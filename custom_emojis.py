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

from html import escape
from typing import Iterable, List, Tuple

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
    # Example (paste the real ID once you've grabbed it via /emojiid):
    # "chatgpt":   "5368324170671202286",
    # "telegram":  "5368324170671202286",
    "chatgpt": "",
}


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
    fb = (fallback or "").strip() or "•"
    raw = (name_or_id or "").strip()
    emoji_id = raw if raw.isdigit() else get_emoji_id(raw)
    if not emoji_id:
        return escape(fb)
    return f'<tg-emoji emoji-id="{escape(emoji_id)}">{escape(fb)}</tg-emoji>'


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
    "set_emoji_id",
    "get_emoji_id",
    "tg_emoji",
    "extract_custom_emoji_ids",
]
