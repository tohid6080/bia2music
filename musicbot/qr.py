"""ساخت QR کد PNG با کتابخانه‌ی اختیاری segno (پایتون خالص). اگر نصب نباشد None برمی‌گرداند."""
from __future__ import annotations

import io
from typing import Optional


def make_qr_png(text: str, scale: int = 12) -> Optional[bytes]:
    try:
        import segno
    except ImportError:
        return None
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=4)
    return buf.getvalue()
