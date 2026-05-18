import os
import re
from datetime import datetime
from html import unescape
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests


GRAPH_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"

DEFAULT_GRAPH_SCOPE = "https://graph.microsoft.com/Mail.Read offline_access"
DISPLAY_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class MailReaderError(RuntimeError):
    pass


def parse_mail_account(raw: str) -> Dict[str, str]:
    """
    Supports common shop formats:
    - email|refresh_token|client_id
    - email|password|refresh_token|client_id
    - email----refresh_token----client_id

    If client_id is missing, MS_GRAPH_CLIENT_ID / MAIL_GRAPH_CLIENT_ID is used.
    """
    text = (raw or "").strip()
    if not text:
        raise MailReaderError("Thiếu chuỗi mail.")

    sep = "|" if "|" in text else "----"
    parts = [re.sub(r"\s+", "", p.strip()) for p in text.split(sep) if p.strip()]
    if len(parts) < 2:
        raise MailReaderError("Sai định dạng. Cần dạng email|refresh_token|client_id.")

    email = parts[0]
    if "@" not in email:
        raise MailReaderError("Không nhận ra email ở đầu chuỗi.")

    client_id = os.getenv("MS_GRAPH_CLIENT_ID", "").strip() or os.getenv("MAIL_GRAPH_CLIENT_ID", "").strip()

    if len(parts) >= 4:
        refresh_token = parts[-2]
        client_id = parts[-1]
    elif len(parts) == 3:
        refresh_token = parts[1]
        client_id = parts[2]
    else:
        refresh_token = parts[1]

    if not refresh_token:
        raise MailReaderError("Thiếu refresh_token.")
    if not client_id:
        raise MailReaderError("Thiếu client_id. Dùng email|refresh_token|client_id hoặc set MS_GRAPH_CLIENT_ID.")

    return {
        "email": email,
        "refresh_token": refresh_token,
        "client_id": client_id,
    }


def get_graph_access_token(refresh_token: str, client_id: str) -> str:
    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": DEFAULT_GRAPH_SCOPE,
    }
    try:
        resp = requests.post(GRAPH_TOKEN_URL, data=data, timeout=20)
    except requests.RequestException as e:
        raise MailReaderError(f"Lỗi kết nối Microsoft OAuth: {e}") from e

    if resp.status_code >= 400:
        detail = _short_error(resp)
        raise MailReaderError(f"Không lấy được access_token ({resp.status_code}): {detail}")

    token = resp.json().get("access_token")
    if not token:
        raise MailReaderError("Microsoft không trả access_token.")
    return token


def read_inbox_messages(raw_account: str, limit: int = 5) -> Dict[str, Any]:
    account = parse_mail_account(raw_account)
    token = get_graph_access_token(account["refresh_token"], account["client_id"])

    params = {
        "$top": max(1, min(int(limit or 5), 10)),
        "$orderby": "receivedDateTime desc",
        "$select": "subject,from,receivedDateTime,bodyPreview,body",
    }
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.get(GRAPH_MESSAGES_URL, headers=headers, params=params, timeout=20)
    except requests.RequestException as e:
        raise MailReaderError(f"Lỗi kết nối Microsoft Graph: {e}") from e

    if resp.status_code >= 400:
        detail = _short_error(resp)
        raise MailReaderError(f"Không đọc được inbox ({resp.status_code}): {detail}")

    messages = [_normalize_message(m) for m in resp.json().get("value", [])]
    return {"email": account["email"], "messages": messages}


def extract_codes(text: str) -> List[str]:
    found = re.findall(r"(?<!\d)(\d{4,8})(?!\d)", text or "")
    out: List[str] = []
    for code in found:
        if code not in out:
            out.append(code)
    return out[:5]


def _normalize_message(msg: Dict[str, Any]) -> Dict[str, str]:
    sender = (((msg.get("from") or {}).get("emailAddress") or {}).get("address") or "").strip()
    sender_name = (((msg.get("from") or {}).get("emailAddress") or {}).get("name") or "").strip()
    subject = (msg.get("subject") or "(no subject)").strip()
    preview = (msg.get("bodyPreview") or "").strip()
    body_text = _plain_body((((msg.get("body") or {}).get("content")) or "").strip())
    received = _format_time(msg.get("receivedDateTime") or "")
    codes = extract_codes(f"{subject}\n{preview}\n{body_text}")
    return {
        "from": sender or sender_name or "(unknown)",
        "time": received,
        "subject": subject,
        "preview": preview,
        "body": body_text,
        "codes": ", ".join(codes),
    }


def _plain_body(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return " ".join(text.split())


def _format_time(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(DISPLAY_TZ).strftime("%H:%M %d/%m/%Y GMT+7")
    except Exception:
        return value


def _short_error(resp: requests.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error") or {}
        if isinstance(err, dict):
            return (err.get("message") or err.get("code") or str(data))[:500]
        return str(data)[:500]
    except Exception:
        return resp.text[:500]
