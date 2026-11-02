"""اعتبارسنجی امن initData مینی‌اپ تلگرام (سمت سرور). هیچ‌چیز از ورودی لاگ نمی‌شود.

الگوریتم رسمی: secret = HMAC_SHA256(key="WebAppData", msg=bot_token)؛ hash = HMAC_SHA256(secret, data_check_string)
که data_check_string همه‌ی فیلدها به‌جز hash است، مرتب‌شده و به شکل key=value با \\n.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl

MAX_LEN = 8192
CLOCK_SKEW = 60


class InitDataError(Exception):
    """code فقط یک برچسب کوتاه است؛ هرگز بخشی از ورودی در پیام نمی‌آید."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: Optional[str]
    username: Optional[str]
    language_code: Optional[str]
    is_bot: bool
    auth_date: int


def secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def _check_string(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{k}={v}" for k, v in sorted(pairs))


def sign(fields: dict[str, str], bot_token: str) -> str:
    """ساخت initData معتبر (برای تست و ابزار توسعه؛ نیازمند توکن واقعی)."""
    from urllib.parse import urlencode

    h = hmac.new(secret_key(bot_token), _check_string(list(fields.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int, now: Optional[float] = None) -> TelegramUser:
    if not isinstance(init_data, str) or not init_data or len(init_data) > MAX_LEN:
        raise InitDataError("malformed")
    if not bot_token:
        raise InitDataError("server_misconfigured")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=40)
    except ValueError:
        raise InitDataError("malformed") from None
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise InitDataError("malformed")                      # فیلد تکراری ← ابهام و حمله‌ی احتمالی
    received = dict(pairs)
    got = received.pop("hash", None)
    if not got:
        raise InitDataError("missing_hash")
    rest = [(k, v) for k, v in pairs if k != "hash"]
    expected = hmac.new(secret_key(bot_token), _check_string(rest).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, got.lower()):
        raise InitDataError("bad_signature")
    try:
        auth_date = int(received.get("auth_date", ""))
    except ValueError:
        raise InitDataError("bad_auth_date") from None
    t = time.time() if now is None else now
    if auth_date > t + CLOCK_SKEW:
        raise InitDataError("auth_date_in_future")
    if t - auth_date > max_age_seconds:
        raise InitDataError("expired")
    try:
        u = json.loads(received.get("user", ""))
        uid = u["id"]
    except (ValueError, KeyError, TypeError):
        raise InitDataError("no_user") from None
    if not isinstance(u, dict) or not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
        raise InitDataError("no_user")
    s = lambda k: (u.get(k) if isinstance(u.get(k), str) else None)  # noqa: E731
    return TelegramUser(uid, (s("first_name") or "")[:128], (s("last_name") or None), (s("username") or None), s("language_code"),
                        bool(u.get("is_bot")), auth_date)
