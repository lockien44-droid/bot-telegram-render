"""Custom (premium) emoji helpers for the Telegram bot.

Telegram premium emoji are referenced by a numeric ``custom_emoji_id`` that is
unique per emoji (not per pack). The IDs are NOT public — you must extract them
from a real Telegram message that contains the emoji.

Workflow:
    1) Send (or forward) a message containing the desired premium emoji to the
       bot — for example, the ChatGPT-shaped emoji from the @ADROITPACKE pack.
    2) Reply to that message with ``/emojiid`` (admin only). The bot will print
       the ``custom_emoji_id`` for every premium emoji in the message.
    3) Paste the ID into ``EMOJI_IDS`` below under a friendly name.
    4) Anywhere in the bot, use ``tg_emoji("chatgpt", "💬")`` to render the
       emoji inside an HTML-formatted message.

Sending notes:
    * The bot must send messages with ``parse_mode="HTML"`` (or with explicit
      ``MessageEntity`` objects of type ``custom_emoji``) for the emoji to be
      rendered as the animated version.
    * The text wrapped inside ``<tg-emoji>`` must be exactly ONE regular emoji
      char — that emoji is used as the fallback for users without Premium.
    * Per Bot API 9.4 (Feb 2026): the BOT OWNER must have Telegram Premium for
      the bot to be allowed to send custom emoji. Without Premium the API will
      reject the message; the fallback emoji will not be auto-substituted.
"""

from __future__ import annotations

import os
from html import escape
from typing import Any, Dict, Iterable, List, Tuple

try:
    # Optional — only used for type hints / runtime extraction.
    from telegram import Message, MessageEntity
except Exception:  # pragma: no cover — keep module importable without PTB
    Message = None  # type: ignore[assignment]
    MessageEntity = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Registry of known custom emoji IDs.
# Fill these in by running /emojiid on a message that contains the emoji.
# ---------------------------------------------------------------------------
EMOJI_IDS: dict[str, str] = {
    # Icon ChatGPT từ pack @ADROITPACKE (custom_emoji_id từ /emojiid)
    "chatgpt": "5359726582447487916",
}

# Ký tự placeholder BẮT BUỘC khớp tin gốc (text "📱", length UTF-16 = 2, id 5359726582447487916).
EMOJI_FALLBACKS: dict[str, str] = {
    "chatgpt": (os.getenv("CUSTOM_EMOJI_CHATGPT_FALLBACK", "📱") or "📱").strip(),
}

# Emoji thường hiển thị trước icon ChatGPT (giống tin mẫu: 🏷️ + logo GPT).
GPT_PRODUCT_TAG_PREFIX = (os.getenv("GPT_PRODUCT_TAG_PREFIX", "🏷️") or "🏷️").strip()


def set_emoji_id(name: str, emoji_id: str) -> None:
    """Register a custom emoji ID at runtime (e.g. from a DB / Sheet)."""
    EMOJI_IDS[name.strip().lower()] = (emoji_id or "").strip()


def get_emoji_id(name: str) -> str:
    """Return the stored custom emoji ID for ``name`` or an empty string."""
    return EMOJI_IDS.get((name or "").strip().lower(), "")


def tg_emoji(name_or_id: str, fallback: str) -> str:
    """Return an HTML snippet that renders as a custom emoji.

    ``name_or_id`` may be either a friendly key in :data:`EMOJI_IDS` or the
    raw numeric ID. ``fallback`` MUST be exactly one regular emoji character;
    it is what non-Premium users (and clients that can't load the sticker) see.

    If no ID is configured yet, the fallback emoji is returned untouched so
    messages keep working before the registry is populated.
    """
    raw = (name_or_id or "").strip()
    emoji_id = raw if raw.isdigit() else get_emoji_id(raw)
    if not emoji_id:
        fb = (fallback or "").strip() or "•"
        return escape(fb)
    fb = (fallback or EMOJI_FALLBACKS.get(raw.lower(), "") or "").strip() or "📱"
    return f'<tg-emoji emoji-id="{escape(emoji_id)}">{escape(fb)}</tg-emoji>'


def is_gpt_product_name(name: str) -> bool:
    s = (name or "").lower().replace(" ", "")
    return "gpt" in s or "chatgpt" in s or "openai" in s


def gpt_product_icon_html() -> str:
    """Tiền tố tiêu đề sản phẩm GPT: 🏷️ + icon ChatGPT (custom emoji)."""
    if not get_emoji_id("chatgpt"):
        return "📱 "
    tag = GPT_PRODUCT_TAG_PREFIX
    gpt = tg_emoji("chatgpt", EMOJI_FALLBACKS.get("chatgpt", "📱"))
    return f"{tag}{gpt} "


def utf16_len(text: str) -> int:
    """Độ dài chuỗi theo UTF-16 (Telegram entity offset/length)."""
    return len((text or "").encode("utf-16-le")) // 2


def product_detail_gpt_entities(
    p: Dict[str, Any],
    ready_qty: int,
    *,
    fmt_price,
) -> Tuple[str, List[Any]]:
    """Tin chi tiết GPT gửi bằng ``entities`` (không parse_mode) — chuẩn Bot API.

    Placeholder custom emoji: ``📱`` (offset 0, length 2) như webhook mẫu.
    """
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
    """Return ``[(fallback_char, custom_emoji_id), ...]`` for every premium
    emoji entity in ``message`` (text + caption + entities + caption_entities).
    Preserves order; deduplicates by ``custom_emoji_id``.
    """
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
                # ent.offset / ent.length are in UTF-16 code units.
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
    "is_gpt_product_name",
    "gpt_product_icon_html",
    "utf16_len",
    "product_detail_gpt_entities",
    "extract_custom_emoji_ids",
]
