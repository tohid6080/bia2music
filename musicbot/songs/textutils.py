"""نرمال‌سازی متن فارسی برای جست‌وجو و تشخیص مشابه، و پاکسازی نام آهنگ/خواننده."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

_CHARS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "آ": "ا", "ؤ": "و"})
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MARKS = re.compile("[ً-ٰٟـ]")
_URL = re.compile(r"(https?://\S+|t\.me/\S+|www\.\S+)", re.IGNORECASE)
_MENTION = re.compile(r"@\w+")
AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".wma")


def ascii_digits(text: Optional[str]) -> str:
    """ارقام فارسی/عربی ← لاتین؛ بقیه نویسه‌ها دست‌نخورده (برای تاریخ و ساعت)."""
    return (text or "").translate(_DIGITS)


def normalize(text: Optional[str]) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_CHARS).translate(_DIGITS)
    t = _MARKS.sub("", t)
    t = t.replace("‌", " ").replace("‏", "").replace("‎", "")
    t = re.sub(r"[^\w\s]|_", " ", t)
    return re.sub(r"\s+", " ", t).strip().casefold()


def clean_text(text: Optional[str], limit: int = 120) -> Optional[str]:
    """حذف لینک و @آیدی تبلیغاتی از برچسب فایل؛ None اگر چیزی نماند."""
    if not text:
        return None
    t = _MENTION.sub(" ", _URL.sub(" ", text))
    t = re.sub(r"\s+", " ", t).strip(" -_.|")
    return t[:limit] or None


def parse_filename(name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """«Artist - Title.mp3» ← (artist, title). اگر الگو نبود فقط عنوان برمی‌گردد."""
    if not name:
        return None, None
    stem = name
    if stem.lower().endswith(AUDIO_EXTS):
        stem = stem.rsplit(".", 1)[0]
    stem = stem.replace("_", " ")
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return clean_text(artist), clean_text(title)
    return None, clean_text(stem)
