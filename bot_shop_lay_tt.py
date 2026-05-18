import os
import re
import io
import logging
import random
import string
import asyncio
import time
import urllib.request
from telegram.constants import ChatAction
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dotenv import load_dotenv
import json
import urllib.request
from email.utils import parsedate_to_datetime

import httpx

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
API_BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8080/api")
API_LOCK = asyncio.Lock()
# ================== LOGGING ==================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("vanminh_store_bot")

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
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
_ws_users = None

ADMIN_IDS = {5322953111}  # <-- đổi thành Telegram user id của bạn

ORDER_TTL_SECONDS = int(os.getenv("ORDER_TTL_SECONDS", "900"))  # 15 phút

# BIDV
PAYMENT_INFO = {
    "bank_code": os.getenv("BANK_CODE", "BIDV").strip(),
    "bank_name": os.getenv("BANK_NAME", "BIDV").strip(),
    "bank_owner": os.getenv("BANK_OWNER", "NGUYEN VAN MINH").strip(),
    "bank_number": os.getenv("BANK_NUMBER", "8867625524").strip(),
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


PENDING_QTY: Dict[int, Dict[str, Any]] = {}  # user_id -> {"product_id": ...}
_KNOWN_USERS = set()

# ================== HELPERS ==================
_CACHE = {
    "products": {"ts": 0.0, "data": []},
    "stock": {"ts": 0.0, "data": {}},
}
def _ts() -> float:
    return time.time()

def invalidate_stock_cache():
    _CACHE["stock"]["ts"] = 0.0

def load_products_cached(ttl: int = 30) -> List[Dict[str, Any]]:
    if _ts() - _CACHE["products"]["ts"] < ttl and _CACHE["products"]["data"]:
        return _CACHE["products"]["data"]
    data = load_products()
    _CACHE["products"] = {"ts": _ts(), "data": data}
    return data

def normalize_order_ref(s: str) -> str:
    # giữ chữ/số, bỏ hết ký tự lạ như '-', ' ', '.', ...
    return re.sub(r"[^A-Za-z0-9]", "", (s or "")).upper()

def stock_count_ready_by_code_cached(ttl: int = 5) -> Dict[str, int]:
    if _ts() - _CACHE["stock"]["ts"] < ttl and _CACHE["stock"]["data"]:
        return _CACHE["stock"]["data"]
    data = stock_count_ready_by_code()
    _CACHE["stock"] = {"ts": _ts(), "data": data}
    return data

async def gs_call(fn, *args, **kwargs):
    # Just run the function since it's now mostly async HTTP requests
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return fn(*args, **kwargs)

    
def now_dt() -> datetime:
    return datetime.now()

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
        return int((expire_at - datetime.now()).total_seconds())
    except Exception:
        return 0

def format_countdown(seconds: int) -> str:
    if seconds <= 0:
        return "0 giây"
    m, s = divmod(seconds, 60)
    return f"{m} phút {s} giây" if m > 0 else f"{s} giây"

def build_checkout_caption_with_countdown(
    order_id: str,
    product_name: str,
    unit_price: int,
    qty: int,
    total: int,
    remain_seconds: int,
    status_line: str = "⏳ *ĐANG CHỜ THANH TOÁN*",
) -> str:
    remain_text = format_countdown(remain_seconds)
    bank_acc = PAYMENT_INFO["bank_number"]
    bank_code = PAYMENT_INFO["bank_code"].upper()

    pay_note = normalize_order_ref(order_id) # hàm của bạn đã bỏ ký tự lạ

    return (
        f"{status_line}\n\n"
        f"🧾 Mã đơn: `{order_id}`\n"
        f"📦 SP: *{product_name}* — {fmt_price(unit_price)}\n"
        f"🔢 SL: *{qty}*\n"
        f"💰 Tổng: *{fmt_price(total)}*\n\n"
        f"⏳ *Hết hạn sau:* `{remain_text}`\n\n"
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
    if chat_id in _KNOWN_USERS: return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{API_BASE_URL}/users", json={"chat_id": chat_id, "username": username, "full_name": full_name})
        _KNOWN_USERS.add(chat_id)
    except Exception as e:
        logger.error(f"upsert_user error: {e}")



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

async def _fetch_api_data():
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{API_BASE_URL}/products", timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("products", []), data.get("stock", {})
    except Exception as e:
        logger.error(f"API fetch error: {e}")
    return [], {}

async def load_products_cached(ttl: int = 30) -> List[Dict[str, Any]]:
    if _ts() - _CACHE["products"]["ts"] < ttl and _CACHE["products"]["data"]:
        return _CACHE["products"]["data"]
    prods, stock = await _fetch_api_data()
    if prods:
        _CACHE["products"] = {"ts": _ts(), "data": prods}
        _CACHE["stock"] = {"ts": _ts(), "data": stock}
        return prods
    return _CACHE["products"]["data"]

async def stock_count_ready_by_code_cached(ttl: int = 5) -> Dict[str, int]:
    if _ts() - _CACHE["stock"]["ts"] < ttl and _CACHE["stock"]["data"]:
        return _CACHE["stock"]["data"]
    prods, stock = await _fetch_api_data()
    if stock:
        _CACHE["products"] = {"ts": _ts(), "data": prods}
        _CACHE["stock"] = {"ts": _ts(), "data": stock}
        return stock
    return _CACHE["stock"]["data"]

async def find_product_by_id(pid: str) -> Optional[Dict[str, Any]]:
    prods = await load_products_cached()
    for p in prods:
        if p["product_id"] == pid: return p
    return None

async def find_product_by_stock_code(stock_code: str) -> Optional[Dict[str, Any]]:
    prods = await load_products_cached()
    for p in prods:
        if p["stock_code"] == stock_code: return p
    return None

# MOCK POOL OLD 

async def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{API_BASE_URL}/orders/{order_id}", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("order")
    except Exception as e:
        logger.error(f"get_order error {order_id}: {e}")
    return None

async def set_order_fields(order_id: str, updates: Dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient() as client:
            await client.patch(f"{API_BASE_URL}/orders/{order_id}", json=updates, timeout=10.0)
    except Exception as e:
        logger.error(f"set_order_fields error {order_id}: {e}")

async def release_hold_by_order(order_id: str, mark_status: str) -> int:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{API_BASE_URL}/orders/{order_id}/cancel", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("released", 0)
    except Exception as e:
        logger.error(f"release_hold_by_order error {order_id}: {e}")
    return 0

async def list_user_orders(user_id: int, limit: int = 10) -> List[Dict[str, str]]:
    # Mocking for now as the API currently doesn't have a specific endpoint for user orders
    # You can add the endpoint /api/users/{user_id}/orders if needed
    return []

# MOCK functions for compatibility that are now handled centrally 
async def mark_sold_and_get_secrets(order_id: str) -> List[Dict[str, str]]: return []
async def append_fulfillments_bulk(order_id: str, items: List[Dict[str, str]], delivered_at: str) -> None: pass
async def get_fulfillment_secrets(order_id: str) -> List[str]: return []


# ================== UI: MAIN MENU ==================
BTN_PRODUCTS = "🛍 Sản phẩm".replace("\ufe0f","")
BTN_SUPPORT  = "💬 Hỗ trợ".replace("\ufe0f","")
BTN_ORDERS   = "📦 Đơn hàng".replace("\ufe0f","")
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(BTN_PRODUCTS), KeyboardButton(BTN_SUPPORT)],
        [KeyboardButton(BTN_ORDERS)],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)



def welcome_text(user_fullname: str) -> str:
    return (
        f"👋 *xin chào {user_fullname}!* \n\n"
        f"*{SHOP_NAME}* rất vui được phục vụ bạn.\n\n"
        "✅ Hàng số chuẩn • giao tự động 24/7\n\n"
        "📌 *Lệnh nhanh:*\n\n"
        "/shop - Xem sản phẩm\n\n"
        "/orders - Đơn hàng của bạn\n\n"
        "/support - Hỗ trợ\n\n"
        f"😘 “Mỗi đơn hàng bạn đặt tại {SHOP_NAME} không chỉ là một sản phẩm – đó là sự tin tưởng bạn gửi gắm "
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

    # ✅ LƯU USER 
    await gs_call(upsert_user, update.effective_chat.id, user.username or "", user.full_name or "")

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

# ================== PRODUCTS FLOW ==================
async def show_products(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        products = await gs_call(load_products_cached)
        stock_ready = await gs_call(stock_count_ready_by_code_cached)
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

    # ✅ đọc stock bằng cache + thread
    ready_map = await gs_call(stock_count_ready_by_code_cached)
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
            await edit_query.edit_message_text(f"⏳ Đang khởi tạo mã QR tự động cho *{qty}* x {product['name']}...\n\n_Vui lòng đợi vài giây..._", parse_mode="Markdown")
        except Exception:
            pass

    # ✅ Gọi API để tạo order và reserve kho
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{API_BASE_URL}/orders", json={
                "user_id": user_id,
                "stock_code": product["stock_code"],
                "qty": qty
            }, timeout=10.0)
            if resp.status_code != 200:
                raise Exception(resp.text)
            
            data = resp.json()
            if not data.get("ok"):
                raise Exception(data)
            
            order_data = data.get("order", {})
            order_id = order_data.get("order_id")
            total = int(order_data.get("total", 0))
            created_at = order_data.get("created_at")
            
    except Exception as e:
        logger.error(f"Failed to create order via API: {e}")
        msg = "❌ Không thể tạo đơn hàng hoặc kho không đủ. Vui lòng thử lại."
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

    qr_url = build_vietqr_image_url(order_id, total)

    # ✅ cho user thấy bot đang làm việc
    try:
        await context.bot.send_chat_action(chat_id=user_id, action=ChatAction.UPLOAD_PHOTO)
    except Exception:
        pass

    # ✅ tải QR song song (giảm timeout để khỏi đứng lâu)
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

    if context.application.job_queue and qr_msg_id:
        context.application.job_queue.run_repeating(
            countdown_job,
            interval=60,
            first=60,
            data={"order_id": order_id, "user_id": user_id},
            name=f"countdown_{order_id}",
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
                + "\n==================================\n".join([f"{i}) {s}" for i, s in enumerate(secrets_plain, start=1)]) +
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

        deliver_text_md = "\n==================================\n".join(secrets_md) if secrets_md else "(trống)"
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

    deliver_text_plain = "\n==================================\n".join(secrets_plain) if secrets_plain else "(trống)"
    deliver_text_md = "\n==================================\n".join(secrets_md) if secrets_md else "(trống)"

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
    await q.answer()

    order = await gs_call(get_order,order_id)
    if not order:
        await context.bot.send_message(chat_id=q.from_user.id, text="❌ Không tìm thấy đơn.", reply_markup=main_menu_keyboard())
        return
    # ✅ CHECK QUYỀN
    if (order.get("user_id") or "").strip() != str(q.from_user.id):
        await q.answer("⛔ Bạn không có quyền huỷ đơn này.", show_alert=True)
        return
    
    st = (order.get("status") or "PENDING").upper()
    if st in ("DELIVERED",):
        await context.bot.send_message(chat_id=q.from_user.id, text="✅ Đơn đã giao, không thể huỷ.", reply_markup=main_menu_keyboard())
        return

    released = await gs_call(release_hold_by_order,order_id, "CANCELLED")

    qr_msg_id = (order.get("qr_msg_id") or "").strip()
    if qr_msg_id.isdigit():
        try:
            await context.bot.delete_message(chat_id=q.from_user.id, message_id=int(qr_msg_id))
        except Exception:
            pass

    remove_jobs_by_prefix(context.application, f"countdown_{order_id}")

    await context.bot.send_message(
        chat_id=q.from_user.id,
        text=f"❌ Đã huỷ đơn `{order_id}`.\n✅ Trả kho: *{released}* item.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

# ================== ORDERS SCREEN ==================
# ✅ Thêm hàm này (đặt ở gần restore_pending_jobs cũng được)
async def bootstrap_job(context: ContextTypes.DEFAULT_TYPE):
    await restore_pending_jobs(context.application)

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
        remain = int((expire_dt - datetime.now()).total_seconds())

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

        # schedule countdown nếu có qr_msg_id
        if qr_msg_id_s.isdigit():
            app.job_queue.run_repeating(
                countdown_job,
                interval=60,
                first=60,
                data={"order_id": order_id, "user_id": user_id},
                name=f"countdown_{order_id}",
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

    lines = ["📦 *ĐƠN HÀNG ĐÃ MUA*\n", "Danh sách 5 đơn gần nhất:\n", "━━━━━━━━━━━━━━━━"]
    kb_rows = []

    for o in orders[:5]:
        oid = o.get("order_id", "")
        sc = o.get("stock_code", "")
        qty = o.get("qty", "")
        total = normalize_int(o.get("total"), 0)
        created = o.get("created_at", "")
        st = o.get("status", "PENDING")
        emoji = status_emoji(st)

        lines.append(
            f"\n`{oid}`\n"
            f"SP: `{sc}` | SL: *{qty}*\n"
            f"Tổng: *{fmt_price(total)}*\n"
            f"📅 {created}\n"
            f"📌 Trạng thái: {emoji} *{st}*\n"
            "━━━━━━━━━━━━━━━━"
        )

        p = await gs_call(find_product_by_stock_code, sc)
        if p:
            kb_rows.append([InlineKeyboardButton(f"🔁 Mua lại: {p['name']}", callback_data=f"rebuy|{p['product_id']}")])

    kb_rows.append([InlineKeyboardButton("⬅️ Menu chính", callback_data="back_main")])

    await context.bot.send_message(
        chat_id=user_id,
        text="\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb_rows),
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
    await gs_call(upsert_user, update.effective_chat.id, user.username or "", user.full_name or "")

    text = (update.message.text or "").strip()
    text = text.replace("\ufe0f", "")
    text = " ".join(text.split())

    if text == BTN_PRODUCTS:
        return await show_products(user.id, context)
    if text == BTN_SUPPORT:
        return await send_support(user.id, context)
    if text == BTN_ORDERS:
        return await show_orders(user.id, context)

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

    if data.startswith("rebuy|"):
        pid = data.split("|", 1)[1]
        p = await gs_call(find_product_by_id, pid)
        if not p:
            await q.answer("Không tìm thấy sản phẩm", show_alert=True)
            return
        await q.answer()
        return await checkout_flow(q.from_user.id, p, 1, context, edit_query=q)

    await q.answer()

# ================== MAIN ==================
def main():

    app = Application.builder().token(BOT_TOKEN).build()

    if not app.job_queue:
        logger.warning("⚠️ JobQueue not available. Install: pip install python-telegram-bot[job-queue]")
    else:
        # ✅ khôi phục TTL/Countdown cho các đơn PENDING sau restart
        app.job_queue.run_once(bootstrap_job, when=2, name="bootstrap_restore")

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("shop", cmd_shop))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("support", cmd_support))
    app.add_handler(CommandHandler("hangve", cmd_hangve))

    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info("✅ Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
