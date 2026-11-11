import asyncio
import logging
import os
import re
import secrets
import hashlib
import hmac
import threading
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from telegram import Update

from admin_dashboard import register_admin_routes
from shop_api import register_shop_api_routes
from bot_shop import build_application, claim_telegram_update, setup_bot_commands
from operations import enqueue_event, inbox, worker_loop
from sepay_webhook import expire_scan_once, process_payment, set_telegram_bot, verify_sepay_auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MAIN_ORCHESTRATOR")


_QUIET_PATHS = ("/health", "/ping", "/cron/keepalive", "/favicon.ico")


class _AccessLogFilter(logging.Filter):
    """Suppress uvicorn access logs for keep-alive endpoints (cron-job.org, UptimeRobot, ...)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(path in message for path in _QUIET_PATHS)


class _SecretRedactionFilter(logging.Filter):
    """Prevent Telegram bot tokens from leaking through dependency logs."""

    _telegram_token = re.compile(r"(?i)(?:bot)?\d{6,}:[A-Za-z0-9_-]{20,}")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self._telegram_token.sub("bot[REDACTED]", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


logging.getLogger("uvicorn.access").addFilter(_AccessLogFilter())
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_SecretRedactionFilter())

app = FastAPI()
telegram_app = None
_operations_task = None
_failed_updates = set()

_PAYMENT_TASKS: set[asyncio.Task] = set()


def _track_task(task: asyncio.Task) -> None:
    _PAYMENT_TASKS.add(task)
    task.add_done_callback(_PAYMENT_TASKS.discard)


register_admin_routes(app)
register_shop_api_routes(app)


def public_base_url() -> str:
    raw = (
        os.environ.get("TELEGRAM_WEBHOOK_URL")
        or os.environ.get("WEBHOOK_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("PUBLIC_URL")
        or ""
    ).strip()
    return raw.rstrip("/")


def telegram_webhook_path() -> str:
    return "/webhook/telegram"


def telegram_webhook_secret() -> str:
    configured = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if configured:
        return configured
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required to secure Telegram webhook")
    return hmac.new(token.encode(), b"vm-store-telegram-webhook", hashlib.sha256).hexdigest()


@app.post("/webhook/sepay")
async def sepay_webhook(request: Request):
    if not verify_sepay_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(400, "Expected JSON object")
        await asyncio.to_thread(enqueue_event, "sepay", payload)
        return {"ok": True, "queued": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("sepay_webhook error")
        raise HTTPException(status_code=503, detail="Could not persist payment event; retry required")


@app.post("/jobs/expire")
async def jobs_expire(request: Request):
    sepay_key = os.environ.get("SEPAY_API_KEY", "").strip()
    if sepay_key:
        key = (request.headers.get("x-api-key") or "").strip()
        if not key or not secrets.compare_digest(key, sepay_key):
            raise HTTPException(status_code=401, detail="Unauthorized")
    else:
        if os.environ.get("ALLOW_PUBLIC_EXPIRE", "").strip() != "1":
            raise HTTPException(
                status_code=503,
                detail="SEPAY_API_KEY chưa cấu hình. Bật ALLOW_PUBLIC_EXPIRE=1 nếu thực sự muốn mở.",
            )
    return await expire_scan_once()


def _telegram_update_is_slow_broadcast(payload: dict) -> bool:
    """Lệnh gửi hàng loạt — xử lý nền để webhook trả 200 ngay, tránh Telegram retry."""
    msg = payload.get("message") or payload.get("edited_message") or {}
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return False
    cmd = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
    return cmd in ("/hangve", "/capnhatkho")


@app.post(telegram_webhook_path())
async def telegram_webhook(request: Request):
    if telegram_app is None:
        raise HTTPException(status_code=503, detail="Telegram app is not ready")

    expected_secret = telegram_webhook_secret()
    if expected_secret:
        provided = (request.headers.get("X-Telegram-Bot-Api-Secret-Token") or "").strip()
        if not provided or not secrets.compare_digest(provided, expected_secret):
            raise HTTPException(status_code=401, detail="Bad secret token")

    payload = await request.json()
    update_id = payload.get("update_id")
    update = Update.de_json(payload, telegram_app.bot)

    if not isinstance(update_id, int):
        raise HTTPException(400, "Missing update_id")
    store = await asyncio.to_thread(inbox)
    if await asyncio.to_thread(store.telegram_done, update_id):
        return {"ok": True, "duplicate": True}
    if not await claim_telegram_update(update_id):
        # An in-flight attempt is not a completed receipt. Ask Telegram to retry.
        raise HTTPException(503, "Update is being processed")
    try:
        await telegram_app.process_update(update)
        if update_id in _failed_updates:
            raise RuntimeError("Telegram handler failed")
        await asyncio.to_thread(store.telegram_done, update_id, True)
    except Exception:
        import bot_shop as shop
        shop._TELEGRAM_UPDATE_DEDUP.pop(update_id, None)
        _failed_updates.discard(update_id)
        logger.exception("Telegram update processing failed id=%s", update_id)
        raise HTTPException(503, "Update failed; retry required")
    return {"ok": True}


async def telegram_handler_error(update, context):
    if update is not None:
        _failed_updates.add(update.update_id)
    logger.error("Telegram handler failed: %s", type(context.error).__name__)


@app.get("/")
async def health_check():
    return {"status": "Bot & Webhook are alive!", "telegram_mode": "webhook" if telegram_app else "polling"}


@app.get("/ping")
async def ping():
    return "ok"


@app.get("/health")
async def health():
    """Deep health check: verify Telegram + Sheets reachable."""
    issues: list[str] = []
    if telegram_app is None and public_base_url():
        issues.append("telegram_app_not_initialized")
    try:
        import bot_shop as _shop  # local import to avoid cold-start cost on /ping

        await asyncio.to_thread(_shop.init_sheets)
        if _shop._ws_orders is None:
            issues.append("sheets_not_ready")
    except Exception as e:
        issues.append(f"sheets_error:{type(e).__name__}")

    body = {
        "ok": not issues,
        "release": "reliability-v1",
        "telegram": "webhook" if telegram_app else "polling",
        "ts": int(time.time()),
    }
    if _operations_task is None or _operations_task.done():
        issues.append("operations_worker_not_running")
        body["ok"] = False
    if issues:
        body["issues"] = issues
        raise HTTPException(status_code=503, detail=body)
    return body


@app.head("/health")
async def health_head():
    return None


@app.get("/cron/keepalive")
async def cron_keepalive():
    return {"ok": True, "ts": int(time.time())}


@app.head("/cron/keepalive")
async def cron_keepalive_head():
    return None


@app.head("/")
async def health_check_head():
    return None


def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        logger.info("Starting Telegram bot polling in background thread...")
        tg_app = build_application()
        set_telegram_bot(tg_app.bot)
        tg_app.run_polling(drop_pending_updates=False, stop_signals=False)
    except Exception:
        logger.exception("Telegram bot crashed")
    finally:
        loop.close()


@app.on_event("startup")
async def startup_telegram_webhook():
    global telegram_app, _operations_task
    _operations_task = asyncio.create_task(worker_loop())
    base_url = public_base_url()
    if not base_url:
        logger.info("No public URL configured; Telegram bot will use polling fallback.")
        return

    webhook_url = f"{base_url}{telegram_webhook_path()}"
    telegram_app = build_application()
    telegram_app.add_error_handler(telegram_handler_error)
    await telegram_app.initialize()
    set_telegram_bot(telegram_app.bot)
    await setup_bot_commands(telegram_app)

    secret = telegram_webhook_secret()
    set_webhook_kwargs = {"url": webhook_url, "drop_pending_updates": False}
    if secret:
        set_webhook_kwargs["secret_token"] = secret
    await telegram_app.bot.set_webhook(**set_webhook_kwargs)
    await telegram_app.start()
    logger.info(
        "Telegram webhook is active: %s (secret_token: %s)",
        webhook_url,
        "yes" if secret else "no",
    )


@app.on_event("shutdown")
async def shutdown_telegram_webhook():
    global telegram_app, _operations_task
    if _operations_task:
        _operations_task.cancel()
        await asyncio.gather(_operations_task, return_exceptions=True)
        _operations_task = None

    if _PAYMENT_TASKS:
        logger.info("Waiting for %d in-flight payment tasks...", len(_PAYMENT_TASKS))
        try:
            await asyncio.wait_for(
                asyncio.gather(*list(_PAYMENT_TASKS), return_exceptions=True),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Some payment tasks did not finish within grace period")

    if telegram_app is None:
        return
    await telegram_app.stop()
    await telegram_app.shutdown()
    telegram_app = None


if __name__ == "__main__":
    if not public_base_url():
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    logger.info("Starting FastAPI webhook server on port %s...", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
