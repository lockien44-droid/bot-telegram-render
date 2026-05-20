"""Custom (premium) emoji helpers — gửi theo Bot API (HTML ``<tg-emoji>``).

Ví dụ (chủ bot cần Telegram Premium):

    await bot.send_message(
        chat_id,
        '<tg-emoji emoji-id="5359726582447487916">📱</tg-emoji> Hello',
        parse_mode="HTML",
    )

Placeholder ``📱`` phải khớp đúng ký tự trong tin gốc (entity length = 2 UTF-16).
"""

from __future__ import annotations

import os
import re
from html import escape
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from telegram import Message, MessageEntity
except Exception:  # pragma: no cover
    Message = None  # type: ignore[assignment]
    MessageEntity = None  # type: ignore[assignment]


EMOJI_IDS: dict[str, str] = {
    "chatgpt": "5359726582447487916",
}

EMOJI_FALLBACKS: dict[str, str] = {
    "chatgpt": (os.getenv("CUSTOM_EMOJI_CHATGPT_FALLBACK", "📱") or "📱").strip(),
}

# Tiền tố trước icon GPT (để trống = chỉ hiện custom emoji, không thêm 🏷️).
GPT_PRODUCT_TAG_PREFIX = (os.getenv("GPT_PRODUCT_TAG_PREFIX", "") or "").strip()

_TG_EMOJI_RE = re.compile(
    r'<tg-emoji emoji-id="(\d+)">([^<]*)</tg-emoji>',
    re.IGNORECASE,
)


def set_emoji_id(name: str, emoji_id: str) -> None:
    EMOJI_IDS[name.strip().lower()] = (emoji_id or "").strip()


def get_emoji_id(name: str) -> str:
    return EMOJI_IDS.get((name or "").strip().lower(), "")


def tg_emoji(name_or_id: str, fallback: Optional[str] = None) -> str:
    """Trả về thẻ HTML ``<tg-emoji>`` (dùng với ``parse_mode='HTML'``)."""
    raw = (name_or_id or "").strip()
    emoji_id = raw if raw.isdigit() else get_emoji_id(raw)
    if not emoji_id:
        return escape((fallback or "").strip() or "•")
    key = raw.lower() if not raw.isdigit() else ""
    fb = (fallback or EMOJI_FALLBACKS.get(key, "") or "").strip() or "📱"
    return f'<tg-emoji emoji-id="{escape(emoji_id)}">{escape(fb)}</tg-emoji>'


def chatgpt_icon_html() -> str:
    """Custom emoji ChatGPT (HTML ``<tg-emoji>``), không kèm emoji 🏷️."""
    if not get_emoji_id("chatgpt"):
        return "📱 "
    prefix = GPT_PRODUCT_TAG_PREFIX
    return f"{prefix}{tg_emoji('chatgpt')} "


def strip_tg_emoji_html(text: str) -> str:
    """Bỏ thẻ tg-emoji → chỉ còn ký tự fallback (khi API từ chối custom emoji)."""

    def _repl(m: re.Match[str]) -> str:
        return m.group(2) or ""

    return _TG_EMOJI_RE.sub(_repl, text or "")


def is_gpt_product_name(name: str) -> bool:
    s = (name or "").lower().replace(" ", "")
    return "gpt" in s or "chatgpt" in s or "openai" in s


def gpt_product_icon_html() -> str:
    return chatgpt_icon_html()


def utf16_len(text: str) -> int:
    return len((text or "").encode("utf-16-le")) // 2


def product_detail_gpt_entities(
    p: Dict[str, Any],
    ready_qty: int,
    *,
    fmt_price,
) -> Tuple[str, List[Any]]:
    """Fallback gửi bằng entities (nếu HTML không dùng được)."""
    if MessageEntity is None:
        return "", []

    name = (p.get("name") or "").strip()
    desc = (p.get("description") or "").strip() or "Chưa có mô tả."
    desc = desc.replace("`", "'")
    status = "✅ Còn hàng" if ready_qty > 0 else "⛔ Hết hàng"
    price = int(p.get("price") or 0)

    tag = GPT_PRODUCT_TAG_PREFIX
    ph = EMOJI_FALLBACKS.get("chatgpt", "📱")
    head = f"{tag}{ph} {name}"
    text = (
        f"{head}\n\n"
        f"💰 Giá: {fmt_price(price)}\n"
        f"📦 Còn lại: {ready_qty}\n"
        f"📝 Mô tả:\n{desc}\n"
        f"📌 Trạng thái: {status}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ Thanh toán xong hệ thống giao tự động.\n"
    )
    if ready_qty > 0:
        text += "🛒 Chọn số lượng để mua (bot sẽ tạo QR thanh toán ngay):"
    else:
        text += "💬 Sản phẩm tạm hết, vui lòng liên hệ hỗ trợ."

    entities: List[Any] = []
    emoji_id = get_emoji_id("chatgpt")
    if emoji_id:
        entities.append(
            MessageEntity(
                type=MessageEntity.CUSTOM_EMOJI,
                offset=utf16_len(tag),
                length=utf16_len(ph),
                custom_emoji_id=emoji_id,
            )
        )
    name_off = utf16_len(tag) + utf16_len(ph) + utf16_len(" ")
    if name:
        entities.append(
            MessageEntity(
                type=MessageEntity.BOLD,
                offset=name_off,
                length=utf16_len(name),
            )
        )
    return text, entities


def extract_custom_emoji_ids(message: "Message") -> List[Tuple[str, str]]:
    if message is None:
        return []

    results: List[Tuple[str, str]] = []
    seen: set[str] = set()

    pairs: Iterable[Tuple[str, Iterable]] = (
        (message.text or "", message.entities or []),
        (message.caption or "", message.caption_entities or []),
    )
    for text, entities in pairs:
        if not text or not entities:
            continue
        for ent in entities:
            if getattr(ent, "type", None) != "custom_emoji":
                continue
            emoji_id = getattr(ent, "custom_emoji_id", "") or ""
            if not emoji_id or emoji_id in seen:
                continue
            try:
                utf16 = text.encode("utf-16-le")
                snippet = utf16[ent.offset * 2 : (ent.offset + ent.length) * 2].decode(
                    "utf-16-le", errors="replace"
                )
            except Exception:
                snippet = "?"
            seen.add(emoji_id)
            results.append((snippet, emoji_id))

    return results


__all__ = [
    "EMOJI_IDS",
    "EMOJI_FALLBACKS",
    "GPT_PRODUCT_TAG_PREFIX",
    "set_emoji_id",
    "get_emoji_id",
    "tg_emoji",
    "chatgpt_icon_html",
    "strip_tg_emoji_html",
    "is_gpt_product_name",
    "gpt_product_icon_html",
    "utf16_len",
    "product_detail_gpt_entities",
    "extract_custom_emoji_ids",
]
