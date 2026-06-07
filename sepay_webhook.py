import os
import io
import re
import json
import asyncio
import logging
import secrets
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
from gspread.cell import Cell
from typing import Any, Dict, Optional, List, Tuple

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks

import gspread
from google.oauth2.service_account import Credentials

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode

# =========================
# LOGGING
# =========================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("sepay_webhook")

# =========================
# ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SEPAY_API_KEY = os.getenv("SEPAY_API_KEY", "").strip()

GSHEET_ID = os.getenv("GSHEET_ID", "").strip()
GSVC_JSON = os.getenv("GSVC_JSON", "").strip()
if GSVC_JSON and not os.path.isabs(GSVC_JSON):
    GSVC_JSON = str(BASE_DIR / GSVC_JSON)

ORDERS_TAB = os.getenv("ORDERS_TAB", "ORDERS").strip()
POOL_TAB = os.getenv("POOL_TAB", "POOL").strip()
RES_TAB = os.getenv("RESERVATIONS_TAB", "RESERVATIONS").strip()
FUL_TAB = os.getenv("FULFILLMENTS_TAB", "FULFILLMENTS").strip()
SUPPORT_TELE_LINK = os.getenv("SUPPORT_TELE_LINK", "https://t.me/minhgear5").strip()
SHEETS_LOCK = asyncio.Lock()

def kb_after_delivery() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Hỗ trợ", url=SUPPORT_TELE_LINK)],
        [InlineKeyboardButton("⬅️ Menu", callback_data="back_main")],
    ])

ORDER_TTL_SECONDS = int(os.getenv("ORDER_TTL_SECONDS", "300"))  # 5 phút

# If true: only mark PAID/DELIVERED when transferAmount == order.total
CHECK_AMOUNT = os.getenv("CHECK_AMOUNT", "1").strip() not in ("0", "false", "False")

# Extract order id from description/content
ORDER_ID_REGEX = os.getenv(
    "ORDER_ID_REGEX",
    r"\bORD\d{14}[A-Z0-9]{4}\b"
).strip()

app = FastAPI(title="SePay Webhook AutoDeliver")
tg_bot: Optional[Bot] = Bot(token=BOT_TOKEN) if BOT_TOKEN else None


def set_telegram_bot(bot: Bot) -> None:
    global tg_bot
    tg_bot = bot

# =========================
# GSheet globals
# =========================
gs_client = None
gs_sheet = None
ws_orders = None
ws_pool = None
ws_res = None
ws_ful = None

def release_hold_by_order(order_id: str, mark_status: str = "EXPIRED") -> int:
    """
    POOL: HELD + hold_order_id=order_id -> READY (xóa hold fields)
    RESERVATIONS: released_at = now
    ORDERS: status = mark_status
    """
    init_gsheet()

    # ----- POOL -----
    pool_vals = ws_pool.get_all_values()
    if len(pool_vals) < 2:
        return 0
    ph = normalize_headers(pool_vals[0])

    c_status = ph.get("status")
    c_hold_oid = ph.get("hold_order_id")
    c_hold_at = ph.get("hold_at")
    c_hold_exp = ph.get("hold_expires_at")

    if c_status is None or c_hold_oid is None:
        return 0

    released = 0
    cells: List[Cell] = []
    for i in range(1, len(pool_vals)):
        rownum = i + 1
        row = pool_vals[i]

        hold_oid = (row[c_hold_oid] or "").strip() if c_hold_oid < len(row) else ""
        st = (row[c_status] or "").strip().upper() if c_status < len(row) else ""

        if norm_oid(hold_oid) == norm_oid(order_id) and st == "HELD":
            cells.append(Cell(rownum, c_status + 1, "READY"))
            cells.append(Cell(rownum, c_hold_oid + 1, ""))

            if c_hold_at is not None:
                cells.append(Cell(rownum, c_hold_at + 1, ""))
            if c_hold_exp is not None:
                cells.append(Cell(rownum, c_hold_exp + 1, ""))

            released += 1

    if cells:
        ws_pool.update_cells(cells, value_input_option="USER_ENTERED")

    # ----- RESERVATIONS.released_at -----
    try:
        res_vals = ws_res.get_all_values()
        if len(res_vals) >= 2:
            rh = normalize_headers(res_vals[0])
            c_oid = rh.get("order_id")
            c_rel = rh.get("released_at")
            if c_oid is not None and c_rel is not None:
                res_cells: List[Cell] = []
                nowv = now_str()
                for i in range(1, len(res_vals)):
                    rownum = i + 1
                    row = res_vals[i]
                    oid = (row[c_oid] or "").strip() if c_oid < len(row) else ""
                    if norm_oid(oid) == norm_oid(order_id):
                        res_cells.append(Cell(rownum, c_rel + 1, nowv))
                if res_cells:
                    ws_res.update_cells(res_cells, value_input_option="USER_ENTERED")
    except Exception:
        pass

    return released

def parse_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def is_expired(created_at: str) -> bool:
    dt = parse_dt(created_at)
    if not dt:
        return False
    return (datetime.now() - dt).total_seconds() > ORDER_TTL_SECONDS

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def verify_sepay_auth(request: Request) -> bool:
    """Fail-closed: nếu chưa cấu hình SEPAY_API_KEY thì từ chối, trừ khi bật
    ALLOW_PUBLIC_SEPAY=1 (chỉ dùng cho dev/local)."""
    if not SEPAY_API_KEY:
        if os.getenv("ALLOW_PUBLIC_SEPAY", "").strip() == "1":
            return True
        logger.warning("verify_sepay_auth: SEPAY_API_KEY missing; rejecting request")
        return False

    auth = (
        request.headers.get("Authorization")
        or request.headers.get("authorization")
        or request.headers.get("x-api-key")
        or ""
    ).strip()

    if auth.lower().startswith("apikey "):
        key = auth.split(" ", 1)[1].strip()
    else:
        key = auth

    if not key:
        return False
    try:
        return secrets.compare_digest(key, SEPAY_API_KEY)
    except Exception:
        return False

def init_gsheet() -> None:
    global gs_client, gs_sheet, ws_orders, ws_pool, ws_res, ws_ful

    if ws_orders and ws_pool and ws_res:
        return

    if not GSHEET_ID:
        raise RuntimeError("Missing GSHEET_ID")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    json_content = os.getenv("GOOGLE_JSON_CONTENT", "").strip()
    if json_content:
        creds = Credentials.from_service_account_info(json.loads(json_content), scopes=scopes)
        logger.info("GSheet creds from GOOGLE_JSON_CONTENT")
    elif GSVC_JSON and os.path.exists(GSVC_JSON):
        creds = Credentials.from_service_account_file(GSVC_JSON, scopes=scopes)
        logger.info("GSheet creds from file %s", GSVC_JSON)
    else:
        raise RuntimeError("Missing GOOGLE_JSON_CONTENT or GSVC_JSON file")
    gs_client = gspread.authorize(creds)
    gs_sheet = gs_client.open_by_key(GSHEET_ID)

    ws_orders = gs_sheet.worksheet(ORDERS_TAB)
    ws_pool = gs_sheet.worksheet(POOL_TAB)
    ws_res = gs_sheet.worksheet(RES_TAB)
    try:
        ws_ful = gs_sheet.worksheet(FUL_TAB)
    except Exception:
        ws_ful = None


def normalize_headers(headers: List[str]) -> Dict[str, int]:
    return {str(h).strip().lower(): i for i, h in enumerate(headers)}


def safe_int(v: Any, default: int = 0) -> int:
    try:
        s = str(v).strip().replace(".", "").replace(",", "")
        return int(float(s))
    except Exception:
        return default

def norm_oid(s: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", (s or "").upper())


def extract_order_id(text: str) -> Optional[str]:
    if not text:
        return None
    text_u = (text or "").upper()

    # dùng regex từ ENV nếu có
    m = re.search(ORDER_ID_REGEX, text_u)
    if not m:
        return None

    # norm_oid sẽ tự bỏ '-' và ký tự lạ => ra chuẩn không dấu
    return norm_oid(m.group(0))


def get_order_by_id(order_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[int], str]:
    init_gsheet()
    values = ws_orders.get_all_values()
    if len(values) < 2:
        return None, None, "ORDERS empty"

    headers = normalize_headers(values[0])
    c_oid = headers.get("order_id")
    if c_oid is None:
        return None, None, "Missing column order_id"

    def get_cell(row: List[str], key: str) -> str:
        c = headers.get(key.lower())
        if c is None or c >= len(row):
            return ""
        return (row[c] or "").strip()

    for i in range(1, len(values)):
        row = values[i]
        oid = (row[c_oid] or "").strip()
        if norm_oid(oid) == norm_oid(order_id):
            data = {
                "order_id": oid,
                "user_id": get_cell(row, "user_id"),
                "stock_code": get_cell(row, "stock_code"),
                "qty": safe_int(get_cell(row, "qty")) or 1,
                "total": safe_int(get_cell(row, "total")),
                "status": get_cell(row, "status"),
                "created_at": get_cell(row, "created_at"),
                "qr_msg_id": get_cell(row, "qr_msg_id"),
                "paid_at": get_cell(row, "paid_at"),
                "tx_id": get_cell(row, "tx_id"),
                "delivered_at": get_cell(row, "delivered_at"),
                "deliver_text": get_cell(row, "deliver_text"),
            }
            return data, (i + 1), ""
    return None, None, "Order not found"

def update_order_cells(rownum: int, updates: Dict[str, Any]) -> None:
    init_gsheet()
    values = ws_orders.get_all_values()
    headers = normalize_headers(values[0])

    cells: List[Cell] = []
    for k, v in updates.items():
        col = headers.get(k.lower())
        if col is None:
            continue
        cells.append(Cell(rownum, col + 1, "" if v is None else str(v)))

    if cells:
        ws_orders.update_cells(cells, value_input_option="USER_ENTERED")



def pool_take_held_and_mark_sold(order_id: str) -> List[Dict[str, str]]:
    """
    Tìm các item HELD trong POOL có hold_order_id=order_id -> mark SOLD,
    trả về list secrets.
    """
    init_gsheet()
    values = ws_pool.get_all_values()
    if len(values) < 2:
        return []

    h = normalize_headers(values[0])
    c_item = h.get("item_id")
    c_stock = h.get("stock_code")
    c_secret = h.get("secret")
    c_status = h.get("status")
    c_hold_oid = h.get("hold_order_id")
    c_sold_oid = h.get("sold_order_id")
    c_sold_at = h.get("sold_at")

    if c_status is None or c_hold_oid is None or c_secret is None:
        logger.warning("POOL missing required columns")
        return []

    items: List[Dict[str, str]] = []
    cells: List[Cell] = []          # ✅ gom Cell để batch update
    sold_time = now_str()           # ✅ dùng 1 timestamp cho đồng bộ

    for i in range(1, len(values)):
        rownum = i + 1
        row = values[i]

        hold_oid = (row[c_hold_oid] or "").strip() if c_hold_oid < len(row) else ""
        st = (row[c_status] or "").strip().upper() if c_status < len(row) else ""

        if norm_oid(hold_oid) == norm_oid(order_id) and st == "HELD":
            item_id = (row[c_item] or "").strip() if c_item is not None and c_item < len(row) else ""
            stock_code = (row[c_stock] or "").strip() if c_stock is not None and c_stock < len(row) else ""
            secret = (row[c_secret] or "").strip() if c_secret < len(row) else ""

            # ✅ THAY vì update_cell nhiều lần -> gom Cell
            cells.append(Cell(rownum, c_status + 1, "SOLD"))
            if c_sold_oid is not None:
                cells.append(Cell(rownum, c_sold_oid + 1, order_id))
            if c_sold_at is not None:
                cells.append(Cell(rownum, c_sold_at + 1, sold_time))

            items.append({"item_id": item_id, "stock_code": stock_code, "secret": secret})

    # ✅ update POOL 1 lần
    if cells:
        ws_pool.update_cells(cells, value_input_option="USER_ENTERED")

    # update RESERVATIONS.sold_at (giữ nguyên logic cũ của bạn)
    try:
        res_vals = ws_res.get_all_values()
        if len(res_vals) >= 2:
            rh = normalize_headers(res_vals[0])
            c_oid = rh.get("order_id")
            c_sold = rh.get("sold_at")

            if c_oid is not None and c_sold is not None:
                res_cells: List[Cell] = []

                for i in range(1, len(res_vals)):
                    rownum = i + 1
                    row = res_vals[i]
                    oid = (row[c_oid] or "").strip() if c_oid < len(row) else ""
                    if norm_oid(oid) == norm_oid(order_id):
                        res_cells.append(Cell(rownum, c_sold + 1, sold_time))

                if res_cells:
                    ws_res.update_cells(res_cells, value_input_option="USER_ENTERED")
    except Exception:
        pass

    return items


def append_fulfillment_rows(order_id: str, items: List[Dict[str, str]], delivered_at: str) -> None:
    if not ws_ful:
        return
    vals = ws_ful.get_all_values()
    if not vals:
        return
    h = normalize_headers(vals[0])

    def make_row():
        return [""] * len(h)

    def put(row: List[str], key: str, val: Any):
        c = h.get(key.lower())
        if c is not None:
            row[c] = "" if val is None else str(val)

    for it in items:
        row = make_row()
        put(row, "order_id", order_id)
        put(row, "item_id", it.get("item_id", ""))
        put(row, "stock_code", it.get("stock_code", ""))
        put(row, "secret", it.get("secret", ""))
        put(row, "delivered_at", delivered_at)
        ws_ful.append_row(row, value_input_option="USER_ENTERED")

# Link hỗ trợ (nên lấy từ ENV cho tiện)
SUPPORT_TELE_LINK = os.getenv("SUPPORT_TELE_LINK", "https://t.me/minhgear5").strip()
SUPPORT_ZALO_LINK = os.getenv("SUPPORT_ZALO_LINK", "https://zalo.me/0342324611").strip()

def kb_support_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Hỗ trợ", url=SUPPORT_TELE_LINK),
            InlineKeyboardButton("📱 Zalo", url=SUPPORT_ZALO_LINK),
        ]
    ])

def kb_delivered() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="back_main")]])


def caption_delivered(order_id: str, stock_code: str, qty: int) -> str:
    return (
        "✅ *THANH TOÁN THÀNH CÔNG*\n\n"
        f"🧾 Mã đơn: `{order_id}`\n"
        f"📦 SP: `{stock_code}`\n"
        f"🔢 SL: *{qty}*\n"
        "🎁 Đã giao hàng tự động.\n\n"
        "📎 *Thông tin nhận được đã gửi trong file .txt* ở tin nhắn bên dưới."
    )


async def gs_call(fn, *args, **kwargs):
    async with SHEETS_LOCK:
        last_err: Optional[Exception] = None
        for attempt, delay in enumerate((0, 2, 5, 12, 20)):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as e:
                last_err = e
                if "429" in str(e) and attempt < 4:
                    logger.warning("Sheets quota 429, retry %s/%s fn=%s", attempt + 1, 5, fn.__name__)
                    continue
                raise
        if last_err:
            raise last_err


async def edit_text_safe(user_id: int, msg_id: int, text: str, kb: InlineKeyboardMarkup):
    if not tg_bot:
        return
    try:
        await tg_bot.edit_message_text(
            chat_id=user_id,
            message_id=msg_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


async def edit_caption_safe(user_id: int, msg_id: int, caption: str, kb: InlineKeyboardMarkup):
    if not tg_bot:
        return
    try:
        await tg_bot.edit_message_caption(
            chat_id=user_id,
            message_id=msg_id,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
    except Exception:
        pass


async def edit_checkout_safe(user_id: int, msg_id: int, text: str, kb: InlineKeyboardMarkup):
    # ưu tiên caption, fail thì edit text
    await edit_caption_safe(user_id, msg_id, text, kb)
    await edit_text_safe(user_id, msg_id, text, kb)


async def send_delivery_message(user_id: int, order_id: str, stock_code: str, qty: int, secrets: List[str]) -> bool:
    if not tg_bot:
        return False

    # clean + tránh vỡ Markdown
    cleaned = [(s or "").replace("`", "'").strip() for s in secrets if (s or "").strip()]

    # File txt: mỗi account cách nhau 2 dòng + separator
    lines_plain: List[str] = []
    for i, s in enumerate(cleaned, start=1):
        if i > 1:
            lines_plain.append("")
            lines_plain.append("====================")
            lines_plain.append("")
            lines_plain.append("")   # thêm 1 dòng trống nữa cho thoáng (đủ 2 dòng trống)
        lines_plain.append(f"{i}) {s}")

    delivered_at = now_str()

    content = (
        f"ORDER: {order_id}\n"
        f"PRODUCT: {stock_code}\n"
        f"QTY: {qty}\n"
        f"DELIVERED_AT: {delivered_at}\n"
        "====================\n"
        + "\n".join(lines_plain)
        + "\n"
    )

    bio = io.BytesIO(content.encode("utf-8"))
    bio.name = f"{order_id}.txt"
    bio.seek(0)

    try:
        from bot_shop import file_delivery_line, usage_guide_line_for_stock

        usage_guide_line = await usage_guide_line_for_stock(stock_code)
        guide_or_file_line = usage_guide_line or file_delivery_line()
    except Exception as e:
        logger.warning("load usage guide failed (stock=%s): %s", stock_code, e)
        guide_or_file_line = "📄 File .txt chứa đầy đủ thông tin ở đây (bấm để tải & copy nhanh)."

    # 1) GỬI FILE TRƯỚC (KHÔNG caption, KHÔNG parse_mode) => cực ổn định
    try:
        caption_doc = (
            "✅ *MUA HÀNG THÀNH CÔNG*\n\n"
            f"🧾 Mã đơn: `{order_id}`\n\n"
            f"📦 SP: `{stock_code}`\n\n"
            f"🔢 SL: *{qty}*\n\n\n"
            f"{guide_or_file_line}\n\n"
            "🔐 Nếu là tài khoản, vui lòng đổi mật khẩu ngay sau khi đăng nhập.\n\n"
            "❗ Nếu tài khoản lỗi/không đăng nhập được hoặc có vấn đề, hãy bấm *Hỗ trợ* bên dưới."
)
        await tg_bot.send_document(
            chat_id=user_id,
            document=bio,
            caption=caption_doc,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_support_only(),   # <-- thêm nút Hỗ trợ ngay ở tin nhắn file
)
        return True
    except Exception as e:
        logger.exception("send_document FAILED (order=%s): %s", order_id, e)
        return False
    
def parse_sepay_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    desc = (payload.get("description") or payload.get("content") or "").strip()
    amount = safe_int(payload.get("transferAmount"), 0)
    txn_id = (payload.get("referenceCode") or payload.get("id") or "").__str__().strip()
    transfer_type = (payload.get("transferType") or "").strip().lower()
    return {"description": desc, "amount": amount, "txn_id": txn_id, "transfer_type": transfer_type}


# ===== Idempotency =====
# Bộ nhớ tạm các tx_id đã xử lý xong (per-process). Tránh xử lý lặp khi SePay
# bắn lại cùng 1 transaction (thường do retry sau khi timeout).
_PROCESSED_TX_IDS: List[str] = []
_PROCESSED_TX_LIMIT = 2000
_PROCESSING_TX_IDS: Dict[str, asyncio.Lock] = {}
_PROCESSING_TX_GLOBAL_LOCK = asyncio.Lock()


def _remember_tx(tx_id: str) -> None:
    if not tx_id:
        return
    _PROCESSED_TX_IDS.append(tx_id)
    if len(_PROCESSED_TX_IDS) > _PROCESSED_TX_LIMIT:
        del _PROCESSED_TX_IDS[: len(_PROCESSED_TX_IDS) - _PROCESSED_TX_LIMIT]


async def _acquire_tx_lock(tx_id: str) -> asyncio.Lock:
    async with _PROCESSING_TX_GLOBAL_LOCK:
        lock = _PROCESSING_TX_IDS.get(tx_id)
        if lock is None:
            lock = asyncio.Lock()
            _PROCESSING_TX_IDS[tx_id] = lock
        return lock


async def process_payment(payload: Dict[str, Any]) -> None:
    info = parse_sepay_payload(payload)
    amount = info["amount"]
    desc = info["description"]
    txn_id = info["txn_id"]
    transfer_type = info["transfer_type"]

    # chỉ nhận tiền vào
    if transfer_type and transfer_type != "in":
        logger.info("skip transfer_type=%s", transfer_type)
        return

    # Idempotency: bỏ qua nếu tx_id này đã xử lý gần đây
    if txn_id and txn_id in _PROCESSED_TX_IDS:
        logger.info("Skip duplicate tx_id=%s (already processed)", txn_id)
        return

    # Serialize per-tx_id để 2 webhook đồng thời không cùng chạy 1 đơn
    tx_lock = await _acquire_tx_lock(txn_id) if txn_id else None
    if tx_lock:
        await tx_lock.acquire()
    try:
        if txn_id and txn_id in _PROCESSED_TX_IDS:
            logger.info("Skip duplicate tx_id=%s (processed during wait)", txn_id)
            return

        extracted = extract_order_id(desc)
        if not extracted:
            logger.warning("No order_id found in desc=%s", desc)
            return

        # 1) tìm order trong ORDERS trực tiếp bằng extracted
        order, rownum, err = await gs_call(get_order_by_id, extracted)
        if not order or not rownum:
            logger.warning("Order not found | extracted=%s | err=%s", extracted, err)
            return

        # ✅ canonical_oid: lấy đúng order_id như trong sheet (có thể có '-')
        canonical_oid = (order.get("order_id") or extracted).strip()

        status = (order.get("status") or "PENDING").upper()
        if status == "DELIVERED":
            logger.info("Skip: already DELIVERED %s", canonical_oid)
            _remember_tx(txn_id)
            return

        created_at = (order.get("created_at") or "").strip()

        user_id_s = (order.get("user_id") or "").strip()
        qr_msg_id_s = (order.get("qr_msg_id") or "").strip()
        stock_code = (order.get("stock_code") or "").strip()
        qty = int(order.get("qty") or 1)
        total_need = int(order.get("total") or 0)

        if not user_id_s.isdigit():
            logger.warning("Bad user_id in order %s: %s", canonical_oid, user_id_s)
            return
        user_id = int(user_id_s)

        if CHECK_AMOUNT and total_need and amount != total_need:
            logger.warning("Amount mismatch for %s: got=%s need=%s", canonical_oid, amount, total_need)
            return

        if status in ("CANCELLED", "EXPIRED"):
            from bot_shop import reserve_items_from_pool

            held = await gs_call(reserve_items_from_pool, stock_code, qty, canonical_oid, ORDER_TTL_SECONDS)
            if len(held) < qty:
                logger.warning(
                    "Paid but cannot re-hold stock | order=%s need=%s got=%s",
                    canonical_oid, qty, len(held),
                )
                return
            logger.info("Re-held stock for paid %s order (was %s)", canonical_oid, status)
            status = "PENDING"

        resume_paid = status == "PAID"
        existing_tx = (order.get("tx_id") or "").strip()
        if existing_tx:
            if norm_oid(existing_tx) == norm_oid(txn_id):
                if status == "DELIVERED":
                    logger.info("Skip: already DELIVERED %s", canonical_oid)
                    _remember_tx(txn_id)
                    return
                if status == "PAID":
                    resume_paid = True
                elif status == "PENDING":
                    pass
                else:
                    logger.info("Skip retry: same tx_id=%s | order=%s", existing_tx, canonical_oid)
                    _remember_tx(txn_id)
                    return
            elif not resume_paid:
                logger.warning(
                    "Order already has tx_id=%s but got new txn_id=%s | order=%s",
                    existing_tx, txn_id, canonical_oid,
                )
                return

        # Thanh toán đúng hạn nhưng webhook trễ — vẫn giao nếu còn HELD
        if status == "PENDING" and created_at and is_expired(created_at):
            logger.info("Late payment accepted for %s (past TTL)", canonical_oid)

        # 2) mark PAID
        if not resume_paid:
            paid_at = now_str()
            await gs_call(update_order_cells, rownum, {"status": "PAID", "paid_at": paid_at, "tx_id": txn_id})

        # 3) take HELD -> SOLD and get secrets
        items = await gs_call(pool_take_held_and_mark_sold, canonical_oid)

        secrets = [
            (it.get("secret") or "").strip()
            for it in items
            if (it.get("secret") or "").strip()
        ]

        # ✅ không lấy được HELD/secret => KHÔNG DELIVERED
        if not items or not secrets:
            logger.warning(
                "No items/secrets from POOL for order=%s | items=%s | secrets=%s. Keep status=PAID",
                canonical_oid, len(items), len(secrets)
            )
            await gs_call(
                update_order_cells,
                rownum,
                {"status": "PAID", "deliver_text": "(POOL_EMPTY)", "delivered_at": ""},
            )
            try:
                from bot_shop import notify_admins_order_event

                paid_row = dict(order)
                paid_row["order_id"] = canonical_oid
                paid_row["status"] = "PAID"
                await notify_admins_order_event(None, "paid", paid_row, bot=tg_bot)
            except Exception as e:
                logger.warning("notify_admins_order_event paid failed: %s", e)
            return

        delivered_at = now_str()
        deliver_text_plain = "\n".join([f"{i}) {s}" for i, s in enumerate(secrets, start=1)])

        # 4) update DELIVERED (chỉ update rownum)
        await gs_call(
            update_order_cells,
            rownum,
            {"status": "DELIVERED", "delivered_at": delivered_at, "deliver_text": deliver_text_plain},
        )

        try:
            from bot_shop import notify_admins_order_event

            delivered_row = dict(order)
            delivered_row["order_id"] = canonical_oid
            delivered_row["status"] = "DELIVERED"
            delivered_row["delivered_at"] = delivered_at
            delivered_row["deliver_text"] = deliver_text_plain
            await notify_admins_order_event(None, "delivered", delivered_row, bot=tg_bot)
        except Exception as e:
            logger.warning("notify_admins_order_event delivered failed: %s", e)

        # 5) write fulfillments
        try:
            await gs_call(append_fulfillment_rows, canonical_oid, items, delivered_at)
        except Exception:
            pass

        # 6) send delivery message
        sent_ok = False
        try:
            sent_ok = await send_delivery_message(user_id, canonical_oid, stock_code, qty, secrets)
        except Exception as e:
            logger.exception("send_delivery_message crashed: %s", e)
            sent_ok = False

        # Xoá các message "Chưa tìm thấy giao dịch" mà user đã thấy trong lúc chờ
        try:
            from bot_shop import cleanup_check_miss_messages
            if tg_bot:
                await cleanup_check_miss_messages(tg_bot, canonical_oid)
        except Exception as e:
            logger.warning("cleanup_check_miss_messages failed: %s", e)

        # 7) nếu gửi OK thì xoá QR; nếu không thì chỉ edit lại caption
        if qr_msg_id_s.isdigit() and tg_bot:
            if sent_ok:
                try:
                    await tg_bot.delete_message(chat_id=user_id, message_id=int(qr_msg_id_s))
                except Exception as e:
                    logger.warning(
                        "delete qr message failed (order=%s, msg_id=%s): %s",
                        canonical_oid, qr_msg_id_s, e,
                    )
                    try:
                        await edit_checkout_safe(
                            user_id,
                            int(qr_msg_id_s),
                            caption_delivered(canonical_oid, stock_code, qty),
                            kb_delivered(),
                        )
                    except Exception:
                        pass
            else:
                try:
                    await edit_checkout_safe(
                        user_id,
                        int(qr_msg_id_s),
                        caption_delivered(canonical_oid, stock_code, qty),
                        kb_delivered(),
                    )
                except Exception:
                    pass

        logger.info(
            "DELIVERED ok: %s user=%s qty=%s secrets=%s",
            canonical_oid, user_id, qty, len(secrets),
        )
        _remember_tx(txn_id)
    finally:
        if tx_lock:
            tx_lock.release()
        if txn_id:
            async with _PROCESSING_TX_GLOBAL_LOCK:
                lock = _PROCESSING_TX_IDS.get(txn_id)
                if lock is not None and not lock.locked():
                    _PROCESSING_TX_IDS.pop(txn_id, None)
def get_all_pending_orders() -> List[Tuple[int, Dict[str, Any]]]:
    """
    Return list of (rownum, order_dict) for PENDING orders.
    rownum is 1-based row number in sheet.
    """
    init_gsheet()
    values = ws_orders.get_all_values()
    if len(values) < 2:
        return []

    headers = normalize_headers(values[0])

    def get_cell(row: List[str], key: str) -> str:
        c = headers.get(key.lower())
        if c is None or c >= len(row):
            return ""
        return (row[c] or "").strip()

    res: List[Tuple[int, Dict[str, Any]]] = []
    for i in range(1, len(values)):
        rownum = i + 1
        row = values[i]
        status = get_cell(row, "status").upper()
        if status != "PENDING":
            continue

        oid = get_cell(row, "order_id")
        if not oid:
            continue

        res.append((rownum, {
            "order_id": oid,
            "status": status,
            "created_at": get_cell(row, "created_at"),
            "user_id": get_cell(row, "user_id"),
            "qr_msg_id": get_cell(row, "qr_msg_id"),
        }))
    return res


async def expire_scan_once() -> Dict[str, Any]:
    expired = 0
    released_total = 0

    pendings = await gs_call(get_all_pending_orders)
    for rownum, order in pendings:
        oid = (order.get("order_id") or "").strip()
        created_at = (order.get("created_at") or "").strip()
        if not oid or not created_at:
            continue

        if not is_expired(created_at):
            continue

        # 1) trả kho (POOL HELD -> READY)
        rel = await gs_call(release_hold_by_order, oid, "EXPIRED")
        released_total += int(rel or 0)

        # 2) set order EXPIRED
        await gs_call(update_order_cells, rownum, {
            "status": "EXPIRED",
            "deliver_text": f"(AUTO_EXPIRED_{ORDER_TTL_SECONDS}s)",
            "delivered_at": "",
        })

        # 3) best-effort xoá QR
        user_id_s = (order.get("user_id") or "").strip()
        qr_msg_id_s = (order.get("qr_msg_id") or "").strip()
        if tg_bot and user_id_s.isdigit() and qr_msg_id_s.isdigit():
            try:
                await tg_bot.delete_message(chat_id=int(user_id_s), message_id=int(qr_msg_id_s))
            except Exception:
                pass

        expired += 1

    return {"ok": True, "expired": expired, "released_items": released_total, "ttl_seconds": ORDER_TTL_SECONDS}


@app.post("/jobs/expire")
async def jobs_expire(request: Request):
    # (tuỳ chọn) bảo vệ endpoint bằng API key dùng chung SEPAY_API_KEY
    # nếu bạn muốn tắt bảo vệ thì comment 5 dòng dưới
    if SEPAY_API_KEY:
        key = (request.headers.get("x-api-key") or "").strip()
        if key != SEPAY_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    return await expire_scan_once()



@app.post("/webhook/sepay")
async def sepay_webhook(request: Request):
    if not verify_sepay_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized (bad API key)")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    asyncio.create_task(process_payment(payload))  # ✅ chạy thật sự
    return {"ok": True, "queued": True}


@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "SePay Webhook AutoDeliver",
        "has_bot_token": bool(BOT_TOKEN),
        "has_gsheet": bool(GSHEET_ID),
        "check_amount": CHECK_AMOUNT,
        "orders_tab": ORDERS_TAB,
        "pool_tab": POOL_TAB,
        "res_tab": RES_TAB,
        "ful_tab": FUL_TAB,
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SEPAY_PORT", "8001"))
    logger.info("Starting SePay webhook on port %s ...", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
