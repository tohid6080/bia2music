"""ورودی/نمایش زمان برای زمان‌بندی. ذخیره در دیتابیس همیشه UTC است؛ نمایش با TIMEZONE و تاریخ شمسی."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from musicbot.publishing.jalali import gregorian_to_jalali, jalali_to_gregorian
from musicbot.songs.textutils import ascii_digits

ISO = "%Y-%m-%dT%H:%M:%SZ"
MIN_LEAD = timedelta(minutes=2)
_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATETIME = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})$")

QUICK = {
    "h1": "⏱ ۱ ساعت دیگر",
    "h3": "⏱ ۳ ساعت دیگر",
    "t21": "🌙 امشب ۲۱:۰۰",
    "m10": "🌅 فردا ۱۰:۰۰",
    "m21": "🌙 فردا ۲۱:۰۰",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(ISO)


def from_iso(s: str) -> datetime:
    return datetime.strptime(s, ISO).replace(tzinfo=timezone.utc)


def quick_time(code: str, now: datetime, tz: ZoneInfo) -> datetime:
    local = now.astimezone(tz)
    if code == "h1":
        return (local + timedelta(hours=1)).replace(second=0, microsecond=0)
    if code == "h3":
        return (local + timedelta(hours=3)).replace(second=0, microsecond=0)
    at = lambda day, h: local.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(days=day)  # noqa: E731
    if code == "t21":
        target = at(0, 21)
        return target if target - local >= MIN_LEAD else at(1, 21)
    if code == "m10":
        return at(1, 10)
    if code == "m21":
        return at(1, 21)
    raise ValueError("کد زمان نامعتبر")


def parse_user_datetime(text: str, now: datetime, tz: ZoneInfo) -> datetime:
    """«21:30» ، «1405/08/20 21:30» (شمسی) یا «2026-11-10 21:30» (میلادی). ValueError با پیام فارسی."""
    t = re.sub(r"\s+", " ", ascii_digits(text).replace("٫", ":").replace("：", ":")).strip()
    local_now = now.astimezone(tz)
    m = _TIME.match(t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            raise ValueError("ساعت نامعتبر است.")
        target = local_now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if target - local_now < MIN_LEAD:
            target += timedelta(days=1)
    else:
        m = _DATETIME.match(t)
        if not m:
            raise ValueError("قالب زمان نامعتبر است. مثال: 21:30 یا 1405/08/20 21:30")
        y, mo, d, h, mi = (int(x) for x in m.groups())
        if h > 23 or mi > 59:
            raise ValueError("ساعت نامعتبر است.")
        try:
            day = jalali_to_gregorian(y, mo, d) if y < 1700 else datetime(y, mo, d).date()
        except ValueError:
            raise ValueError("تاریخ نامعتبر است.") from None
        target = datetime(day.year, day.month, day.day, h, mi, tzinfo=tz)
    if target.astimezone(timezone.utc) - now < MIN_LEAD:
        raise ValueError("زمان باید حداقل چند دقیقه بعد از اکنون باشد.")
    return target


def format_local(iso_utc: str, tz: ZoneInfo) -> str:
    """مثل «1405/08/12 21:00»."""
    local = from_iso(iso_utc).astimezone(tz)
    jy, jm, jd = gregorian_to_jalali(local.date())
    return f"{jy}/{jm:02d}/{jd:02d} {local:%H:%M}"
