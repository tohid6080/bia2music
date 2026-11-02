"""نشست API: JWT امضاشده (HS256) با انقضا. فقط شناسه‌ی داخلی کاربر درون آن است."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import jwt

from b2m.core.timeutil import utcnow

ISS = "bia2music"


def issue(user_id: int, secret: str, ttl_minutes: int) -> tuple[str, int]:
    now = utcnow()
    exp = now + timedelta(minutes=ttl_minutes)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": exp, "iss": ISS}, secret, algorithm="HS256"), ttl_minutes * 60


def verify(token: str, secret: str) -> Optional[int]:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"], issuer=ISS, options={"require": ["exp", "iat", "sub", "iss"]})
        return int(data["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None
