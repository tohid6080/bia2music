"""امتیاز داخلی «داغ‌بودن». کاملاً شفاف و جدا از شاخص رسمی هر منبع (که بدون تغییر و با برچسب منبع نشان داده می‌شود).
هیچ مقداری حدس زده نمی‌شود: تغییر رتبه بدون عکس قبلی «نامشخص» و تازگی بدون تاریخ منبع «نامشخص» است (صفر امتیاز)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

DEFAULT_WEIGHTS = (1.0, 1.0, 10.0, 1.0)     # رتبه، تغییر رتبه، چندمنبعی، تازگی
RANK_BASE = 26                              # امتیاز رتبه = (۲۶ − رتبه) × وزن؛ رتبه ۱ = ۲۵ ... رتبه ۲۵ = ۱
MOVE_MIN, MOVE_MAX = -5, 10
FRESH_7, FRESH_30 = 10.0, 5.0


@dataclass
class Weights:
    rank: float = DEFAULT_WEIGHTS[0]
    move: float = DEFAULT_WEIGHTS[1]
    multi: float = DEFAULT_WEIGHTS[2]
    fresh: float = DEFAULT_WEIGHTS[3]

    @classmethod
    def parse(cls, text: Optional[str]) -> "Weights":
        try:
            a, b, c, d = (float(x) for x in (text or "").split(","))
            return cls(a, b, c, d)
        except ValueError:
            return cls()

    def dump(self) -> str:
        return ",".join(f"{x:g}" for x in (self.rank, self.move, self.multi, self.fresh))


@dataclass
class ChartView:
    """یک نمودارِ کش‌شده برای امتیازدهی: عکس فعلی + رتبه‌های عکس قبلی همان منبع/منطقه."""

    source_id: str
    region: str
    fetched_at: str
    stale: bool
    entries: list[dict]
    prev_ranks: dict[str, int] = field(default_factory=dict)       # کلید ردیف ← رتبه‌ی قبلی


@dataclass
class Appearance:
    source_id: str
    region: str
    rank: int
    delta: Optional[int]                   # مثبت = صعود؛ None = عکس قبلی نبود (نامشخص)
    url: Optional[str]
    native_label: Optional[str]


@dataclass
class TrackScore:
    key: str
    title: str
    artist: Optional[str]
    appearances: list[Appearance]
    rank_points: float
    move_points: float
    multi_points: float
    fresh_points: float
    published_at: Optional[str]            # فقط اگر خود منبع داده باشد
    fresh_known: bool
    genre: Optional[str] = None            # فقط اگر خود منبع داده باشد

    @property
    def total(self) -> float:
        return self.rank_points + self.move_points + self.multi_points + self.fresh_points

    @property
    def sources(self) -> set[str]:
        return {a.source_id for a in self.appearances}


def entry_key(e: dict) -> str:
    """کلید تطبیق بین منابع: خواننده+عنوان نرمال‌شده (تطبیق بین منابع تقریبی است)."""
    title = e.get("title_norm") or ""
    artist = e.get("artist_norm") or ""
    return f"{artist}|{title}" if artist else title


def row_key(e: dict) -> str:
    """کلید ردیف برای مقایسه با عکس قبلی همان منبع: شناسه‌ی خود منبع اگر باشد."""
    return e.get("ext_id") or entry_key(e)


def parse_date(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    t = text.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
            return datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def score_tracks(charts: list[ChartView], weights: Weights, now: datetime) -> list[TrackScore]:
    """نمودارهای کهنه (stale) در امتیاز نمی‌آیند تا اطلاعات قدیمی «جدید» جلوه نکند."""
    groups: dict[str, dict] = {}
    for ch in charts:
        if ch.stale:
            continue
        for e in ch.entries:
            k = entry_key(e)
            if not k:
                continue
            prev = ch.prev_ranks.get(row_key(e))
            delta = (prev - e["rank"]) if prev is not None else None
            g = groups.setdefault(k, {"title": e["title"], "artist": e.get("artist"), "apps": [], "dates": [], "genre": None})
            g["genre"] = g["genre"] or e.get("genre")
            g["apps"].append(Appearance(ch.source_id, ch.region, e["rank"], delta, e.get("url"), e.get("native_label")))
            d = parse_date(e.get("published_at"))
            if d:
                g["dates"].append((d, e["published_at"]))
    out = []
    for k, g in groups.items():
        apps: list[Appearance] = g["apps"]
        rank_pts = sum(max(0, RANK_BASE - a.rank) for a in apps) * weights.rank
        move_pts = sum(max(MOVE_MIN, min(MOVE_MAX, a.delta)) for a in apps if a.delta is not None) * weights.move
        multi_pts = (len({a.source_id for a in apps}) - 1) * weights.multi
        fresh_pts, known, pub = 0.0, False, None
        if g["dates"]:
            newest = max(g["dates"], key=lambda x: x[0])
            known, pub = True, newest[1]
            age = (now - newest[0]).days
            if age <= 7:
                fresh_pts = FRESH_7 * weights.fresh
            elif age <= 30:
                fresh_pts = FRESH_30 * weights.fresh
        out.append(TrackScore(k, g["title"], g["artist"], sorted(apps, key=lambda a: a.rank), rank_pts, move_pts, multi_pts, fresh_pts, pub, known, g["genre"]))
    out.sort(key=lambda t: (-t.total, t.appearances[0].rank, t.key))
    return out


def explain(w: Weights) -> str:
    return (
        "📐 <b>روش محاسبه‌ی «امتیاز ربات»</b>\n"
        "این امتیاز <b>داخلی و تخمینی</b> است و با شاخص رسمی هر منبع (رتبه/آمار خود منبع) یکی نیست؛ آن‌ها جدا و بدون تغییر نمایش داده می‌شوند.\n\n"
        f"۱) <b>رتبه‌ی فعلی</b>: برای هر نمودار (۲۶ − رتبه) × {w.rank:g} (رتبه ۱ = ۲۵ امتیاز).\n"
        f"۲) <b>تغییر رتبه</b>: صعود نسبت به عکس قبلی <i>همان منبع و منطقه</i> (حداقل {MOVE_MIN}، حداکثر +{MOVE_MAX}) × {w.move:g}. "
        "اگر عکس قبلی نیست «نامشخص» و صفر است.\n"
        f"۳) <b>حضور در چند منبع مستقل</b>: برای هر منبع اضافه‌ی دیگر {w.multi:g} امتیاز (چند منطقه‌ی یک منبع مستقل حساب نمی‌شود). تطبیق بین منابع با نام خواننده/عنوان تقریبی است.\n"
        f"۴) <b>تازگی</b>: فقط اگر خود منبع تاریخ انتشار داده باشد: تا ۷ روز {FRESH_7:g} و تا ۳۰ روز {FRESH_30:g} (× {w.fresh:g}). وگرنه «نامشخص» و صفر.\n\n"
        "نمودارهای کهنه (به‌روز‌نشده) در امتیاز نمی‌آیند. <b>تعداد پخش کل</b> معیار نیست. هیچ رتبه، آمار یا تاریخی حدس زده نمی‌شود."
    )
