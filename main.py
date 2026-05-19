import asyncio
import logging
import os
import threading
import time

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from telegram import Update

from admin_dashboard import register_admin_routes
from shop_api import register_shop_api_routes
from bot_shop import build_application, setup_bot_commands
from sepay_webhook import expire_scan_once, process_payment, set_telegram_bot, verify_sepay_auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MAIN_ORCHESTRATOR")

app = FastAPI()
telegram_app = None
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


@app.post("/webhook/sepay")
async def sepay_webhook(request: Request):
    if not verify_sepay_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        payload = await request.json()
        asyncio.create_task(process_payment(payload))
        return {"ok": True, "queued": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/jobs/expire")
async def jobs_expire(request: Request):
    sepay_key = os.environ.get("SEPAY_API_KEY", "").strip()
    if sepay_key:
        key = (request.headers.get("x-api-key") or "").strip()
        if key != sepay_key:
            raise HTTPException(status_code=401, detail="Unauthorized")
    return await expire_scan_once()


@app.post(telegram_webhook_path())
async def telegram_webhook(request: Request):
    if telegram_app is None:
        raise HTTPException(status_code=503, detail="Telegram app is not ready")
    payload = await request.json()
    update = Update.de_json(payload, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}


@app.get("/")
async def health_check():
    return {"status": "Bot & Webhook are alive!", "telegram_mode": "webhook" if telegram_app else "polling"}


@app.get("/ping")
async def ping():
    return "ok"


@app.get("/health")
async def health():
    return {
        "ok": True,
        "telegram": "webhook" if telegram_app else "polling",
        "ts": int(time.time()),
    }


@app.head("/health")
async def health_head():
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
        tg_app.run_polling(drop_pending_updates=True, stop_signals=False)
    except Exception:
        logger.exception("Telegram bot crashed")
    finally:
        loop.close()


@app.on_event("startup")
async def startup_telegram_webhook():
    global telegram_app
    base_url = public_base_url()
    if not base_url:
        logger.info("No public URL configured; Telegram bot will use polling fallback.")
        return

    webhook_url = f"{base_url}{telegram_webhook_path()}"
    telegram_app = build_application()
    await telegram_app.initialize()
    set_telegram_bot(telegram_app.bot)
    await setup_bot_commands(telegram_app)
    await telegram_app.bot.set_webhook(webhook_url, drop_pending_updates=True)
    await telegram_app.start()
    logger.info("Telegram webhook is active: %s", webhook_url)


@app.on_event("shutdown")
async def shutdown_telegram_webhook():
    global telegram_app
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
