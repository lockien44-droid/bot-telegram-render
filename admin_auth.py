"""Short-lived signed admin sessions; passwords are only sent at login."""
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import OrderedDict, deque

from fastapi import HTTPException

COOKIE = "vm_admin_session"
_failures = OrderedDict()
_lock = threading.Lock()


def password():
    value = os.getenv("ADMIN_PASSWORD", "").strip()
    if not value or value == "your_admin_password":
        raise HTTPException(503, "Configure a real ADMIN_PASSWORD")
    return value


def signing_key():
    return hashlib.sha256(("admin-session:" + password()).encode()).digest()


def create_session():
    value = f"{int(time.time()) + 8 * 3600}.{secrets.token_hex(16)}"
    return value + "." + hmac.new(signing_key(), value.encode(), hashlib.sha256).hexdigest()


def valid_session(token):
    try:
        expiry, nonce, signature = token.split(".")
        value = expiry + "." + nonce
        expected = hmac.new(signing_key(), value.encode(), hashlib.sha256).hexdigest()
        return int(expiry) > time.time() and secrets.compare_digest(signature, expected)
    except (ValueError, AttributeError):
        return False


def check_login(host, candidate):
    expected = password()
    with _lock:
        now = time.monotonic()
        history = _failures.setdefault(host, deque(maxlen=6))
        _failures.move_to_end(host)
        while history and now - history[0] > 600:
            history.popleft()
        if len(history) >= 6:
            raise HTTPException(429, "Too many login attempts. Try again in 10 minutes.")
        if not secrets.compare_digest(candidate.encode(), expected.encode()):
            history.append(now)
            if len(_failures) > 10000:
                _failures.popitem(last=False)
            raise HTTPException(401, "Unauthorized")
        _failures.pop(host, None)


def require_session(request):
    if not valid_session(request.cookies.get(COOKIE, "")):
        raise HTTPException(401, "Unauthorized")
