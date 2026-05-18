import os
import re
import io
import logging
import random
import string
import asyncio
import time
import base64
import hmac
import hashlib
import struct
import urllib.request
import json
from telegram.constants import ChatAction, ParseMode
from gspread.cell import Cell
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from mail_reader import MailReaderError, read_inbox_messages

import httpx

SHEETS_LOCK = asyncio.Lock()
_CATALOG_LOCK = asyncio.Lock()
_DEFAULT_PORT = os.getenv("PORT", "10000").strip() or "10000"
API_BASE_URL = os.environ.get("API_BASE_URL", f"http://127.0.0.1:{_DEFAULT_PORT}/api").rstrip("/")
# Tắt mặc định: bot gọi Sheets trực tiếp (nhanh hơn HTTP qua FastAPI)
USE_BOT_API = os.getenv("USE_BOT_API", "0").strip().lower() in ("1", "true", "yes")
CATALOG_CACHE_TTL = int(os.getenv("CATALOG_CACHE_TTL", "45"))
_KNOWN_USERS: set[int] = set()
_http_client: Optional[httpx.AsyncClient] = None
# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("khoivan_store_bot")

# ================== CONFIG ==================
SHOP_NAME = os.getenv("SHOP_NAME", "Văn Minh Store").strip()
BOT_TOKEN = (os.getenv("BOT_TOKEN", "").strip() or "PUT_YOUR_BOT_TOKEN_HERE")

GSHEET_ID = os.getenv("GSHEET_ID", "").strip()  # khuyên để ENV
GSVC_JSON = os.getenv("GSVC_JSON", "").strip()
if GSVC_JSON and not os.path.isabs(GSVC_JSON):
    GSVC_JSON = os.path.join(BASE_DIR, GSVC_JSON)

TAB_ORDERS = os.getenv("ORDERS_TAB", "ORDERS").strip()
TAB_PRODUCTS = os.getenv("PRODUCTS_TAB", "PRODUCTS").strip()
TAB_POOL = os.getenv("POOL_TAB", "POOL").strip()
TAB_RES = os.getenv("RESERVATIONS_TAB", "RESERVATIONS").strip()
TAB_USERS = os.getenv("USERS_TAB", "USERS").strip()
TAB_FUL = os.getenv("FULFILLMENTS_TAB", "FULFILLMENTS").strip()
_ws_users = None

def parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in re.split(r"[,\s]+", raw or ""):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


ADMIN_IDS = parse_admin_ids(os.getenv("ADMIN_IDS", "5322953111"))

ORDER_TTL_SECONDS = int(os.getenv("ORDER_TTL_SECONDS", "300"))  # 5 phút
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Ho_Chi_Minh").strip() or "Asia/Ho_Chi_Minh"
LOCAL_TZ = ZoneInfo(APP_TIMEZONE)

# Thanh toán (có thể ghi đè bằng BANK_* trong .env)
PAYMENT_INFO = {
    "bank_code": os.getenv("BANK_CODE", "BIDV").strip(),
    "bank_name": os.getenv("BANK_NAME", "BIDV").strip(),
    "bank_owner": os.getenv("BANK_OWNER", "NGUYEN VAN MINH").strip(),
    "bank_number": os.getenv("BANK_NUMBER", "96247W4CBY").strip(),
    "note_template": os.getenv("NOTE_TEMPLATE", "{order_id}").strip(),
}
# Support
SUPPORT_ADMIN_NAME = os.getenv("SUPPORT_ADMIN_NAME", "Nguyễn Văn Minh").strip()
SUPPORT_ZALO = os.getenv("SUPPORT_ZALO", "0342324611").strip()
SUPPORT_ZALO_LINK = os.getenv("SUPPORT_ZALO_LINK", "https://zalo.me/0342324611").strip()
SUPPORT_TELE = os.getenv("SUPPORT_TELE", "@minhgear5").strip()
SUPPORT_TELE_LINK = os.getenv("SUPPORT_TELE_LINK", "https://t.me/minhgear5").strip()

# ================== GLOBAL STATE ==================
_gs_client = None
_gs_sheet = None
_ws_orders = None
_ws_products = None
_ws_pool = None
_ws_res = None
_ws_ful = None


PENDING_QTY: Dict[int, Dict[str, Any]] = {}  # user_id -> {"product_id": ...}

# ================== HELPERS ==================
_CACHE = {
    "products": {"ts": 0.0, "data": []},
    "stock": {"ts": 0.0, "data": {}},
}

LAST_MAIL_INPUT: Dict[int, str] = {}
def _ts() -> float:
    return time.time()

def invalidate_stock_cache():
    _CACHE["stock"]["ts"] = 0.0
    _CACHE["products"]["ts"] = 0.0

def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    return _http_client


async def _fetch_api_data() -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    resp = await _get_http_client().get(f"{API_BASE_URL}/products")
    if resp.status_code == 200:
        data = resp.json()
        return data.get("products", []), data.get("stock", {})
    return [], {}


def _load_catalog_sync() -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    init_sheets()
    return load_products(), stock_count_ready_by_code()


async def refresh_catalog_cache(force: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    if (
        not force
        and _ts() - _CACHE["products"]["ts"] < CATALOG_CACHE_TTL
        and _CACHE["products"]["data"]
    ):
        return _CACHE["products"]["data"], _CACHE["stock"]["data"]

    async with _CATALOG_LOCK:
        if (
            not force
            and _ts() - _CACHE["products"]["ts"] < CATALOG_CACHE_TTL
            and _CACHE["products"]["data"]
        ):
            return _CACHE["products"]["data"], _CACHE["stock"]["data"]

        if USE_BOT_API:
            try:
                prods, stock = await _fetch_api_data()
                if prods:
                    _CACHE["products"] = {"ts": _ts(), "data": prods}
                    _CACHE["stock"] = {"ts": _ts(), "data": stock}
                    return prods, stock
            except Exception as e:
                logger.warning("API catalog failed: %s", e)

        async with SHEETS_LOCK:
            prods, stock = await asyncio.to_thread(_load_catalog_sync)
        _CACHE["products"] = {"ts": _ts(), "data": prods}
        _CACHE["stock"] = {"ts": _ts(), "data": stock}
        return prods, stock


async def load_products_cached(ttl: int = 30) -> List[Dict[str, Any]]:
    prods, _ = await refresh_catalog_cache()
    return prods

def normalize_order_ref(s: str) -> str:
    # giữ chữ/số, bỏ hết ký tự lạ như '-', ' ', '.', ...
    return re.sub(r"[^A-Za-z0-9]", "", (s or "")).upper()

async def stock_count_ready_by_code_cached(ttl: int = 5) -> Dict[str, int]:
    _, stock = await refresh_catalog_cache()
    return stock


def schedule_upsert_user(chat_id: int, username: str = "", full_name: str = "") -> None:
    if chat_id in _KNOWN_USERS:
        return
    asyncio.create_task(upsert_user(chat_id, username, full_name))


def money_vnd(value: Any) -> str:
    return f"{normalize_int(value, 0):,}".replace(",", ".") + "đ"


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None) -> None:
    if not ADMIN_IDS:
        return
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning("notify admin failed admin_id=%s: %s", admin_id, e)


def _esc_md2(value: Any) -> str:
    return escape_markdown(str(value or ""), version=2)


async def notify_admins_order_event(
    context: ContextTypes.DEFAULT_TYPE,
    event: str,
    order: Dict[str, Any],
    *,
    released: int = 0,
    actor_id: Optional[int] = None,
) -> None:
    """Gửi Telegram cho admin: đơn mới / huỷ / hết hạn / đã giao."""
    if not ADMIN_IDS or not context:
        return

    oid = _esc_md2(order.get("order_id"))
    uid = _esc_md2(order.get("user_id"))
    stock = _esc_md2(order.get("stock_code"))
    qty = _esc_md2(order.get("qty"))
    total = _esc_md2(money_vnd(order.get("total")))
    created = _esc_md2(order.get("created_at"))
    status = _esc_md2((order.get("status") or "").upper())

    titles = {
        "new": "🛒 *Đơn mới chờ thanh toán*",
        "cancelled": "❌ *Đơn đã huỷ*",
        "expired": "⌛ *Đơn hết hạn*",
        "delivered": "✅ *Đơn đã giao*",
        "paid": "💰 *Đơn đã thanh toán*",
    }
    title = titles.get(event, "📦 *Cập nhật đơn hàng*")

    lines = [
        title,
        f"Order: `{oid}`",
        f"Khách: `{uid}`",
        f"Stock: `{stock}`",
        f"SL: `{qty}`",
        f"Tổng: *{total}*",
        f"Trạng thái: `{status}`",
        f"Tạo lúc: `{created}`",
    ]
    if released:
        lines.append(f"Trả kho: `{released}` item")
    if actor_id is not None:
        lines.append(f"Thao tác bởi: `{actor_id}`")

    await notify_admins(context, "\n".join(lines))

async def gs_call(fn, *args, **kwargs):
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    async with SHEETS_LOCK:
        return await asyncio.to_thread(fn, *args, **kwargs)

def now_dt() -> datetime:
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)

def now_str() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")

def fmt_price(vnd: int) -> str:
    return f"{vnd:,} đ".replace(",", ".")

def normalize_int(v: Any, default: int = 0) -> int:
    try:
        s = str(v).strip().replace(".", "").replace(",", "")
        return int(float(s))
    except Exception:
        return default

def generate_order_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    # KHÔNG có dấu '-'
    return f"ORD{now_dt().strftime('%Y%m%d%H%M%S')}{suffix}"

def build_vietqr_image_url(order_id: str, amount: int) -> str:
    """QR động theo order_id (addInfo) bằng img.vietqr.io"""
    from urllib.parse import quote

    # note_template có thể là "{order_id}" hoặc "VM{order_id}"...
    raw_note = PAYMENT_INFO["note_template"].format(order_id=order_id)

    # ✅ ép nội dung CK về dạng sạch: bỏ '-' và mọi ký tự lạ
    add_info = normalize_order_ref(raw_note)

    bank = PAYMENT_INFO["bank_code"].strip()
    acc  = PAYMENT_INFO["bank_number"].strip()
    name = PAYMENT_INFO["bank_owner"].strip()

    return (
        f"https://img.vietqr.io/image/{bank}-{acc}-compact2.png"
        f"?amount={int(amount)}"
        f"&addInfo={quote(add_info)}"
        f"&accountName={quote(name)}"
    )


async def fetch_qr_bytes(url: str, timeout: int = 12) -> Optional[bytes]:
    """Tải ảnh QR về bytes để tránh Telegram tự fetch URL (hay lỗi không hiện QR)."""
    def _dl() -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    try:
        data = await asyncio.to_thread(_dl)
        return data if data and len(data) > 100 else None
    except Exception as e:
        logger.warning("fetch_qr_bytes failed: %s", e)
        return None

def remaining_seconds(created_at: str, ttl_seconds: int) -> int:
    try:
        created = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        expire_at = created + timedelta(seconds=ttl_seconds)
        return int((expire_at - now_dt()).total_seconds())
    except Exception:
        return 0

def format_order_ttl() -> str:
    minutes = max(1, ORDER_TTL_SECONDS // 60)
    return f"{minutes} phút"

def build_checkout_caption_with_countdown(
    order_id: str,
    product_name: str,
    unit_price: int,
    qty: int,
    total: int,
    remain_seconds: int = 0,
    status_line: str = "⏳ *ĐANG CHỜ THANH TOÁN*",
) -> str:
    _ = remain_seconds
    ttl_text = format_order_ttl()
    bank_acc = PAYMENT_INFO["bank_number"]
    bank_code = PAYMENT_INFO["bank_code"].upper()

    pay_note = normalize_order_ref(order_id) # hàm của bạn đã bỏ ký tự lạ

    return (
        f"{status_line}\n\n"
        f"🧾 Mã đơn: `{order_id}`\n"
        f"📦 SP: *{product_name}* — {fmt_price(unit_price)}\n"
        f"🔢 SL: *{qty}*\n"
        f"💰 Tổng: *{fmt_price(total)}*\n\n"
        f"⏳ *Hết hạn sau:* {ttl_text}\n\n"
        f"📌 *Thanh toán:*\n"
        f"• STK: `{bank_acc}`\n"
        f"• Bank: `{bank_code}`\n"
        f"• Nội dung CK: `{pay_note}`"
    )

async def edit_checkout_message(
    bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: str = "Markdown",
) -> None:
    """Edit caption nếu là photo; nếu không phải photo thì edit text."""
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return
    except Exception:
        pass
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

def _safe_secret(s: str) -> str:
    # tránh vỡ Markdown nếu secret có dấu `
    return (s or "").replace("`", "'").strip()

# ================== GOOGLE SHEETS ==================

async def upsert_user(chat_id: int, username: str = "", full_name: str = "") -> None:
    if chat_id in _KNOWN_USERS:
        return
    if USE_BOT_API:
        try:
            await _get_http_client().post(
                f"{API_BASE_URL}/users",
                json={"chat_id": chat_id, "username": username, "full_name": full_name},
            )
            _KNOWN_USERS.add(chat_id)
            return
        except Exception as e:
            logger.warning("upsert_user API failed: %s", e)
    await gs_call(upsert_user_sheet, chat_id, username, full_name)
    _KNOWN_USERS.add(chat_id)


def upsert_user_sheet(chat_id: int, username: str = "", full_name: str = "") -> None:
    """Lưu chat_id user vào tab USERS (nếu có rồi thì update updated_at)."""
    init_sheets()
    if not _ws_users:
        return

    vals = _ws_users.get_all_values()
    if not vals:
        raise RuntimeError("USERS thiếu header row")

    h = {str(x).strip().lower(): i for i, x in enumerate(vals[0], start=1)}
    c_chat = h.get("chat_id")
    if not c_chat:
        raise RuntimeError("USERS cần cột chat_id")

    # tìm row theo chat_id
    rownum = None
    for idx in range(2, len(vals) + 1):
        r = vals[idx - 1]
        cid = r[c_chat - 1].strip() if c_chat - 1 < len(r) else ""
        if cid == str(chat_id):
            rownum = idx
            break

    now = now_str()

    # helper update cell theo key
    def set_cell(rn: int, key: str, value: str):
        col = h.get(key.lower())
        if col:
            _ws_users.update_cell(rn, col, value)

    if rownum:
        # update
        set_cell(rownum, "username", username or "")
        set_cell(rownum, "full_name", full_name or "")
        set_cell(rownum, "updated_at", now)
    else:
        # append new row
        row_values = [""] * len(h)
        def put(key: str, value: str):
            col = h.get(key.lower())
            if col:
                row_values[col - 1] = value
        put("chat_id", str(chat_id))
        put("username", username or "")
        put("full_name", full_name or "")
        put("updated_at", now)
        _ws_users.append_row(row_values, value_input_option="USER_ENTERED")


def get_all_user_chat_ids() -> List[int]:
    init_sheets()
    if not _ws_users:
        return []
    vals = _ws_users.get_all_values()
    if not vals or len(vals) < 2:
        return []
    h = {str(x).strip().lower(): i for i, x in enumerate(vals[0], start=1)}
    c_chat = h.get("chat_id")
    if not c_chat:
        return []
    out = []
    for r in vals[1:]:
        cid = r[c_chat - 1].strip() if c_chat - 1 < len(r) else ""
        if cid.isdigit():
            out.append(int(cid))
    return out

# def init_sheets():
#     global _gs_client, _gs_sheet, _ws_orders, _ws_products, _ws_pool, _ws_res, _ws_users

#     # giữ nguyên phần check return
#     if _ws_orders and _ws_products and _ws_pool and _ws_res and _ws_users:
#         return

#     if not GSHEET_ID:
#         raise RuntimeError("GSHEET_ID empty (hãy set ENV GSHEET_ID)")
#     if not os.path.exists(GSVC_JSON):
#         raise RuntimeError(f"GSVC_JSON not found: {GSVC_JSON}")

#     scopes = [
#         "https://www.googleapis.com/auth/spreadsheets",
#         "https://www.googleapis.com/auth/drive",
#     ]
#     creds = Credentials.from_service_account_file(GSVC_JSON, scopes=scopes)
#     _gs_client = gspread.authorize(creds)
#     _gs_sheet = _gs_client.open_by_key(GSHEET_ID)

#     _ws_orders = _gs_sheet.worksheet(TAB_ORDERS)
#     _ws_products = _gs_sheet.worksheet(TAB_PRODUCTS)
#     _ws_pool = _gs_sheet.worksheet(TAB_POOL)
#     _ws_res = _gs_sheet.worksheet(TAB_RES)
#     _ws_users = _gs_sheet.worksheet(TAB_USERS)



def init_sheets():
    global _gs_client, _gs_sheet, _ws_orders, _ws_products, _ws_pool, _ws_res, _ws_users, _ws_ful

    if _ws_orders and _ws_products and _ws_pool and _ws_res and _ws_users:
        return

    if not GSHEET_ID:
        raise RuntimeError("GSHEET_ID empty (hãy set ENV GSHEET_ID)")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # --- SỬA LẠI ĐOẠN NÀY ĐỂ BỎ QUA CHECK FILE VẬT LÝ ---
    json_content = os.getenv("GOOGLE_JSON_CONTENT")

    if json_content:
        # Nếu có biến môi trường (Ưu tiên số 1 trên Render)
        try:
            json_info = json.loads(json_content)
            creds = Credentials.from_service_account_info(json_info, scopes=scopes)
            logger.info("✅ Nạp GSheet Creds từ Environment Variable")
        except Exception as e:
            logger.error(f"❌ Lỗi đọc GOOGLE_JSON_CONTENT: {e}")
            raise
    else:
        # Nếu không có (Chạy ở máy nhà), lúc này mới tìm file
        if os.path.exists(GSVC_JSON):
            creds = Credentials.from_service_account_file(GSVC_JSON, scopes=scopes)
            logger.info("🏠 Nạp GSheet Creds từ file JSON cục bộ")
        else:
            # Nếu cả 2 đều không có thì mới báo lỗi
            raise RuntimeError("❌ Không tìm thấy thông tin xác thực Google (cả Env và File)")

    # ------------------------------

    _gs_client = gspread.authorize(creds)
    _gs_sheet = _gs_client.open_by_key(GSHEET_ID)

    _ws_orders = _gs_sheet.worksheet(TAB_ORDERS)
    _ws_products = _gs_sheet.worksheet(TAB_PRODUCTS)
    _ws_pool = _gs_sheet.worksheet(TAB_POOL)
    _ws_res = _gs_sheet.worksheet(TAB_RES)
    _ws_users = _gs_sheet.worksheet(TAB_USERS)
    try:
        _ws_ful = _gs_sheet.worksheet(TAB_FUL)
    except Exception:
        _ws_ful = None
def headers_map(ws) -> Dict[str, int]:
    headers = ws.row_values(1)
    return {str(h).strip().lower(): i for i, h in enumerate(headers, start=1)}

def get_all_records(ws) -> List[Dict[str, str]]:
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return []
    headers = [str(h).strip() for h in values[0]]
    rows = []
    for r in values[1:]:
        d = {}
        for i, h in enumerate(headers):
            d[h] = r[i].strip() if i < len(r) else ""
        rows.append(d)
    return rows

# ================== PRODUCTS + STOCK ==================
def load_products() -> List[Dict[str, Any]]:
    init_sheets()
    rows = get_all_records(_ws_products)
    out: List[Dict[str, Any]] = []
    for r in rows:
        product_id = (r.get("product_id") or "").strip()
        name = (r.get("name") or "").strip()
        stock_code = (r.get("stock_code") or "").strip()
        price = normalize_int(r.get("price"), 0)

        # ✅ lấy mô tả riêng từng sản phẩm (từ cột description)
        desc = (r.get("description") or "").strip()

        if product_id and stock_code and name:
            out.append({
                "product_id": product_id,
                "name": name,
                "price": price,
                "stock_code": stock_code,
                "description": desc,   # ✅ thêm field
            })
    return out


def stock_count_ready_by_code() -> Dict[str, int]:
    init_sheets()
    rows = get_all_records(_ws_pool)
    cnt: Dict[str, int] = {}
    for r in rows:
        sc = (r.get("stock_code") or "").strip()
        st = (r.get("status") or "").strip().upper()
        if sc and st == "READY":
            cnt[sc] = cnt.get(sc, 0) + 1
    return cnt

async def find_product_by_id(pid: str) -> Optional[Dict[str, Any]]:
    for p in await load_products_cached():
        if p["product_id"] == pid:
            return p
    return None

async def find_product_by_stock_code(stock_code: str) -> Optional[Dict[str, Any]]:
    for p in await load_products_cached():
        if p["stock_code"] == stock_code:
            return p
    return None

# ================== POOL + RESERVATIONS ==================
def reserve_items_from_pool(stock_code: str, qty: int, order_id: str, hold_seconds: int) -> List[Dict[str, str]]:
    """
    Lấy qty item READY từ POOL theo stock_code -> set HELD + hold_order_id/hold_at/hold_expires_at
    + append RESERVATIONS
    """
    init_sheets()
    rows = _ws_pool.get_all_values()
    if not rows or len(rows) < 2:
        return []

    hmap = {str(h).strip().lower(): i for i, h in enumerate(rows[0], start=1)}
    col_item_id = hmap.get("item_id")
    col_stock = hmap.get("stock_code")
    col_secret = hmap.get("secret")
    col_status = hmap.get("status")
    col_hold_oid = hmap.get("hold_order_id")
    col_hold_at = hmap.get("hold_at")
    col_hold_exp = hmap.get("hold_expires_at")

    if not (col_item_id and col_stock and col_secret and col_status):
        raise RuntimeError("POOL thiếu cột bắt buộc (item_id, stock_code, secret, status)")

    now = now_str()
    exp = (now_dt() + timedelta(seconds=hold_seconds)).strftime("%Y-%m-%d %H:%M:%S")

    selected: List[Tuple[int, Dict[str, str]]] = []
    for idx in range(2, len(rows) + 1):
        r = rows[idx - 1]
        sc = r[col_stock - 1].strip() if col_stock - 1 < len(r) else ""
        st = r[col_status - 1].strip().upper() if col_status - 1 < len(r) else ""
        if sc == stock_code and st == "READY":
            item_id = r[col_item_id - 1].strip() if col_item_id - 1 < len(r) else ""
            secret = r[col_secret - 1].strip() if col_secret - 1 < len(r) else ""
            selected.append((idx, {"item_id": item_id, "stock_code": sc, "secret": secret}))
            if len(selected) >= qty:
                break

    if len(selected) < qty:
        return []

    # ✅ mark HELD in POOL (BATCH UPDATE - nhanh hơn nhiều)
    cells: List[Cell] = []
    for rownum, _item in selected:
        cells.append(Cell(rownum, col_status, "HELD"))
        if col_hold_oid:
            cells.append(Cell(rownum, col_hold_oid, order_id))
        if col_hold_at:
            cells.append(Cell(rownum, col_hold_at, now))
        if col_hold_exp:
            cells.append(Cell(rownum, col_hold_exp, exp))

    _ws_pool.update_cells(cells, value_input_option="USER_ENTERED")

    # append RESERVATIONS rows
    res_hmap = headers_map(_ws_res)
    rows_to_append = []
    for _, item in selected:
        row_values = [""] * len(res_hmap)
        def put(key: str, val: str):
            c = res_hmap.get(key.lower())
            if c:
                row_values[c - 1] = val

        put("order_id", order_id)
        put("item_id", item["item_id"])
        put("stock_code", stock_code)
        put("reserved_at", now)
        put("expires_at", exp)
        put("released_at", "")
        put("sold_at", "")

        rows_to_append.append(row_values)

    _ws_res.append_rows(rows_to_append, value_input_option="USER_ENTERED")

    invalidate_stock_cache()
    return [item for _, item in selected]

def release_hold_by_order_sheet(
    order_id: str,
    mark_status: str,
    order_rownum: Optional[int] = None,
) -> int:
    """
    Trả kho: POOL HELD -> READY nếu hold_order_id=order_id
    + RESERVATIONS.released_at
    + ORDERS.status = mark_status
    """
    init_sheets()

    pool_vals = _ws_pool.get_all_values()
    if not pool_vals or len(pool_vals) < 2:
        set_order_fields_sheet(order_id, {"status": mark_status}, order_rownum=order_rownum)
        invalidate_stock_cache()
        return 0
    ph = {str(h).strip().lower(): i for i, h in enumerate(pool_vals[0], start=1)}
    c_status = ph.get("status")
    c_hold_oid = ph.get("hold_order_id")
    c_hold_at = ph.get("hold_at")
    c_hold_exp = ph.get("hold_expires_at")
    if not (c_status and c_hold_oid):
        set_order_fields_sheet(order_id, {"status": mark_status}, order_rownum=order_rownum)
        invalidate_stock_cache()
        return 0

    pool_cells: List[Cell] = []
    released = 0
    for idx in range(2, len(pool_vals) + 1):
        r = pool_vals[idx - 1]
        hold_oid = r[c_hold_oid - 1].strip() if c_hold_oid - 1 < len(r) else ""
        st = r[c_status - 1].strip().upper() if c_status - 1 < len(r) else ""
        if hold_oid == order_id and st == "HELD":
            pool_cells.append(Cell(idx, c_status, "READY"))
            pool_cells.append(Cell(idx, c_hold_oid, ""))
            if c_hold_at:
                pool_cells.append(Cell(idx, c_hold_at, ""))
            if c_hold_exp:
                pool_cells.append(Cell(idx, c_hold_exp, ""))
            released += 1

    if pool_cells:
        _ws_pool.update_cells(pool_cells, value_input_option="USER_ENTERED")

    res_vals = _ws_res.get_all_values()
    if res_vals and len(res_vals) >= 2:
        rh = {str(h).strip().lower(): i for i, h in enumerate(res_vals[0], start=1)}
        c_oid = rh.get("order_id")
        c_rel = rh.get("released_at")
        if c_oid and c_rel:
            rel_now = now_str()
            res_cells = [
                Cell(idx, c_rel, rel_now)
                for idx in range(2, len(res_vals) + 1)
                if (
                    (r := res_vals[idx - 1])
                    and c_oid - 1 < len(r)
                    and r[c_oid - 1].strip() == order_id
                )
            ]
            if res_cells:
                _ws_res.update_cells(res_cells, value_input_option="USER_ENTERED")

    set_order_fields_sheet(order_id, {"status": mark_status}, order_rownum=order_rownum)
    invalidate_stock_cache()
    return released


async def release_hold_by_order(
    order_id: str,
    mark_status: str,
    order_rownum: Optional[int] = None,
) -> int:
    if USE_BOT_API:
        try:
            resp = await _get_http_client().post(f"{API_BASE_URL}/orders/{order_id}/cancel")
            if resp.status_code == 200:
                return int(resp.json().get("released", 0))
        except Exception as e:
            logger.warning("release_hold_by_order API failed %s: %s", order_id, e)
    released = await gs_call(release_hold_by_order_sheet, order_id, mark_status, order_rownum)
    invalidate_stock_cache()
    return released


def mark_sold_and_get_secrets(order_id: str) -> List[Dict[str, str]]:
    """
    Khi giao: POOL HELD (hold_order_id=order_id) -> SOLD + sold_at/sold_order_id
    Update RESERVATIONS.sold_at
    Return list items with secret
    """
    init_sheets()
    pool_vals = _ws_pool.get_all_values()
    if not pool_vals or len(pool_vals) < 2:
        return []

    ph = {str(h).strip().lower(): i for i, h in enumerate(pool_vals[0], start=1)}
    c_item_id = ph.get("item_id")
    c_stock = ph.get("stock_code")
    c_secret = ph.get("secret")
    c_status = ph.get("status")
    c_hold_oid = ph.get("hold_order_id")
    c_sold_oid = ph.get("sold_order_id")
    c_sold_at = ph.get("sold_at")

    if not (c_hold_oid and c_status and c_secret):
        return []

    items: List[Dict[str, str]] = []
    for idx in range(2, len(pool_vals) + 1):
        r = pool_vals[idx - 1]
        hold_oid = r[c_hold_oid - 1].strip() if c_hold_oid - 1 < len(r) else ""
        st = r[c_status - 1].strip().upper() if c_status - 1 < len(r) else ""
        if hold_oid == order_id and st == "HELD":
            item_id = r[c_item_id - 1].strip() if c_item_id and c_item_id - 1 < len(r) else ""
            stock_code = r[c_stock - 1].strip() if c_stock and c_stock - 1 < len(r) else ""
            secret = r[c_secret - 1].strip() if c_secret - 1 < len(r) else ""

            # mark SOLD
            _ws_pool.update_cell(idx, c_status, "SOLD")
            if c_sold_oid:
                _ws_pool.update_cell(idx, c_sold_oid, order_id)
            if c_sold_at:
                _ws_pool.update_cell(idx, c_sold_at, now_str())

            items.append({"item_id": item_id, "stock_code": stock_code, "secret": secret})

    # update RESERVATIONS.sold_at
    res_vals = _ws_res.get_all_values()
    if res_vals and len(res_vals) >= 2:
        rh = {str(h).strip().lower(): i for i, h in enumerate(res_vals[0], start=1)}
        c_oid = rh.get("order_id")
        c_sold = rh.get("sold_at")
        if c_oid and c_sold:
            for idx in range(2, len(res_vals) + 1):
                r = res_vals[idx - 1]
                oid = r[c_oid - 1].strip() if c_oid - 1 < len(r) else ""
                if oid == order_id:
                    _ws_res.update_cell(idx, c_sold, now_str())

    invalidate_stock_cache()
    return items

# ================== ORDERS ==================
def append_order(order_row: Dict[str, Any]) -> None:
    init_sheets()
    h = headers_map(_ws_orders)
    if not h:
        raise RuntimeError("ORDERS thiếu header row")

    row_values = [""] * len(h)

    def put(key: str, value: Any):
        c = h.get(key.lower())
        if c:
            row_values[c - 1] = "" if value is None else str(value)

    put("order_id", order_row.get("order_id", ""))
    put("user_id", order_row.get("user_id", ""))
    put("stock_code", order_row.get("stock_code", ""))
    put("qty", order_row.get("qty", ""))
    put("total", order_row.get("total", ""))
    put("status", order_row.get("status", "PENDING"))
    put("qr_msg_id", order_row.get("qr_msg_id", ""))
    put("paid_at", order_row.get("paid_at", ""))
    put("tx_id", order_row.get("tx_id", ""))
    put("delivered_at", order_row.get("delivered_at", ""))
    put("deliver_text", order_row.get("deliver_text", ""))
    put("created_at", order_row.get("created_at", now_str()))

    _ws_orders.append_row(row_values, value_input_option="USER_ENTERED")

async def get_order(order_id: str) -> Optional[Dict[str, str]]:
    if USE_BOT_API:
        try:
            resp = await _get_http_client().get(f"{API_BASE_URL}/orders/{order_id}")
            if resp.status_code == 200:
                return resp.json().get("order")
        except Exception as e:
            logger.warning("get_order API failed %s: %s", order_id, e)
    return await gs_call(get_order_sheet, order_id)


def get_order_sheet(order_id: str) -> Optional[Dict[str, str]]:
    init_sheets()
    vals = _ws_orders.get_all_values()
    if not vals or len(vals) < 2:
        return None

    h = {str(x).strip().lower(): i for i, x in enumerate(vals[0], start=1)}
    c_oid = h.get("order_id")
    if not c_oid:
        return None

    target = normalize_order_ref(order_id)

    for idx in range(2, len(vals) + 1):
        r = vals[idx - 1]
        raw_oid = r[c_oid - 1].strip() if c_oid - 1 < len(r) else ""
        if normalize_order_ref(raw_oid) == target:
            d = {}
            for k, c in h.items():
                d[k] = r[c - 1].strip() if c - 1 < len(r) else ""
            d["_rownum"] = str(idx)
            return d
    return None


async def set_order_fields(order_id: str, updates: Dict[str, Any]) -> None:
    if USE_BOT_API:
        try:
            resp = await _get_http_client().patch(
                f"{API_BASE_URL}/orders/{order_id}",
                json=updates,
            )
            if resp.status_code == 200:
                return
        except Exception as e:
            logger.warning("set_order_fields API failed %s: %s", order_id, e)
    await gs_call(set_order_fields_sheet, order_id, updates)


def set_order_fields_sheet(
    order_id: str,
    updates: Dict[str, Any],
    *,
    order_rownum: Optional[int] = None,
) -> None:
    init_sheets()
    rownum = order_rownum
    if rownum is None:
        o = get_order_sheet(order_id)
        if not o:
            return
        rownum = int(o["_rownum"])
    h = headers_map(_ws_orders)
    cells: List[Cell] = []
    for k, v in updates.items():
        c = h.get(k.lower())
        if c:
            cells.append(Cell(rownum, c, "" if v is None else str(v)))
    if cells:
        _ws_orders.update_cells(cells, value_input_option="USER_ENTERED")

async def list_user_orders(user_id: int, limit: int = 10) -> List[Dict[str, str]]:
    if USE_BOT_API:
        try:
            resp = await _get_http_client().get(
                f"{API_BASE_URL}/users/{user_id}/orders",
                params={"limit": limit},
            )
            if resp.status_code == 200:
                return resp.json().get("orders", [])
        except Exception as e:
            logger.warning("list_user_orders API failed %s: %s", user_id, e)
    return await gs_call(list_user_orders_sheet, user_id, limit)


def list_user_orders_sheet(user_id: int, limit: int = 10) -> List[Dict[str, str]]:
    init_sheets()
    vals = _ws_orders.get_all_values()
    if not vals or len(vals) < 2:
        return []
    h = {str(x).strip().lower(): i for i, x in enumerate(vals[0], start=1)}
    c_uid = h.get("user_id")
    if not c_uid:
        return []
    rows: List[Dict[str, str]] = []
    for idx in range(2, len(vals) + 1):
        r = vals[idx - 1]
        uid = r[c_uid - 1].strip() if c_uid - 1 < len(r) else ""
        if uid == str(user_id):
            d = {}
            for k, c in h.items():
                d[k] = r[c - 1].strip() if c - 1 < len(r) else ""
            rows.append(d)

    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows[:limit]


# ================== FULFILLMENTS (optional) ==================
def append_fulfillment(order_id: str, item_id: str, stock_code: str, secret: str, delivered_at: str) -> None:
    init_sheets()
    if not _ws_ful:
        return
    h = headers_map(_ws_ful)
    if not h:
        return
    row_values = [""] * len(h)

    def put(key: str, value: Any):
        c = h.get(key.lower())
        if c:
            row_values[c - 1] = "" if value is None else str(value)

    put("order_id", order_id)
    put("item_id", item_id)
    put("stock_code", stock_code)
    put("secret", secret)
    put("delivered_at", delivered_at)
    _ws_ful.append_row(row_values, value_input_option="USER_ENTERED")

def append_fulfillments_bulk(order_id: str, items: List[Dict[str, str]], delivered_at: str) -> None:
    """
    Append nhiều dòng vào sheet FULFILLMENTS chỉ 1 lần (nhanh hơn nhiều).
    items: list dict có keys: item_id, stock_code, secret
    """
    init_sheets()
    if not _ws_ful:
        return

    h = headers_map(_ws_ful)
    if not h:
        return

    rows_to_append: List[List[str]] = []

    for it in items:
        row_values = [""] * len(h)

        def put(key: str, value: Any):
            c = h.get(key.lower())
            if c:
                row_values[c - 1] = "" if value is None else str(value)

        put("order_id", order_id)
        put("item_id", it.get("item_id", ""))
        put("stock_code", it.get("stock_code", ""))
        put("secret", it.get("secret", ""))
        put("delivered_at", delivered_at)

        rows_to_append.append(row_values)

    # ✅ append 1 lần
    _ws_ful.append_rows(rows_to_append, value_input_option="USER_ENTERED")


def get_fulfillment_secrets(order_id: str) -> List[str]:
    """Lấy secret đã giao từ sheet FULFILLMENTS (dùng để resend khi đơn DELIVERED)."""
    init_sheets()
    if not _ws_ful:
        return []
    try:
        vals = _ws_ful.get_all_values()
        if not vals or len(vals) < 2:
            return []
        h = {str(x).strip().lower(): i for i, x in enumerate(vals[0])}
        c_oid = h.get("order_id")
        c_secret = h.get("secret")
        if c_oid is None or c_secret is None:
            return []
        out = []
        for r in vals[1:]:
            oid = r[c_oid].strip() if c_oid < len(r) else ""
            if oid == order_id:
                sec = r[c_secret].strip() if c_secret < len(r) else ""
                if sec:
                    out.append(sec)
        return out
    except Exception:
        return []

# ================== UI: MAIN MENU ==================
BTN_PRODUCTS = "🛍 Sản phẩm".replace("\ufe0f","")
BTN_SUPPORT  = "💬 Hỗ trợ".replace("\ufe0f","")
BTN_ORDERS   = "📦 Đơn hàng".replace("\ufe0f","")
BTN_2FA      = "🔐 2FA".replace("\ufe0f","")
BTN_MAIL     = "📬 Đọc mail".replace("\ufe0f","")


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(BTN_PRODUCTS), KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_ORDERS)],
        [KeyboardButton(BTN_2FA), KeyboardButton(BTN_MAIL)],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)



def welcome_text(user_fullname: str) -> str:
    return (
        f"👋 *Xin chào {user_fullname}!* \n\n"
        f"*{SHOP_NAME}* rất vui được phục vụ bạn.\n\n\n"
        "✅ Hàng số chuẩn • giao tự động 24/7\n\n"
        "⚡️ Thanh toán nhanh • VietQR / chuyển khoản\n\n"
        "🛡 Bảo mật riêng tư • thông tin được bảo vệ tuyệt đối\n\n\n"
        "📌 *Lệnh nhanh:*\n\n"
        "/start - Menu chính\n\n"
        "/shop - Xem sản phẩm\n\n"
        "/orders - Đơn hàng của bạn\n\n"
        "/support - Hỗ trợ\n\n"
        "/2fa - Lấy mã 2FA từ secret\n\n"
        f"🫡 “Mỗi đơn hàng bạn đặt tại {SHOP_NAME} không chỉ là một sản phẩm — đó là sự tin tưởng bạn gửi gắm, "
        "và là cam kết chúng tôi luôn giữ trọn.”\n\n"
    )



# ================== SUPPORT ==================
def support_text() -> str:
    return (
        "💬 *HỖ TRỢ & CHĂM SÓC KHÁCH HÀNG*\n\n"
        "Nếu bạn gặp bất kỳ vấn đề nào, cứ nhắn mình nhé:\n\n\n"
        f"👤 *Phụ trách:* {SUPPORT_ADMIN_NAME}\n\n"
        f"📱 *Zalo:* `{SUPPORT_ZALO}`\n\n"
        f"✈️ *Telegram:* {SUPPORT_TELE}\n\n"
        "🤝 Mình luôn sẵn sàng hỗ trợ bạn *bất kể giờ nào* (có thể phản hồi chậm hơn vào giờ khuya).\n\n"
        "👉 Bấm nút bên dưới để liên hệ ngay."
    )



def support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Nhắn Zalo", url=SUPPORT_ZALO_LINK)],
        [InlineKeyboardButton("✈️ Nhắn Telegram", url=SUPPORT_TELE_LINK)],
        [InlineKeyboardButton("⬅️ Menu chính", callback_data="back_main")],
    ])


def quick_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛍 Sản phẩm", callback_data="go_products"),
            InlineKeyboardButton("📦 Đơn hàng", callback_data="go_orders"),
        ],
        [
            InlineKeyboardButton("🔐 2FA", callback_data="2fa_help"),
            InlineKeyboardButton("📬 Đọc mail", callback_data="mail_help"),
        ],
        [InlineKeyboardButton("🔄 Đọc lại thư", callback_data="mail_repeat")],
        [InlineKeyboardButton("⬅️ Menu chính", callback_data="back_main")],
    ])

async def send_support(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=chat_id,
        text=support_text(),
        parse_mode="Markdown",
        reply_markup=support_kb(),
    )

# ================== UI: PRODUCTS ==================
def build_products_menu_kb(
    products: List[Dict[str, Any]],
    stock_ready: Dict[str, int],
) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []

    for p in products:
        sc = p["stock_code"]
        ready = stock_ready.get(sc, 0)

        # Format theo yêu cầu: "Tên | 15.000 vnđ | Số Lượng Còn : 5"
        price_text = fmt_price(p["price"]).replace(" đ", " vnđ")
        label = f"{p['name']} | {price_text}|SL: {ready}"

        buttons.append([InlineKeyboardButton(label, callback_data=f"pdetail|{p['product_id']}")])

    # 2 nút nhanh
    buttons.append([
        InlineKeyboardButton("📦 Đơn hàng", callback_data="go_orders"),
        InlineKeyboardButton("💬 Hỗ trợ", callback_data="go_support"),
    ])

    buttons.append([
        InlineKeyboardButton("🔐 2FA", callback_data="2fa_help"),
        InlineKeyboardButton("📬 Đọc mail", callback_data="mail_help"),
    ])

    # Menu chính
    buttons.append([InlineKeyboardButton("⬅️ Menu chính", callback_data="back_main")])

    return InlineKeyboardMarkup(buttons)


def product_detail_text(p: Dict[str, Any], ready_qty: int) -> str:
    status = "✅ *Còn hàng*" if ready_qty > 0 else "⛔ *Hết hàng*"

    # ✅ mô tả lấy từ sheet
    desc = (p.get("description") or "").strip()
    if not desc:
        desc = "Chưa có mô tả."

    # tránh vỡ Markdown vì dấu `
    desc = desc.replace("`", "'")

    return (
        f"📦 *{p['name']}*\n\n"
        f"💰 Giá: *{fmt_price(p['price'])}*\n"
        f"📦 Còn lại: *{ready_qty}*\n"
        f"📝 *Mô tả:*\n{desc}\n"
        f"📌 Trạng thái: {status}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ Thanh toán xong hệ thống *giao tự động*.\n"
        "👇 Chọn chức năng bên dưới:"
    )


def product_detail_kb(pid: str, ready_qty: int) -> InlineKeyboardMarkup:
    rows = []
    if ready_qty > 0:
        rows.append([InlineKeyboardButton("🛒 Mua ngay", callback_data=f"buy|{pid}")])
    else:
        rows.append([InlineKeyboardButton("💬 Liên hệ hỗ trợ", url=SUPPORT_TELE_LINK)])

    rows.append([InlineKeyboardButton("⬅️ Quay lại menu sản phẩm", callback_data="back_products")])
    rows.append([InlineKeyboardButton("⬅️ Menu chính", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def qty_select_text(p: Dict[str, Any]) -> str:
    return (
        f"🔢 *Chọn số lượng* cho *{p['name']}*\n\n"

        "👇 Chọn nhanh bên dưới hoặc nhập tuỳ chỉnh:"
    )

def qty_select_kb(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data=f"qty|{pid}|1"),
         InlineKeyboardButton("2", callback_data=f"qty|{pid}|2")],
        [InlineKeyboardButton("5", callback_data=f"qty|{pid}|5"),
         InlineKeyboardButton("10", callback_data=f"qty|{pid}|10")],
        [InlineKeyboardButton("✏️ Tùy chỉnh", callback_data=f"qtycustom|{pid}")],
        [InlineKeyboardButton("⬅️ Quay lại", callback_data=f"pdetail_back|{pid}")],
    ])

def checkout_keyboard_pending(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Xác nhận đã thanh toán", callback_data=f"confirm|{order_id}"),
            InlineKeyboardButton("❌ Huỷ đơn", callback_data=f"cancel|{order_id}"),
        ],
        [InlineKeyboardButton("⬅️ Menu chính", callback_data="back_main")],
    ])

def checkout_keyboard_done() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu chính", callback_data="back_main")]])

# ================== COMMANDS ==================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    schedule_upsert_user(update.effective_chat.id, user.username or "", user.full_name or "")

    await update.message.reply_text(
        welcome_text(user.full_name),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

async def cmd_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_products(update.effective_user.id, context)

async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_orders(update.effective_user.id, context)

async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_support(update.effective_user.id, context)

def looks_like_mail_account(text: str) -> bool:
    text = (text or "").strip()
    return "@" in text and ("|" in text or "----" in text)


def normalize_menu_text(text: str) -> str:
    text = (text or "").replace("\ufe0f", "")
    text = re.sub(r"[^\wÀ-ỹ\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.casefold().split())


def extract_totp_secrets(raw: str) -> List[str]:
    text = (raw or "").strip()
    if not text:
        return []

    # Support otpauth://totp/...?...secret=XXXX links too.
    uri_secrets = re.findall(r"(?:^|[?&])secret=([A-Za-z2-7=\s]+)", text, flags=re.IGNORECASE)
    if uri_secrets:
        return [s.strip() for s in uri_secrets if s.strip()]

    secrets: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            line = parts[-1] if parts else line
        candidate = re.sub(r"[^A-Za-z2-7=]", "", line).upper()
        if len(candidate) >= 12 and re.fullmatch(r"[A-Z2-7=]+", candidate):
            secrets.append(candidate)
    return secrets


def looks_like_totp_secret(text: str) -> bool:
    if "@" in (text or "") or "|" in (text or ""):
        return False
    return bool(extract_totp_secrets(text))


def generate_totp(secret: str, now: Optional[int] = None, step: int = 30, digits: int = 6) -> Tuple[str, int]:
    clean = re.sub(r"[^A-Za-z2-7=]", "", secret or "").upper()
    if not clean:
        raise ValueError("Secret rỗng")
    clean += "=" * ((8 - len(clean) % 8) % 8)
    key = base64.b32decode(clean, casefold=True)
    current = int(now if now is not None else time.time())
    counter = current // step
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10 ** digits)).zfill(digits), step - (current % step)


async def send_2fa_help(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "🔐 *LẤY MÃ 2FA*\n\n"
            "Cách 1:\n"
            "`/2fa SECRET`\n\n"
            "Cách 2:\n"
            "Gửi thẳng secret 2FA vào chat.\n\n"
            "Cách 3:\n"
            "Reply tin có secret rồi gõ `/2fa`.\n\n"
            "Bot sẽ tạo mã 6 số hiện tại giống Google Authenticator."
        ),
        parse_mode="Markdown",
        reply_markup=quick_actions_kb(),
    )


async def send_2fa_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str):
    secrets = extract_totp_secrets(raw)
    if not secrets:
        await send_2fa_help(update.effective_chat.id, context)
        return

    lines = ["🔐 *Mã 2FA hiện tại*"]
    for idx, secret in enumerate(secrets[:10], start=1):
        try:
            code, remain = generate_totp(secret)
            lines.append(f"\n{idx}) `{code}` - còn *{remain}s*")
        except Exception:
            lines.append(f"\n{idx}) Secret không hợp lệ")
    if len(secrets) > 10:
        lines.append(f"\n\nChỉ xử lý 10 secret đầu tiên. Còn {len(secrets) - 10} secret chưa hiển thị.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=quick_actions_kb())


async def cmd_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args).strip()
    if not raw and update.message.reply_to_message:
        raw = (update.message.reply_to_message.text or "").strip()

    if not raw:
        return await send_2fa_help(update.effective_chat.id, context)

    return await send_2fa_from_text(update, context, raw)


async def render_mail_result(loading_msg, raw: str):
    try:
        result = await asyncio.to_thread(read_inbox_messages, raw, 1)
    except MailReaderError as e:
        await loading_msg.edit_text(f"Không đọc được mail:\n{e}", reply_markup=quick_actions_kb())
        return
    except Exception as e:
        logger.exception("cmd_mail failed")
        await loading_msg.edit_text(f"Lỗi không xác định khi đọc mail:\n{e}", reply_markup=quick_actions_kb())
        return

    email = escape_markdown(result.get("email", ""), version=2)
    messages = result.get("messages") or []
    if not messages:
        await loading_msg.edit_text(
            f"Không thấy mail nào trong inbox của `{email}`.",
            parse_mode="MarkdownV2",
            reply_markup=quick_actions_kb(),
        )
        return

    lines = [f"*Inbox:* `{email}`"]
    latest_msg = messages[0]
    latest_code = (latest_msg.get("codes") or "").split(",", 1)[0].strip()
    if latest_code:
        code_md = escape_markdown(latest_code, version=2)
        lines.extend(["", f"*Mã mới nhất:* `{code_md}`"])

    for idx, msg in enumerate(messages, start=1):
        sender = escape_markdown(msg.get("from", ""), version=2)
        time_text = escape_markdown(msg.get("time", ""), version=2)
        subject = escape_markdown(msg.get("subject", ""), version=2)
        preview = escape_markdown((msg.get("preview", "") or "")[:350], version=2)
        codes = escape_markdown(msg.get("codes", ""), version=2)

        block = [
            "",
            f"*{idx}\\. {subject}*",
            f"From: `{sender}`",
            f"Time: `{time_text}`",
        ]
        if codes:
            block.append(f"Code: `{codes}`")
        if preview:
            block.append(preview)
        lines.extend(block)

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n..."

    await loading_msg.edit_text(
        text,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
        reply_markup=quick_actions_kb(),
    )


async def read_mail_from_text(update: Update, raw: str):
    if update.effective_user:
        LAST_MAIL_INPUT[update.effective_user.id] = raw
    loading_msg = await update.message.reply_text("Đang đọc hòm thư...")
    await render_mail_result(loading_msg, raw)


async def read_mail_again(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    raw = LAST_MAIL_INPUT.get(user_id, "").strip()
    if not raw:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Chưa có hòm thư gần nhất để đọc lại. Bạn gửi chuỗi mail hoặc dùng /mail trước nhé.",
            reply_markup=quick_actions_kb(),
        )
        return
    loading_msg = await context.bot.send_message(chat_id=chat_id, text="Đang đọc lại hòm thư...")
    await render_mail_result(loading_msg, raw)


async def cmd_mail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(context.args).strip()
    if not raw and update.message.reply_to_message:
        raw = (update.message.reply_to_message.text or "").strip()

    if not raw:
        await update.message.reply_text(
            "Dùng: `/mail email|refresh_token|client_id`\n"
            "Hoặc gửi thẳng chuỗi `email|refresh_token|client_id` vào chat.",
            parse_mode="Markdown",
            reply_markup=quick_actions_kb(),
        )
        return

    await read_mail_from_text(update, raw)


async def send_mail_help(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "📬 *ĐỌC HÒM THƯ*\n\n"
            "Cách 1:\n"
            "`/mail email|refresh_token|client_id`\n\n"
            "Cách 2:\n"
            "Gửi thẳng chuỗi `email|refresh_token|client_id` vào chat.\n\n"
            "Cách 3:\n"
            "Reply tin chứa chuỗi mail rồi gõ `/mail`.\n\n"
            "Bot sẽ đọc mail mới nhất và tự bắt mã số nếu có."
        ),
        parse_mode="Markdown",
        reply_markup=quick_actions_kb(),
    )

# ================== PRODUCTS FLOW ==================
async def show_products(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
        products, stock_ready = await refresh_catalog_cache()
    except Exception as e:
        logger.exception("show_products error")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Lỗi Google Sheets:\n{e}",
            reply_markup=main_menu_keyboard(),
        )
        return

    if not products:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Chưa có sản phẩm trong tab PRODUCTS.",
            reply_markup=main_menu_keyboard(),
        )
        return

    text = (
        "🛍 *MENU SẢN PHẨM*\n\n"
        "👉 Chọn sản phẩm bên dưới:"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=build_products_menu_kb(products, stock_ready),
    )

async def show_product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: str):
    q = update.callback_query
    await q.answer()

    p = await gs_call(find_product_by_id, pid)
    if not p:
        return await q.edit_message_text("❌ Không tìm thấy sản phẩm.")

    ready_map = await gs_call(stock_count_ready_by_code_cached)
    ready = ready_map.get(p["stock_code"], 0)
    await q.edit_message_text(
        product_detail_text(p, ready),
        parse_mode="Markdown",
        reply_markup=product_detail_kb(pid, ready),
    )

async def ask_qty(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: str):
    q = update.callback_query
    await q.answer()

    p = await gs_call(find_product_by_id, pid)
    if not p:
        return await q.edit_message_text("❌ Không tìm thấy sản phẩm.")

    await q.edit_message_text(
        qty_select_text(p),
        parse_mode="Markdown",
        reply_markup=qty_select_kb(pid),
    )

async def set_custom_qty_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: str):
    q = update.callback_query
    await q.answer()

    p = await gs_call(find_product_by_id, pid)
    if not p:
        return await q.edit_message_text("❌ Không tìm thấy sản phẩm.")

    # có thể xoá/giữ tin cũ tuỳ bạn
    try:
        await q.message.delete()
    except Exception:
        pass

    await prompt_custom_qty(context, q.from_user.id, {**p, "product_id": pid})

async def prompt_custom_qty(context: ContextTypes.DEFAULT_TYPE, user_id: int, p: Dict[str, Any], note: str = ""):
    # ✅ re-arm trạng thái nhập số lượng
    PENDING_QTY[user_id] = {"product_id": p["product_id"]}

    text = (note + "\n\n" if note else "") + f"✏️ Nhập số lượng muốn mua cho *{p['name']}* (>=1):"
    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Quay lại", callback_data=f"buy|{p['product_id']}")
        ]]),
    )

async def handle_custom_qty_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id not in PENDING_QTY:
        return False

    pid = PENDING_QTY[user_id]["product_id"]
    p = await gs_call(find_product_by_id, pid)
    if not p:
        PENDING_QTY.pop(user_id, None)
        await update.message.reply_text("❌ Sản phẩm không tồn tại.", reply_markup=main_menu_keyboard())
        return True

    t = (update.message.text or "").strip()
    if not t.isdigit() or int(t) <= 0:
        await update.message.reply_text("❗ Vui lòng nhập số nguyên >= 1.")
        return True

    qty = int(t)

    ok = await checkout_flow(user_id, p, qty, context, edit_query=None, from_custom_qty=True)

    if ok:
        PENDING_QTY.pop(user_id, None)  # ✅ chỉ pop khi tạo đơn OK
    # nếu fail thì giữ PENDING_QTY để user nhập lại

    return True


async def qty_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: str, qty: int):
    q = update.callback_query
    await q.answer()
    p = await gs_call(find_product_by_id, pid)
    if not p:
        return await q.edit_message_text("❌ Không tìm thấy sản phẩm.")
    await checkout_flow(q.from_user.id, p, qty, context, edit_query=q)

# ================== JOBS ==================
def remove_jobs_by_prefix(app: Application, prefix: str):
    if not app.job_queue:
        return
    for j in app.job_queue.jobs():
        if j.name and j.name.startswith(prefix):
            try:
                j.schedule_removal()
            except Exception:
                pass

async def countdown_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    order_id = data.get("order_id", "")
    user_id = int(data.get("user_id") or 0)

    order = await gs_call(get_order, order_id)
    if not order:
        context.job.schedule_removal()
        return

    status = (order.get("status") or "").upper()
    if status != "PENDING":
        context.job.schedule_removal()
        return

    qr_msg_id = (order.get("qr_msg_id") or "").strip()
    if not qr_msg_id.isdigit():
        return

    remain = remaining_seconds(order.get("created_at", ""), ORDER_TTL_SECONDS)
    if remain <= 0:
        context.job.schedule_removal()
        return

    p = await gs_call(find_product_by_stock_code, order.get("stock_code", ""))
    if not p:
        return

    caption = build_checkout_caption_with_countdown(
        order_id=order_id,
        product_name=p["name"],
        unit_price=int(p["price"]),
        qty=normalize_int(order.get("qty"), 1),
        total=normalize_int(order.get("total"), 0),
        remain_seconds=remain,
        status_line="⏳ *ĐANG CHỜ THANH TOÁN*",
    )
    qr_url = build_vietqr_image_url(order_id, normalize_int(order.get("total"), 0))
    caption_with_link = caption

    await edit_checkout_message(
        bot=context.bot,
        chat_id=user_id,
        message_id=int(qr_msg_id),
        text=caption_with_link,
        reply_markup=checkout_keyboard_pending(order_id),
        parse_mode="Markdown",
    )

async def ttl_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data or {}
    order_id = str(data.get("order_id", "")).strip()
    user_id = int(data.get("user_id") or 0)
    if not order_id or not user_id:
        return

    order = await gs_call(get_order, order_id)
    if not order:
        return

    st = (order.get("status") or "PENDING").upper()
    if st in ("PAID", "DELIVERED", "CANCELLED", "EXPIRED"):
        return

    released = await gs_call(release_hold_by_order, order_id, "EXPIRED")

    qr_msg_id = (order.get("qr_msg_id") or "").strip()
    if qr_msg_id.isdigit():
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=int(qr_msg_id))
        except Exception:
            pass

    remove_jobs_by_prefix(context.application, f"countdown_{order_id}")

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"⌛ Đơn `{order_id}` đã *hết hạn* (quá {ORDER_TTL_SECONDS//60} phút) nên đã bị huỷ.\n"
            f"✅ Đã trả kho: *{released}* item.\n\n"
            "Bạn tạo đơn mới nếu vẫn muốn mua nhé."
        ),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

    expired_order = dict(order)
    expired_order["status"] = "EXPIRED"
    await notify_admins_order_event(context, "expired", expired_order, released=released)

async def schedule_ttl(app: Application, user_id: int, order_id: str):
    if not app.job_queue:
        return
    app.job_queue.run_once(
        ttl_job,
        when=ORDER_TTL_SECONDS,
        data={"user_id": user_id, "order_id": order_id},
        name=f"ttl_{order_id}",
    )

# ================== CHECKOUT ==================
async def checkout_flow(
    user_id: int,
    product: Dict[str, Any],
    qty: int,
    context: ContextTypes.DEFAULT_TYPE,
    edit_query=None,
    from_custom_qty: bool = False,
) -> bool:
    pid = (product.get("product_id") or "").strip()
    if not pid:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Lỗi dữ liệu sản phẩm (thiếu product_id). Vui lòng thử lại từ /shop.",
            reply_markup=main_menu_keyboard(),
        )
        return False

    async def _ask_retry(note: str) -> None:
        PENDING_QTY[user_id] = {"product_id": pid}
        await context.bot.send_message(
            chat_id=user_id,
            text=f"{note}\n\n✏️ Nhập lại số lượng cho *{product['name']}* (>=1):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Quay lại", callback_data=f"buy|{pid}")
            ]]),
        )

    _, ready_map = await refresh_catalog_cache()
    ready = ready_map.get(product["stock_code"], 0)

    if qty > ready:
        msg = f"❌ Kho không đủ.\nCòn lại: {ready} | Bạn chọn: {qty}"
        if from_custom_qty:
            await _ask_retry(msg)
            return False
        if edit_query:
            try:
                await edit_query.edit_message_text(msg)
            except Exception:
                pass
        else:
            await context.bot.send_message(chat_id=user_id, text=msg, reply_markup=main_menu_keyboard())
        return False

    if edit_query:
        try:
            await edit_query.edit_message_text(
                f"⏳ Đang khởi tạo mã QR tự động cho *{qty}* x {product['name']}...\n\n_Vui lòng đợi vài giây..._",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    order_id = ""
    total = 0
    created_at = now_str()
    api_ok = False

    if USE_BOT_API:
        try:
            resp = await _get_http_client().post(
                f"{API_BASE_URL}/orders",
                json={
                    "user_id": user_id,
                    "stock_code": product["stock_code"],
                    "qty": qty,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    order_data = data.get("order", {})
                    order_id = order_data.get("order_id", "")
                    total = int(order_data.get("total", 0))
                    created_at = order_data.get("created_at") or created_at
                    api_ok = bool(order_id)
        except Exception as e:
            logger.warning("create order API failed: %s", e)

    if not api_ok:
        order_id = generate_order_id()
        total = int(product["price"]) * qty
        reserved_items = await gs_call(
            reserve_items_from_pool,
            product["stock_code"], qty, order_id, ORDER_TTL_SECONDS,
        )
        if len(reserved_items) < qty:
            msg = "❌ Không thể giữ kho (POOL). Vui lòng nhập lại số lượng hoặc thử lại."
            if from_custom_qty:
                await _ask_retry(msg)
                return False
            if edit_query:
                try:
                    await edit_query.edit_message_text(msg)
                except Exception:
                    pass
            else:
                await context.bot.send_message(chat_id=user_id, text=msg, reply_markup=main_menu_keyboard())
            return False

        await gs_call(append_order, {
            "order_id": order_id,
            "user_id": user_id,
            "stock_code": product["stock_code"],
            "qty": qty,
            "total": total,
            "status": "PENDING",
            "qr_msg_id": "",
            "paid_at": "",
            "tx_id": "",
            "delivered_at": "",
            "deliver_text": "",
            "created_at": created_at,
        })

    qr_url = build_vietqr_image_url(order_id, total)

    try:
        await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.UPLOAD_PHOTO)
    except Exception:
        pass

    qr_task = asyncio.create_task(fetch_qr_bytes(qr_url, timeout=6))

    if edit_query:
        try:
            await edit_query.delete_message()
        except Exception:
            pass

    caption = build_checkout_caption_with_countdown(
        order_id=order_id,
        product_name=product["name"],
        unit_price=int(product["price"]),
        qty=qty,
        total=total,
        remain_seconds=ORDER_TTL_SECONDS,
        status_line="⏳ *ĐANG CHỜ THANH TOÁN*",
    )

    # ✅ lấy qr bytes (nếu fail -> None)
    try:
        img_bytes = await qr_task
    except Exception:
        img_bytes = None

    qr_msg_id = ""
    try:
        if img_bytes:
            bio = io.BytesIO(img_bytes)
            bio.name = "vietqr.png"
            m = await context.bot.send_photo(
                chat_id=user_id,
                photo=bio,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=checkout_keyboard_pending(order_id),
            )
        else:
            m = await context.bot.send_photo(
                chat_id=user_id,
                photo=qr_url,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=checkout_keyboard_pending(order_id),
            )

        qr_msg_id = str(m.message_id)
        await gs_call(set_order_fields, order_id, {"qr_msg_id": qr_msg_id})

    except Exception as e:
        logger.error("❌ send_photo failed for %s | qr_url=%s | err=%s", order_id, qr_url, e)
        m = await context.bot.send_message(
            chat_id=user_id,
            text=caption,
            parse_mode="Markdown",
            reply_markup=checkout_keyboard_pending(order_id),
            disable_web_page_preview=True,
        )
        qr_msg_id = str(m.message_id)
        await gs_call(set_order_fields, order_id, {"qr_msg_id": qr_msg_id})

    await schedule_ttl(context.application, user_id, order_id)

    await notify_admins_order_event(
        context,
        "new",
        {
            "order_id": order_id,
            "user_id": user_id,
            "stock_code": product["stock_code"],
            "qty": qty,
            "total": total,
            "status": "PENDING",
            "created_at": created_at,
        },
    )

    return True




# ================== CONFIRM / CANCEL ==================
async def confirm_paid(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    q = update.callback_query
    await q.answer()

    order = await gs_call(get_order, order_id)
    if not order:
        try:
            return await q.edit_message_caption(caption="❌ Không tìm thấy đơn.", parse_mode="Markdown")
        except Exception:
            return await context.bot.send_message(
                chat_id=q.from_user.id,
                text="❌ Không tìm thấy đơn.",
                reply_markup=main_menu_keyboard(),
            )
    if (order.get("user_id") or "").strip() != str(q.from_user.id):
        await q.answer("⛔ Bạn không có quyền thao tác đơn này.", show_alert=True)
        return

    status = (order.get("status", "") or "PENDING").upper()
    stock_code = (order.get("stock_code") or "").strip()

    # Nếu chưa PAID -> thông báo kiểm tra
    if status not in ("PAID", "DELIVERED"):
        await context.bot.send_message(
            chat_id=q.from_user.id,
            text=(
                "⏳ *Đang kiểm tra giao dịch...*\n\n"
                "⌛ Vui lòng đợi trong giây lát...\n\n"
                "*CHƯA TÌM THẤY GIAO DỊCH*\n"
                "Hệ thống chưa phát hiện thanh toán của bạn.\n\n"
                "💡 Vui lòng:\n"
                "• Đợi thêm vài giây\n"
                "• Kiểm tra lại nội dung chuyển khoản\n"
                "• Thử lại sau"
            ),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    # ================== RESEND nếu đã DELIVERED ==================
    if status == "DELIVERED":
        delivered_at = (order.get("delivered_at") or now_str()).strip()

        deliver_text_plain = (order.get("deliver_text") or "").strip()
        secrets_plain: List[str] = []

        # Ưu tiên từ ORDERS.deliver_text (dạng "1) xxx")
        if deliver_text_plain and deliver_text_plain != "(trống)":
            for line in deliver_text_plain.splitlines():
                line = line.strip()
                if not line:
                    continue
                if ")" in line:
                    sec = line.split(")", 1)[1].strip()
                else:
                    sec = line.lstrip("-").strip()
                if sec:
                    secrets_plain.append(_safe_secret(sec))

        # Fallback: FULFILLMENTS
        if not secrets_plain:
            secrets_plain = [_safe_secret(x) for x in await gs_call(get_fulfillment_secrets, order_id)]

        secrets_md = [f"{i}) `{_safe_secret(s)}`" for i, s in enumerate(secrets_plain, start=1)]
        qty_val = normalize_int(order.get("qty"), len(secrets_plain) if secrets_plain else 1)

        # edit checkout message -> best effort
        delivered_caption = (
            "✅ *ĐƠN ĐÃ GIAO TRƯỚC ĐÓ*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🧾 *Mã đơn:* `{order_id}`\n"
            f"📦 *SP:* `{stock_code}`\n"
            f"⏱ *Thời gian:* {delivered_at}\n\n"
            "📩 Mình đang gửi lại thông tin đơn cho bạn..."
        )
        try:
            await q.edit_message_caption(caption=delivered_caption, parse_mode="Markdown", reply_markup=None)
        except Exception:
            pass

        # >=5 -> gửi file + preview
        if qty_val >= 5 or len(secrets_plain) >= 5:
            preview_n = 2
            preview_md = "\n".join(secrets_md[:preview_n]) if secrets_md else "(trống)"
            more_count = max(0, len(secrets_md) - preview_n)

            content = (
                f"ORDER: {order_id}\n"
                f"PRODUCT: {stock_code}\n"
                f"QTY: {qty_val}\n"
                f"DELIVERED_AT: {delivered_at}\n"
                "====================\n"
                + "\n".join([f"{i}) {s}" for i, s in enumerate(secrets_plain, start=1)]) +
                "\n"
            )
            bio = io.BytesIO(content.encode("utf-8"))
            bio.name = f"{order_id}.txt"

            await context.bot.send_document(
                chat_id=q.from_user.id,
                document=bio,
                caption=(
                    "✅ *ĐƠN ĐÃ GIAO — GỬI LẠI*\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"🧾 *Mã đơn:* `{order_id}`\n"
                    f"📦 *SP:* `{stock_code}`\n"
                    f"🔢 *SL:* *{qty_val}*\n\n"
                    "👀 *Preview (1–2 dòng):*\n"
                    f"{preview_md}\n"
                    f"{'…' if more_count > 0 else ''}\n\n"
                    "📎 *Xem đầy đủ trong file .txt đính kèm*."
                ),
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
            return

        deliver_text_md = "\n".join(secrets_md) if secrets_md else "(trống)"
        await context.bot.send_message(
            chat_id=q.from_user.id,
            text=(
                "✅ *ĐƠN ĐÃ GIAO — GỬI LẠI*\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🧾 *Mã đơn:* `{order_id}`\n"
                f"📦 *SP:* `{stock_code}`\n"
                f"🔢 *SL:* *{qty_val}*\n"
                f"⏱ *Thời gian:* {delivered_at}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🎁 *Thông tin nhận được:*\n{deliver_text_md}"
            ),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    # ================== GIAO HÀNG khi status=PAID ==================
    items = await gs_call(mark_sold_and_get_secrets, order_id)
    # Fallback: nếu không tìm thấy HELD nhưng fulfillments đã có -> coi như delivered và resend
    if not items:
        secrets = await gs_call(get_fulfillment_secrets, order_id)
        if secrets:
            await gs_call(set_order_fields, order_id, {"status": "DELIVERED"})
            return await confirm_paid(update, context, order_id)

        await context.bot.send_message(
            chat_id=q.from_user.id,
            text="❌ Không tìm thấy item HELD để giao (POOL).",
            reply_markup=main_menu_keyboard(),
        )
        return


    delivered_at = now_str()

    secrets_plain = []
    secrets_md = []
    for i, it in enumerate(items, start=1):
        sec = _safe_secret(it.get("secret", ""))
        if not sec:
            continue
        secrets_plain.append(f"{i}) {sec}")
        secrets_md.append(f"{i}) `{sec}`")

    deliver_text_plain = "\n".join(secrets_plain) if secrets_plain else "(trống)"
    deliver_text_md = "\n".join(secrets_md) if secrets_md else "(trống)"

    await gs_call(append_fulfillments_bulk, order_id, items, delivered_at)

    await gs_call(set_order_fields, order_id, {
        "status": "DELIVERED",
        "delivered_at": delivered_at,
        "deliver_text": deliver_text_plain
    })

    # stop countdown job
    remove_jobs_by_prefix(context.application, f"countdown_{order_id}")

    # edit checkout message -> best effort
    delivered_caption = (
        "✅ *ĐÃ GIAO HÀNG*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🧾 *Mã đơn:* `{order_id}`\n"
        f"📦 *SP:* `{stock_code}`\n"
        f"⏱ *Thời gian:* {delivered_at}\n\n"
        "📩 Mình đã gửi thông tin nhận được ở tin nhắn bên dưới."
    )
    try:
        await q.edit_message_caption(caption=delivered_caption, parse_mode="Markdown", reply_markup=checkout_keyboard_done())
    except Exception:
        try:
            await q.edit_message_text(text=delivered_caption, parse_mode="Markdown", reply_markup=checkout_keyboard_done())
        except Exception:
            pass

    qty_val = normalize_int(order.get("qty"), len(secrets_plain) if secrets_plain else len(items))

    delivered_row = dict(order)
    delivered_row["status"] = "DELIVERED"
    delivered_row["delivered_at"] = delivered_at
    await notify_admins_order_event(context, "delivered", delivered_row, actor_id=q.from_user.id)

    # >=5 -> gửi file + preview
    if qty_val >= 5 or len(secrets_plain) >= 5:
        preview_n = 2
        preview_md = "\n".join(secrets_md[:preview_n]) if secrets_md else "(trống)"
        more_count = max(0, len(secrets_md) - preview_n)

        content = (
            f"ORDER: {order_id}\n"
            f"PRODUCT: {stock_code}\n"
            f"QTY: {qty_val}\n"
            f"DELIVERED_AT: {delivered_at}\n"
            "====================\n"
            + deliver_text_plain +
            "\n"
        )
        bio = io.BytesIO(content.encode("utf-8"))
        bio.name = f"{order_id}.txt"

        await context.bot.send_document(
            chat_id=q.from_user.id,
            document=bio,
            caption=(
                "✅ *MUA HÀNG THÀNH CÔNG*\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🧾 *Mã đơn:* `{order_id}`\n"
                f"📦 *SP:* `{stock_code}`\n"
                f"🔢 *SL:* *{qty_val}*\n\n"
                "👀 *Preview (1–2 dòng):*\n"
                f"{preview_md}\n"
                f"{'…' if more_count > 0 else ''}\n\n"
                "📎 *Xem đầy đủ trong file .txt đính kèm* (bấm để copy nhanh).\n"
                "🔐 Nếu là tài khoản, vui lòng *đổi mật khẩu ngay* sau khi đăng nhập."
            ),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    await context.bot.send_message(
        chat_id=q.from_user.id,
        text=(
            "✅ *MUA HÀNG THÀNH CÔNG*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🧾 *Mã đơn:* `{order_id}`\n"
            f"📦 *SP:* `{stock_code}`\n"
            f"🔢 *SL:* *{qty_val}*\n"
            f"⏱ *Thời gian:* {delivered_at}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🎁 *Thông tin nhận được:*\n{deliver_text_md}\n\n"
            "🔐 Nếu là tài khoản, vui lòng *đổi mật khẩu ngay* sau khi đăng nhập."
        ),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    q = update.callback_query
    user_id = q.from_user.id

    order = await gs_call(get_order, order_id)
    if not order:
        await q.answer("Không tìm thấy đơn", show_alert=True)
        await context.bot.send_message(chat_id=user_id, text="❌ Không tìm thấy đơn.", reply_markup=main_menu_keyboard())
        return
    if (order.get("user_id") or "").strip() != str(user_id):
        await q.answer("⛔ Bạn không có quyền huỷ đơn này.", show_alert=True)
        return

    st = (order.get("status") or "PENDING").upper()
    if st in ("DELIVERED", "CANCELLED", "EXPIRED"):
        await q.answer("Đơn không thể huỷ", show_alert=True)
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ Đơn đã kết thúc, không thể huỷ thêm." if st == "DELIVERED" else "ℹ️ Đơn đã huỷ / hết hạn trước đó.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await q.answer("Đang huỷ đơn…")
    order_rownum = int(order["_rownum"]) if str(order.get("_rownum", "")).isdigit() else None
    qr_msg_id = (order.get("qr_msg_id") or "").strip()
    remove_jobs_by_prefix(context.application, f"countdown_{order_id}")
    remove_jobs_by_prefix(context.application, f"ttl_{order_id}")

    delete_qr = None
    if qr_msg_id.isdigit():
        delete_qr = asyncio.create_task(
            context.bot.delete_message(chat_id=user_id, message_id=int(qr_msg_id))
        )

    released = await gs_call(release_hold_by_order, order_id, "CANCELLED", order_rownum)

    if delete_qr:
        try:
            await delete_qr
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=user_id,
        text=f"❌ Đã huỷ đơn `{order_id}`.\n✅ Trả kho: *{released}* item.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

    cancelled_row = dict(order)
    cancelled_row["status"] = "CANCELLED"
    asyncio.create_task(
        notify_admins_order_event(
            context,
            "cancelled",
            cancelled_row,
            released=released,
            actor_id=user_id,
        )
    )

# ================== ORDERS SCREEN ==================
# ✅ Thêm hàm này (đặt ở gần restore_pending_jobs cũng được)
async def bootstrap_job(context: ContextTypes.DEFAULT_TYPE):
    await restore_pending_jobs(context.application)


async def release_overdue_pending_job(context: ContextTypes.DEFAULT_TYPE):
    """Quét định kỳ để trả HELD nếu bot/Render bị restart làm mất job TTL."""
    try:
        pending = await gs_call(list_pending_orders)
    except Exception as e:
        logger.error("release_overdue_pending_job failed: %s", e)
        return

    expired_count = 0
    released_total = 0
    for order in pending:
        order_id = (order.get("order_id") or "").strip()
        user_id_s = (order.get("user_id") or "").strip()
        created_at_s = (order.get("created_at") or "").strip()
        qr_msg_id_s = (order.get("qr_msg_id") or "").strip()
        created_dt = parse_dt(created_at_s)
        if not order_id or not created_dt:
            continue
        if (created_dt + timedelta(seconds=ORDER_TTL_SECONDS)) > now_dt():
            continue

        released = await gs_call(release_hold_by_order, order_id, "EXPIRED")
        expired_count += 1
        released_total += released
        remove_jobs_by_prefix(context.application, f"countdown_{order_id}")
        remove_jobs_by_prefix(context.application, f"ttl_{order_id}")

        if user_id_s.isdigit():
            user_id = int(user_id_s)
            if qr_msg_id_s.isdigit():
                try:
                    await context.bot.delete_message(chat_id=user_id, message_id=int(qr_msg_id_s))
                except Exception:
                    pass
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"⌛ Đơn `{order_id}` đã *hết hạn* nên hệ thống đã huỷ.\n"
                        f"✅ Đã trả kho: *{released}* item.\n\n"
                        "Bạn tạo đơn mới nếu vẫn muốn mua nhé."
                    ),
                    parse_mode="Markdown",
                    reply_markup=main_menu_keyboard(),
                )
            except Exception:
                pass

    if expired_count:
        logger.info("✅ Auto released overdue orders=%s items=%s", expired_count, released_total)
        await notify_admins(
            context,
            (
                "⌛ *Có đơn hết hạn tự động*\n"
                f"Số đơn: `{expired_count}`\n"
                f"Trả kho: `{released_total}` item"
            ),
        )


async def restore_pending_jobs(app: Application):
    """Khôi phục TTL/Countdown cho các đơn PENDING khi bot vừa chạy lại."""
    if not app.job_queue:
        return

    try:
        pending = await gs_call(list_pending_orders)
    except Exception as e:
        logger.error("restore_pending_jobs failed: %s", e)
        return

    for o in pending:
        order_id = (o.get("order_id") or "").strip()
        user_id_s = (o.get("user_id") or "").strip()
        created_at_s = (o.get("created_at") or "").strip()
        qr_msg_id_s = (o.get("qr_msg_id") or "").strip()

        if not order_id or not user_id_s.isdigit():
            continue
        user_id = int(user_id_s)

        created_dt = parse_dt(created_at_s)
        if not created_dt:
            continue

        # thời gian còn lại
        expire_dt = created_dt + timedelta(seconds=ORDER_TTL_SECONDS)
        remain = int((expire_dt - now_dt()).total_seconds())

        # Nếu đã quá hạn -> trả kho + xoá QR + báo user (best effort)
        if remain <= 0:
            released = await gs_call(release_hold_by_order, order_id, "EXPIRED")

            # xoá tin QR nếu có
            if qr_msg_id_s.isdigit():
                try:
                    await app.bot.delete_message(chat_id=user_id, message_id=int(qr_msg_id_s))
                except Exception:
                    pass

            # dọn job cũ nếu có (phòng trường hợp trùng)
            remove_jobs_by_prefix(app, f"countdown_{order_id}")

            try:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"⌛ Đơn `{order_id}` đã *hết hạn* nên hệ thống đã huỷ.\n"
                        f"✅ Đã trả kho: *{released}* item.\n\n"
                        "Bạn tạo đơn mới nếu vẫn muốn mua nhé."
                    ),
                    parse_mode="Markdown",
                    reply_markup=main_menu_keyboard(),
                )
            except Exception:
                pass
            continue

        # Nếu còn hạn -> schedule TTL theo remain
        app.job_queue.run_once(
            ttl_job,
            when=remain,
            data={"user_id": user_id, "order_id": order_id},
            name=f"ttl_{order_id}",
        )

    logger.info("✅ Restored jobs for %s pending orders", len(pending))



def parse_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def list_pending_orders() -> List[Dict[str, str]]:
    """Lấy tất cả orders status=PENDING để khôi phục job sau khi bot restart."""
    init_sheets()
    vals = _ws_orders.get_all_values()
    if not vals or len(vals) < 2:
        return []
    h = {str(x).strip().lower(): i for i, x in enumerate(vals[0], start=1)}

    c_status = h.get("status")
    if not c_status:
        return []

    out = []
    for idx in range(2, len(vals) + 1):
        r = vals[idx - 1]
        st = r[c_status - 1].strip().upper() if c_status - 1 < len(r) else ""
        if st == "PENDING":
            d = {}
            for k, c in h.items():
                d[k] = r[c - 1].strip() if c - 1 < len(r) else ""
            out.append(d)
    return out




def status_emoji(status: str) -> str:
    s = (status or "").upper()
    if s == "PENDING":
        return "⏳"
    if s == "PAID":
        return "✅"
    if s == "DELIVERED":
        return "🎁"
    if s == "CANCELLED":
        return "❌"
    if s == "EXPIRED":
        return "⌛"
    return "⏳"


def _secrets_from_deliver_text(deliver_text: str) -> List[str]:
    secrets: List[str] = []
    for line in (deliver_text or "").splitlines():
        line = line.strip()
        if not line or line == "(trống)":
            continue
        if ")" in line:
            sec = line.split(")", 1)[1].strip()
        else:
            sec = line.lstrip("-").strip()
        if sec:
            secrets.append(_safe_secret(sec))
    return secrets


async def _purchased_items_block(order: Dict[str, str]) -> str:
    if (order.get("status") or "").upper() != "DELIVERED":
        return ""
    secrets = _secrets_from_deliver_text(order.get("deliver_text") or "")
    if not secrets:
        oid = (order.get("order_id") or "").strip()
        if oid:
            secrets = [_safe_secret(x) for x in await gs_call(get_fulfillment_secrets, oid)]
    if not secrets:
        return ""
    lines = ["🎁 *Vật phẩm đã mua:*"]
    for i, sec in enumerate(secrets, start=1):
        lines.append(f"{i}) `{sec}`")
    return "\n".join(lines)


async def show_orders(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        orders = await gs_call(list_user_orders, user_id, 10)
    except Exception as e:
        logger.exception("show_orders error")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Lỗi Google Sheets:\n{e}",
            reply_markup=main_menu_keyboard(),
        )
        return
    if not orders:
        await context.bot.send_message(
            chat_id=user_id,
            text="📦 *ĐƠN HÀNG ĐÃ MUA*\n\n(Trống)\n\nBấm 🛍 Sản phẩm để mua.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    products, _ = await refresh_catalog_cache()
    name_by_code = {p["stock_code"]: p["name"] for p in products}

    lines = ["📦 *ĐƠN HÀNG ĐÃ MUA*\n", "5 đơn gần nhất:\n", "━━━━━━━━━━━━━━━━"]

    for o in orders[:5]:
        oid = o.get("order_id", "")
        sc = o.get("stock_code", "")
        qty = o.get("qty", "")
        total = normalize_int(o.get("total"), 0)
        created = o.get("created_at", "")
        st = (o.get("status") or "PENDING").upper()
        emoji = status_emoji(st)
        product_name = name_by_code.get(sc) or sc

        lines.append(
            f"\n`{oid}`\n"
            f"📦 *{product_name}*\n"
            f"Mã kho: `{sc}` | SL: *{qty}*\n"
            f"Tổng: *{fmt_price(total)}*\n"
            f"📅 {created}\n"
            f"📌 Trạng thái: {emoji} *{st}*"
        )
        items_block = await _purchased_items_block(o)
        if items_block:
            lines.append(items_block)
        lines.append("━━━━━━━━━━━━━━━━")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…(rút gọn)"

    await context.bot.send_message(
        chat_id=user_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

# ================== ACCOUNT ==================
async def show_account(chat_id: int, context: ContextTypes.DEFAULT_TYPE, user):
    orders = await gs_call(list_user_orders, user.id, 200)
    count = len(orders)
    total_spent = sum(normalize_int(o.get("total"), 0) for o in orders)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "👤 *TÀI KHOẢN*\n\n"
            f"• Họ tên: *{user.full_name}*\n"
            f"• Username: @{user.username if user.username else '—'}\n"
            f"• User ID: `{user.id}`\n\n"
            f"📦 Tổng đơn: *{count}*\n"
            f"💰 Tổng đã mua: *{fmt_price(total_spent)}*"
        ),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

# ================== TEXT ROUTER ==================

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await handle_custom_qty_input(update, context):
        return

    user = update.effective_user
    schedule_upsert_user(update.effective_chat.id, user.username or "", user.full_name or "")

    text = (update.message.text or "").strip()
    text = text.replace("\ufe0f", "")
    text = " ".join(text.split())
    menu_text = normalize_menu_text(text)

    if looks_like_mail_account(text):
        return await read_mail_from_text(update, text)
    if looks_like_totp_secret(text):
        return await send_2fa_from_text(update, context, text)

    if text == BTN_PRODUCTS or "sản phẩm" in menu_text or "san pham" in menu_text:
        return await show_products(user.id, context)
    if text == BTN_SUPPORT or "hỗ trợ" in menu_text or "ho tro" in menu_text:
        return await send_support(user.id, context)
    if text == BTN_ORDERS or "đơn hàng" in menu_text or "don hang" in menu_text:
        return await show_orders(user.id, context)
    if text == BTN_2FA or menu_text in {"2fa", "ma 2fa", "mã 2fa"}:
        return await send_2fa_help(user.id, context)
    if text == BTN_MAIL or "đọc mail" in menu_text or "doc mail" in menu_text:
        return await send_mail_help(user.id, context)

    await update.message.reply_text("Bấm menu để sử dụng nhé.", reply_markup=main_menu_keyboard())


# ================== CALLBACK ROUTER ==================
# ✅ Sửa lại cmd_hangve (copy đè lên hàm cũ)
async def cmd_hangve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # chỉ admin được dùng
    if update.effective_user.id not in ADMIN_IDS:
        return

    text = " ".join(context.args).strip()
    if not text:
        text = "✅ *HÀNG ĐÃ VỀ*\n\n🔥 Sản phẩm đã có hàng lại!\n👉 Vào /shop để mua nhé."

    user_ids = await gs_call(get_all_user_chat_ids)

    ok = fail = 0
    for cid in user_ids:
        try:
            await context.bot.send_message(
                chat_id=cid,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            ok += 1
            await asyncio.sleep(0.05)  # chống rate limit nhẹ
        except Exception as e:
            fail += 1
            logger.warning("send hangve fail chat_id=%s err=%s", cid, e)

    await update.message.reply_text(f"Đã gửi: {ok} | Lỗi: {fail}")



async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    # ✅ NÚT NHANH: Đơn hàng / Hỗ trợ
    if data == "go_products":
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        return await show_products(q.from_user.id, context)

    if data == "go_orders":
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        return await show_orders(q.from_user.id, context)

    if data == "go_support":
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        return await send_support(q.from_user.id, context)

    if data == "mail_help":
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        return await send_mail_help(q.from_user.id, context)

    if data == "mail_repeat":
        await q.answer("Đang đọc lại thư...")
        return await read_mail_again(q.message.chat_id, q.from_user.id, context)

    if data == "2fa_help":
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        return await send_2fa_help(q.from_user.id, context)

    if data == "back_main":
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=q.from_user.id,
            text=welcome_text(q.from_user.full_name),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "back_products":
        await q.answer()
        try:
            await q.message.delete()
        except Exception:
            pass
        return await show_products(q.from_user.id, context)

    if data.startswith("pdetail|"):
        pid = data.split("|", 1)[1]
        return await show_product_detail(update, context, pid)

    if data.startswith("pdetail_back|"):
        pid = data.split("|", 1)[1]
        return await show_product_detail(update, context, pid)

    if data.startswith("buy|"):
        pid = data.split("|", 1)[1]
        return await ask_qty(update, context, pid)

    if data.startswith("qty|"):
        _, pid, qty_s = data.split("|", 2)
        return await qty_chosen(update, context, pid, int(qty_s))

    if data.startswith("qtycustom|"):
        pid = data.split("|", 1)[1]
        return await set_custom_qty_prompt(update, context, pid)

    if data.startswith("confirm|"):
        oid = data.split("|", 1)[1]
        return await confirm_paid(update, context, oid)

    if data.startswith("cancel|"):
        oid = data.split("|", 1)[1]
        return await cancel_order(update, context, oid)

    await q.answer()

async def warmup_catalog_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await refresh_catalog_cache(force=True)
        logger.info("✅ Catalog cache warmed (%s products)", len(_CACHE["products"]["data"]))
    except Exception as e:
        logger.warning("Catalog warmup failed: %s", e)


def configure_application(app: Application) -> Application:
    if not app.job_queue:
        logger.warning("⚠️ JobQueue not available. Install: pip install python-telegram-bot[job-queue]")
    else:
        app.job_queue.run_once(warmup_catalog_job, when=1, name="warmup_catalog")
        # ✅ khôi phục TTL/Countdown cho các đơn PENDING sau restart
        app.job_queue.run_once(bootstrap_job, when=2, name="bootstrap_restore")
        app.job_queue.run_repeating(
            release_overdue_pending_job,
            interval=60,
            first=20,
            name="release_overdue_pending",
        )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("shop", cmd_shop))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("support", cmd_support))
    app.add_handler(CommandHandler("hangve", cmd_hangve))
    app.add_handler(CommandHandler("mail", cmd_mail))
    app.add_handler(CommandHandler("2fa", cmd_2fa))
    app.add_handler(CommandHandler("otp", cmd_2fa))

    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    return app


def build_application() -> Application:
    try:
        init_sheets()
        logger.info("✅ Sheets OK: %s", GSHEET_ID)
    except Exception as e:
        logger.error("❌ init_sheets error: %s", e)

    app = Application.builder().token(BOT_TOKEN).build()
    return configure_application(app)


# ================== MAIN ==================
def main():
    app = build_application()
    logger.info("✅ Bot running...")
    app.run_polling(drop_pending_updates=True, stop_signals=False)


if __name__ == "__main__":
    main()
