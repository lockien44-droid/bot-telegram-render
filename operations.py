"""Durable payment worker, recovery, maintenance and operator review queue."""
import asyncio
import json
import logging
import threading

from reliability import EventInbox, ReviewRequired, serialized

logger = logging.getLogger(__name__)
_inbox = None
_worker_lock = threading.Lock()


@serialized
def inbox():
    global _inbox
    if _inbox is None:
        import bot_shop as shop
        shop.init_sheets()
        _inbox = EventInbox(shop._gs_sheet)
    return _inbox


def enqueue_event(kind, payload):
    return inbox().enqueue(kind, payload)


async def alert_review(event, reason):
    try:
        from bot_shop import notify_admins, _esc_md2
        from sepay_webhook import tg_bot
        # No raw bank payload or credentials in alerts.
        if tg_bot:
            await notify_admins(None, _esc_md2(f"⚠️ Cần xử lý thanh toán/giao hàng\nMã sự kiện: {event['event_id']}\n{reason}"), bot=tg_bot)
    except Exception:
        logger.exception("Could not send operator alert")


async def worker_once():
    if not _worker_lock.acquire(blocking=False):
        return
    try:
        store = await asyncio.to_thread(inbox)
        for event in await asyncio.to_thread(store.pending):
            payload = json.loads(event["payload"])
            try:
                if event["kind"] == "sepay":
                    from sepay_webhook import process_payment
                    await process_payment(payload)
                elif event["kind"] == "delivery":
                    from sepay_webhook import deliver_paid_order
                    await deliver_paid_order(payload["order_id"])
                elif event["kind"] == "backup":
                    from admin_services import run_backup
                    await asyncio.to_thread(run_backup)
                else:
                    raise ReviewRequired("Unknown event kind")
            except ReviewRequired as exc:
                await asyncio.to_thread(store.finish, event, "REVIEW", str(exc))
                await alert_review(event, str(exc))
            except Exception as exc:
                logger.exception("Event %s failed", event["event_id"])
                # Exception messages can contain URLs/credentials: persist only the class.
                await asyncio.to_thread(store.finish, event, "RETRY", type(exc).__name__)
                if int(event["attempts"] or 0) in (0, 4):
                    await alert_review(event, "Lỗi kết nối/xử lý; hệ thống sẽ tự thử lại.")
            else:
                await asyncio.to_thread(store.finish, event, "DONE")
    finally:
        _worker_lock.release()


async def maintenance_once():
    import bot_shop as shop
    from sepay_webhook import recoverable_orders
    for oid in await asyncio.to_thread(recoverable_orders):
        await asyncio.to_thread(enqueue_event, "delivery", {"id": oid, "order_id": oid})
    await asyncio.to_thread(shop.release_orphan_holds)
    import os
    if os.getenv("BACKUP_DRIVE_FOLDER_ID", "1mjOAK0R5A99KfGDfymC9Cy0s77WdGJ9v").strip() and shop.now_dt().hour >= 3:
        day = shop.now_dt().strftime("%Y-%m-%d")
        await asyncio.to_thread(enqueue_event, "backup", {"id": day})


async def worker_loop():
    tick = 0
    while True:
        try:
            if tick % 3 == 0:
                await maintenance_once()
            await worker_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Operations worker cycle failed; will retry")
        tick += 1
        await asyncio.sleep(20)
