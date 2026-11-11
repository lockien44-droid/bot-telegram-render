"""Shared single-process storage guard and durable Google Sheets event inbox.

Run ONE service instance/worker while Sheets is the authoritative database.
This lock also covers the polling thread, FastAPI threadpool and webhook loop.
"""
import functools
import hashlib
import json
import re
import threading
import time
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
from gspread.cell import Cell

STORAGE_LOCK = threading.RLock()


def local_now():
    return datetime.now(ZoneInfo(os.getenv("APP_TIMEZONE", "").strip() or "Asia/Ho_Chi_Minh"))


def serialized(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with STORAGE_LOCK:
            return fn(*args, **kwargs)
    return wrapped


class ReviewRequired(Exception):
    """A valid payment needs an operator decision, not an automatic retry."""


class EventInbox:
    HEADERS = ["event_id", "kind", "payload", "status", "attempts", "next_attempt", "error", "updated_at"]

    def __init__(self, spreadsheet):
        self._rows_cache = None
        self._rows_cache_at = 0
        try:
            self.ws = spreadsheet.worksheet("BOT_EVENTS")
        except gspread.WorksheetNotFound:
            self.ws = spreadsheet.add_worksheet(title="BOT_EVENTS", rows=1000, cols=8)
            self.ws.append_row(self.HEADERS, value_input_option="RAW")
        if self.ws.row_values(1) != self.HEADERS:
            raise RuntimeError("BOT_EVENTS headers do not match; refusing to overwrite data")

    @serialized
    def rows(self):
        if self._rows_cache is None or time.monotonic() - self._rows_cache_at > 5:
            self._rows_cache = [dict(zip(self.HEADERS, row + [""] * (8 - len(row))), _row=i)
                                for i, row in enumerate(self.ws.get_all_values()[1:], start=2)]
            self._rows_cache_at = time.monotonic()
        return self._rows_cache

    @serialized
    def enqueue(self, kind, payload):
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        if len(raw) > 45000:
            raise ValueError("Webhook payload exceeds supported size")
        # The provider transaction ID is the durable idempotency key.
        identity = str(payload.get("referenceCode") or payload.get("id") or payload.get("transaction_id") or payload.get("update_id") or raw)
        key = hashlib.sha256((kind + ":" + identity).encode()).hexdigest()
        if not any(row["event_id"] == key for row in self.rows()):
            self._rows_cache = None
            self.ws.append_row([key, kind, raw, "PENDING", 0, 0, "", time.time()], value_input_option="RAW")
            self._rows_cache = None
        return key

    @serialized
    def pending(self, limit=10):
        now = time.time()
        return [r for r in self.rows() if r["status"] in ("PENDING", "RETRY")
                and float(r["next_attempt"] or 0) <= now][:limit]

    @serialized
    def finish(self, row, status, error=""):
        attempts = int(row["attempts"] or 0) + 1
        delay = min(3600, 15 * 2 ** min(attempts, 8)) if status == "RETRY" else 0
        values = {"status": status, "attempts": attempts, "next_attempt": time.time() + delay,
                  "error": error[:500], "updated_at": time.time()}
        self._rows_cache = None
        self.ws.update_cells([Cell(row["_row"], self.HEADERS.index(k) + 1, v)
                              for k, v in values.items()], value_input_option="RAW")
        self._rows_cache = None

    @serialized
    def reviews(self):
        # Never return full bank payloads or account credentials to the dashboard.
        result = []
        for row in self.rows():
            if row["status"] not in ("REVIEW", "RETRY"):
                continue
            item = {k: row[k] for k in ("event_id", "kind", "status", "attempts", "error", "updated_at")}
            payload = json.loads(row["payload"])
            text = str(payload.get("order_id") or payload.get("description") or payload.get("content") or "")
            match = re.search(r"ORD[0-9]{14}[A-Z0-9]{4}", text.upper())
            item["order_id"] = match.group(0) if match else ""
            result.append(item)
        return result

    @serialized
    def retry(self, event_id):
        for row in self.rows():
            if row["event_id"] == event_id and row["status"] in ("REVIEW", "RETRY"):
                self.finish(row, "PENDING", row["error"])
                return True
        return False

    @serialized
    def telegram_done(self, update_id, save=False):
        key = f"telegram:{update_id}"
        if any(row["event_id"] == key for row in self.rows()):
            return True
        if save:
            # Store only the ID, never mailbox/2FA credentials from Telegram messages.
            self._rows_cache = None
            self.ws.append_row([key, "telegram_receipt", "{}", "DONE", 1, 0, "", time.time()],
                               value_input_option="RAW")
            self._rows_cache = None
        return False

    @serialized
    def checkout_order_id(self, request_id, factory):
        key = "checkout:" + hashlib.sha256(request_id.encode()).hexdigest()
        for row in self.rows():
            if row["event_id"] == key:
                return json.loads(row["payload"])["order_id"]
        oid = factory()
        self._rows_cache = None
        self.ws.append_row([key, "checkout_receipt", json.dumps({"order_id": oid}), "DONE", 1, 0, "", time.time()],
                           value_input_option="RAW")
        self._rows_cache = None
        return oid
