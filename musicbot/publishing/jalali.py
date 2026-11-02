"""تبدیل تاریخ شمسی/میلادی (الگوریتم jalaali-js، معتبر برای سال‌های ۱۱۷۸ تا ۱۶۳۳ شمسی)."""
from __future__ import annotations

from datetime import date, timedelta

_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]


def _jal_cal(jy: int) -> tuple[int, int, int]:
    """(leap, gy, march): leap==0 یعنی کبیسه؛ march روز فروردین ۱ در ماه مارس."""
    if jy < _BREAKS[0] or jy >= _BREAKS[-1]:
        raise ValueError("سال شمسی خارج از بازه")
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for jm in _BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += jump // 33 * 8 + (jump % 33) // 4
        jp = jm
    n = jy - jp
    leap_j += n // 33 * 8 + ((n % 33) + 3) // 4
    if jump % 33 == 4 and jump - n == 4:
        leap_j += 1
    leap_g = gy // 4 - (gy // 100 + 1) * 3 // 4 - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + (jump + 4) // 33 * 33
    leap = (((n + 1) % 33) - 1) % 4
    if leap == -1:
        leap = 4
    return leap, gy, march


def is_jalali_leap(jy: int) -> bool:
    return _jal_cal(jy)[0] == 0


def jalali_month_length(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if is_jalali_leap(jy) else 29


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> date:
    if not (1 <= jm <= 12) or not (1 <= jd <= jalali_month_length(jy, jm)):
        raise ValueError("تاریخ شمسی نامعتبر")
    _, gy, march = _jal_cal(jy)
    offset = (jm - 1) * 31 - (jm // 7) * (jm - 7) + jd - 1
    return date(gy, 3, march) + timedelta(days=offset)


def gregorian_to_jalali(d: date) -> tuple[int, int, int]:
    jy = d.year - 621
    _, gy, march = _jal_cal(jy)
    if d < date(gy, 3, march):
        jy -= 1
        _, gy, march = _jal_cal(jy)
    days = (d - date(gy, 3, march)).days
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    days -= 186
    return jy, 7 + days // 30, 1 + days % 30
