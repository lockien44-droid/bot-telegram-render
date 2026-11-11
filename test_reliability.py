"""Offline regression tests: no bank/Telegram/Google requests are issued."""
import copy
import os
import gzip
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

with patch("dotenv.load_dotenv", return_value=False), patch.dict(os.environ, {"BOT_TOKEN": "", "GSHEET_ID": ""}):
    import bot_shop as shop
    import sepay_webhook as payment
    import operations
    import admin_auth

from reliability import EventInbox, ReviewRequired

OID = "ORD20261111134639TEST"


class Sheet:
    def __init__(self, headers, rows=()):
        self.values = [list(headers)] + [list(row) for row in rows]

    def get_all_values(self):
        return copy.deepcopy(self.values)

    def row_values(self, index):
        return list(self.values[index - 1])

    def update_cells(self, cells, **kwargs):
        for cell in cells:
            row = self.values[cell.row - 1]
            row.extend([""] * max(0, cell.col - len(row)))
            row[cell.col - 1] = str(cell.value)

    def append_row(self, row, **kwargs):
        self.values.append([str(x) for x in row])

    def append_rows(self, rows, **kwargs):
        for row in rows:
            self.append_row(row)


class Spreadsheet:
    def __init__(self):
        self.sheet = Sheet(EventInbox.HEADERS)

    def worksheet(self, name):
        return self.sheet


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.order = Sheet(["order_id", "user_id", "stock_code", "qty", "total", "status", "created_at", "qr_msg_id", "paid_at", "tx_id", "delivered_at", "deliver_text"],
                           [[OID, "123", "GPT", "2", "2000", "PENDING", "2026-11-11 13:00:00", "", "", "", "", ""]])
        self.pool = Sheet(["item_id", "stock_code", "secret", "status", "hold_order_id", "sold_order_id", "sold_at", "hold_at", "hold_expires_at"],
                          [["A", "GPT", "account-A", "HELD", OID, "", "", "", ""],
                           ["B", "GPT", "account-B", "HELD", OID, "", "", "", ""]])
        self.res = Sheet(["order_id", "item_id", "sold_at"])
        self.patches = [patch.object(payment, "init_gsheet"), patch.object(payment, "ws_orders", self.order),
                        patch.object(payment, "ws_pool", self.pool), patch.object(payment, "ws_res", self.res),
                        patch.object(payment, "append_fulfillment_rows"), patch.object(payment, "tg_bot", None),
                        patch.object(shop, "notify_admins_order_event", new_callable=AsyncMock)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.payload = {"id": "test-transaction-1", "transferType": "in", "transferAmount": 2000, "content": OID}
        payment._DELIVERING.clear()

    def status(self):
        return self.order.values[1][5]

    async def test_delivered_only_after_successful_send(self):
        async def send(*args):
            self.assertEqual(self.status(), "DELIVERY_PENDING")
            self.assertEqual(args[-1], ["account-A", "account-B"])
            return True
        with patch.object(payment, "send_delivery_message", side_effect=send) as sender:
            await payment.process_payment(self.payload)
            await payment.process_payment(self.payload)
            self.assertEqual(sender.call_count, 1)
        self.assertEqual(self.status(), "DELIVERED")

    async def test_send_failure_recovers_same_sold_items(self):
        with patch.object(payment, "send_delivery_message", new=AsyncMock(return_value=False)):
            with self.assertRaises(RuntimeError):
                await payment.process_payment(self.payload)
        self.assertEqual(self.status(), "DELIVERY_PENDING")
        self.assertTrue(all(row[3] == "SOLD" for row in self.pool.values[1:]))
        with patch.object(payment, "send_delivery_message", new=AsyncMock(return_value=True)) as send:
            await payment.deliver_paid_order(OID)
            self.assertEqual(send.call_args.args[-1], ["account-A", "account-B"])
        self.assertEqual(self.status(), "DELIVERED")

    async def test_partial_stock_never_marks_any_item_sold(self):
        self.pool.values.pop()
        with self.assertRaises(ReviewRequired):
            await payment.process_payment(self.payload)
        self.assertEqual(self.status(), "PAID")
        self.assertEqual(self.pool.values[1][3], "HELD")

    async def test_empty_secret_never_delivers(self):
        self.pool.values[1][2] = ""
        with self.assertRaises(ReviewRequired):
            await payment.process_payment(self.payload)
        self.assertEqual(self.pool.values[1][3], "HELD")

    async def test_wrong_amount_stays_in_review_without_paid_status(self):
        self.payload["transferAmount"] = 1000
        with self.assertRaises(ReviewRequired):
            await payment.process_payment(self.payload)
        self.assertEqual(self.status(), "PENDING")

    async def test_different_transaction_on_paid_order_is_reviewed(self):
        self.order.values[1][5] = "PAID"
        self.order.values[1][9] = "another-transaction"
        with self.assertRaises(ReviewRequired):
            await payment.process_payment(self.payload)

    def test_cancel_cannot_release_paid_stock(self):
        self.order.values[1][5] = "DELIVERY_PENDING"
        with patch.object(shop, "init_sheets"), patch.object(shop, "_ws_orders", self.order):
            with self.assertRaises(ValueError):
                shop.release_hold_by_order_sheet(OID, "CANCELLED")
        self.assertEqual(self.pool.values[1][3], "HELD")

    def test_reserve_create_failure_rolls_back(self):
        with patch.object(shop, "list_pending_orders", return_value=[]), \
             patch.object(shop, "reserve_items_from_pool", return_value=[{"item_id": "A"}]), \
             patch.object(shop, "append_order", side_effect=RuntimeError("write failed")), \
             patch.object(shop, "get_order_sheet", return_value=None), \
             patch.object(shop, "release_hold_by_order_sheet") as release:
            with self.assertRaises(RuntimeError):
                shop.create_reserved_order(123, {"stock_code": "GPT", "price": 2000}, 1, OID, "now")
            release.assert_called_once_with(OID, "CANCELLED")

    async def test_recover_after_stock_sale_before_pending_status_write(self):
        original = payment.update_order_cells
        def fail_once(row, updates):
            if updates.get("status") == "DELIVERY_PENDING":
                raise RuntimeError("simulated process crash")
            return original(row, updates)
        with patch.object(payment, "update_order_cells", side_effect=fail_once):
            with self.assertRaises(RuntimeError):
                await payment.process_payment(self.payload)
        self.assertEqual(self.status(), "PAID")
        self.assertTrue(all(row[3] == "SOLD" for row in self.pool.values[1:]))
        with patch.object(payment, "send_delivery_message", new=AsyncMock(return_value=True)) as send:
            await payment.deliver_paid_order(OID)
            self.assertEqual(send.call_args.args[-1], ["account-A", "account-B"])

    async def test_outgoing_payment_does_not_change_order(self):
        self.payload["transferType"] = "out"
        await payment.process_payment(self.payload)
        self.assertEqual(self.status(), "PENDING")

    def test_amount_parsing_accepts_integral_decimal_without_multiplying_it(self):
        for amount in (2000, 2000.0, "2000.00"):
            self.assertEqual(payment.parse_sepay_payload({"transferAmount": amount})["amount"], 2000)
        self.assertEqual(payment.parse_sepay_payload({"transferAmount": "2000.50"})["amount"], 0)

    def test_simultaneous_orders_cannot_reserve_same_stock(self):
        from concurrent.futures import ThreadPoolExecutor
        for row in self.pool.values[1:]:
            row[3], row[4] = "READY", ""
        orders = Sheet(self.order.values[0])
        reservations = Sheet(["order_id", "item_id", "reserved_at", "expires_at", "released_at", "sold_at", "stock_code"])
        def checkout(i):
            try:
                shop.create_reserved_order(100 + i, {"stock_code": "GPT", "price": 1000}, 2,
                                           f"ORD20261111134639T00{i}", "2026-11-11 13:00:00")
                return True
            except ValueError:
                return False
        with patch.object(shop, "init_sheets"), patch.object(shop, "_ws_orders", orders), \
             patch.object(shop, "_ws_pool", self.pool), patch.object(shop, "_ws_res", reservations):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(checkout, (1, 2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(orders.values), 2)
        self.assertEqual(len({row[4] for row in self.pool.values[1:]}), 1)

    def test_retrying_same_checkout_does_not_reserve_again(self):
        with patch.object(shop, "get_order_sheet", return_value={"user_id": "123", "stock_code": "GPT", "qty": "1"}), \
             patch.object(shop, "reserve_items_from_pool") as reserve:
            self.assertEqual(shop.create_reserved_order(123, {"stock_code": "GPT", "price": 2000}, 1, OID, "now"), OID)
            reserve.assert_not_called()


class InboxTests(unittest.TestCase):
    def test_restart_deduplicates_and_preserves_pending_receipts(self):
        book = Spreadsheet()
        first = EventInbox(book)
        key = first.enqueue("sepay", {"id": 123, "amount": 2000})
        restarted = EventInbox(book)
        self.assertEqual(key, restarted.enqueue("sepay", {"id": 123, "amount": 2000}))
        self.assertEqual(len(restarted.pending()), 1)
        restarted.finish(restarted.pending()[0], "DONE")
        self.assertEqual(EventInbox(book).pending(), [])

    def test_review_is_visible_and_can_be_requeued(self):
        store = EventInbox(Spreadsheet())
        key = store.enqueue("sepay", {"id": 1, "secret": "not-for-dashboard"})
        store.finish(store.pending()[0], "REVIEW", "Amount mismatch")
        self.assertNotIn("payload", store.reviews()[0])
        self.assertEqual(store.pending(), [])
        self.assertTrue(store.retry(key))
        self.assertEqual(len(store.pending()), 1)

    def test_telegram_receipt_stores_only_id(self):
        book = Spreadsheet()
        store = EventInbox(book)
        self.assertFalse(store.telegram_done(10))
        store.telegram_done(10, save=True)
        self.assertTrue(EventInbox(book).telegram_done(10))
        self.assertEqual(book.sheet.values[1][2], "{}")

    def test_checkout_request_reuses_order_id_across_restart(self):
        book = Spreadsheet()
        with patch("test_reliability.OID", OID):
            oid = EventInbox(book).checkout_order_id("callback:1", lambda: OID)
            self.assertEqual(EventInbox(book).checkout_order_id("callback:1", lambda: "WRONG"), oid)

    def test_failed_event_is_not_lost(self):
        book = Spreadsheet()
        store = EventInbox(book)
        store.enqueue("sepay", {"id": 123})
        store.finish(store.pending()[0], "RETRY", "TimeoutError")
        self.assertEqual(EventInbox(book).reviews()[0]["status"], "RETRY")
        self.assertEqual(EventInbox(book).pending(), [])
        with patch("reliability.time.time", return_value=10**12):
            self.assertEqual(len(EventInbox(book).pending()), 1)


class AuthTests(unittest.TestCase):
    def test_signed_session_and_password_rotation(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "test-only-strong-password"}):
            token = admin_auth.create_session()
            self.assertTrue(admin_auth.valid_session(token))
            self.assertFalse(admin_auth.valid_session(token + "x"))
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "rotated-test-password"}):
            self.assertFalse(admin_auth.valid_session(token))

    def test_login_rate_limit(self):
        from fastapi import HTTPException
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "test-only-strong-password"}):
            admin_auth._failures.clear()
            for _ in range(6):
                with self.assertRaises(HTTPException) as failure:
                    admin_auth.check_login("test-client", "bad")
                self.assertEqual(failure.exception.status_code, 401)
            with self.assertRaises(HTTPException) as failure:
                admin_auth.check_login("test-client", "bad")
            self.assertEqual(failure.exception.status_code, 429)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("dotenv.load_dotenv", return_value=False):
            import main
        cls.main = main

    def test_cookie_login_and_query_password_rejection(self):
        from fastapi.testclient import TestClient
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "test-only-password"}), \
             patch("admin_dashboard.notifications_list", return_value={"items": []}):
            admin_auth._failures.clear()
            client = TestClient(self.main.app, base_url="https://testserver")
            self.assertEqual(client.get("/admin/api/notifications?key=test-only-password").status_code, 401)
            login = client.post("/admin/api/login", json={"password": "test-only-password"})
            self.assertEqual(login.status_code, 200)
            self.assertIn("HttpOnly", login.headers["set-cookie"])
            self.assertEqual(client.get("/admin/api/notifications").status_code, 200)
            client.post("/admin/api/logout")
            self.assertEqual(client.get("/admin/api/notifications").status_code, 401)

    def test_payment_webhook_must_persist_before_ack(self):
        from fastapi.testclient import TestClient
        with patch.object(self.main, "verify_sepay_auth", return_value=True), \
             patch.object(self.main, "enqueue_event", side_effect=RuntimeError("storage offline")):
            client = TestClient(self.main.app)
            self.assertEqual(client.post("/webhook/sepay", json={"id": 123}).status_code, 503)
        with patch.object(self.main, "verify_sepay_auth", return_value=True), \
             patch.object(self.main, "enqueue_event", return_value="receipt") as enqueue:
            client = TestClient(self.main.app)
            self.assertEqual(client.post("/webhook/sepay", json={"id": 123}).status_code, 200)
            enqueue.assert_called_once()


class BackupTests(unittest.TestCase):
    def test_restore_to_fake_sheet_preserves_literal_values(self):
        from backup_manager import BackupManager
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.json.gz"
            data = [["secret"], ["=literal-not-formula"], ["001234"]]
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                json.dump({"sheet_name": "TEST", "data": data}, stream)
            manager = object.__new__(BackupManager)
            from unittest.mock import Mock
            manager.gs_sheet = Mock()
            manager.logger = Mock()
            manager.restore_sheet(str(path))
            manager.gs_sheet.worksheet.return_value.update.assert_called_once_with(data, value_input_option="RAW")


if __name__ == "__main__":
    unittest.main()
