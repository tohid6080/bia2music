"""پیشنهادهای رادار: ساخت فهرست یکتا از نمودارها و ثبت دستی، تفکیک ایرانی/خارجی (تقریبی)، فیلترها، گروه‌ها، حذف تکراری‌های آرشیو،
و تبدیل پیشنهاد به آهنگِ بدون‌فایل در آرشیو/پیش‌نویس. هیچ فایلی دانلود یا منتشر نمی‌شود و هیچ مقداری حدس زده نمی‌شود."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from musicbot.radar.scoring import TrackScore, parse_date
from musicbot.radar.sources import BY_ID
from musicbot.songs.textutils import normalize

NEW_DAYS = 14
FAST_MIN_DELTA = 3
_FA = re.compile(r"[؀-ۿ]")
_TR = re.compile(r"[ğĞşŞıİ]")
DEFAULT_FILTERS = {"kind": "all", "country": "all", "genre": "all", "lang": "all", "window": "all", "fresh": "all", "pop": "all", "growth": "all"}
FILTER_LABELS = {"kind": "نوع", "country": "کشور نمودار", "genre": "سبک", "lang": "زبان (تقریبی)", "window": "بازه‌ی انتشار", "fresh": "تازه/ترند",
                 "pop": "محبوبیت", "growth": "رشد"}
VALUE_FA = {
    "kind": {"all": "همه", "iran": "ایرانی", "foreign": "خارجی"},
    "lang": {"all": "همه", "fa": "فارسی", "tr": "ترکی", "latin": "لاتین/سایر"},
    "window": {"all": "همه", "7": "۷ روز اخیر", "30": "۳۰ روز اخیر"},
    "fresh": {"all": "همه", "new": "فقط تازه‌منتشرشده"},
    "pop": {"all": "همه", "30": "امتیاز ≥ ۳۰", "60": "امتیاز ≥ ۶۰"},
    "growth": {"all": "همه", "up": "فقط در حال صعود"},
}
CYCLES = {"kind": ["all", "iran", "foreign"], "lang": ["all", "fa", "tr", "latin"], "window": ["all", "7", "30"], "fresh": ["all", "new"],
          "pop": ["all", "30", "60"], "growth": ["all", "up"]}
STATUS_ICON = {"new": "", "saved": "⭐", "in_archive": "📚", "drafted": "✅", "rejected": "🚫"}
STATUS_FA = {"new": "جدید", "saved": "ذخیره‌شده", "in_archive": "در آرشیو", "drafted": "پیش‌نویس انتشار", "rejected": "ردشده"}


def looks_persian(*texts: Optional[str]) -> bool:
    return any(t and _FA.search(t) for t in texts)


def guess_language(title: str, artist: Optional[str]) -> str:
    """تقریبی (بر اساس خط نوشتار): fa | tr | latin. منبع‌ها زبان نمی‌دهند."""
    t = f"{title} {artist or ''}"
    if _FA.search(t):
        return "fa"
    return "tr" if _TR.search(t) else "latin"


def item_key(artist: Optional[str], title: str) -> str:
    a, t = normalize(artist), normalize(title)
    return f"{a}|{t}" if a else t


@dataclass
class Item:
    key: str
    title: str
    artist: Optional[str]
    kind: str
    ts: Optional[TrackScore] = None
    manual: Optional[dict] = None
    sug: Optional[dict] = None
    in_archive: Optional[int] = None
    genre: Optional[str] = None
    published_at: Optional[str] = None
    max_delta: Optional[int] = None
    countries: set = field(default_factory=set)

    @property
    def score(self) -> float:
        return self.ts.total if self.ts else 0.0

    @property
    def status(self) -> str:
        return (self.sug or {}).get("status", "new")


def load_filters(ctx) -> dict:
    try:
        raw = json.loads(ctx.repos.settings.get("radar_filters") or "{}")
    except ValueError:
        raw = {}
    f = dict(DEFAULT_FILTERS)
    f.update({k: str(v) for k, v in raw.items() if k in DEFAULT_FILTERS})
    return f


def save_filters(ctx, f: dict) -> None:
    ctx.repos.settings.set("radar_filters", json.dumps({k: v for k, v in f.items() if k in DEFAULT_FILTERS and v != "all"}, ensure_ascii=False))


def active_filters_text(f: dict) -> str:
    parts = [f"{FILTER_LABELS[k]}: {VALUE_FA.get(k, {}).get(v, v)}" for k, v in f.items() if v != "all"]
    return " · ".join(parts)


def build_items(ctx, *, sync: bool = True) -> list[Item]:
    """همه‌ی آهنگ‌های نمودارها (غیرکهنه) + ثبت دستی، یکتا؛ با وضعیت ذخیره‌شده‌ی هر پیشنهاد."""
    svc = ctx.radar_service()
    repo = ctx.repos.radar
    items: dict[str, Item] = {}
    for ts in svc.ranked():
        a = ts.appearances
        it = Item(ts.key, ts.title, ts.artist, "iran" if looks_persian(ts.title, ts.artist) else "foreign", ts=ts, genre=ts.genre,
                  published_at=ts.published_at, max_delta=max((x.delta for x in a if x.delta is not None), default=None),
                  countries={x.region.lower() for x in a})
        items[ts.key] = it
    for m in repo.manual_list(500):
        key = item_key(m["artist"], m["title"])
        if key and key not in items:
            items[key] = Item(key, m["title"], m["artist"], "iran" if looks_persian(m["title"], m["artist"]) else "foreign", manual=m)
    out = list(items.values())
    if sync:
        for it in out:
            best = min(it.ts.appearances, key=lambda x: x.rank) if it.ts else None
            official = bool(best and best.url)
            it.sug = repo.upsert_suggestion(
                it.key, it.title, it.artist, it.kind, best.source_id if best else "manual", best.region if best else None,
                best.rank if best else None, (best.url if best else (it.manual or {}).get("url")),
                best.native_label if best else (it.manual or {}).get("source_note"), it.published_at, it.genre,
                "official_link" if official else "unknown")
            it.kind = it.sug["kind"]                      # انتخاب دستی مدیر محترم شمرده می‌شود
    else:                                                  # بدون همگام‌سازی هم وضعیت ذخیره‌شده (ردشده/ذخیره…) باید دیده شود
        for it in out:
            it.sug = repo.get_suggestion_by_key(it.key)
            if it.sug:
                it.kind = it.sug["kind"]
    for it in out:
        row = ctx.repos.songs.find_by_norm(normalize(it.title), normalize(it.artist))
        it.in_archive = row["id"] if row else None            # تکراری آرشیو: از فهرست‌های کشف حذف می‌شود
    return out


def is_new(it: Item, now: datetime, days: int = NEW_DAYS) -> bool:
    d = parse_date(it.published_at)
    return bool(d and 0 <= (now - d).days <= days)


def discoverable(items: list[Item]) -> list[Item]:
    """حذف ردشده‌ها و آنچه در آرشیو هست (پیشنهاد تکراری ندهد)."""
    return [i for i in items if i.status != "rejected" and not i.in_archive and i.status not in ("in_archive",)]


def apply_filters(items: list[Item], f: dict, now: datetime) -> list[Item]:
    out = []
    for it in items:
        if f["kind"] != "all" and it.kind != f["kind"]:
            continue
        if f["country"] != "all" and f["country"].lower() not in it.countries:
            continue
        if f["genre"] != "all" and (it.genre or "") != f["genre"]:
            continue
        if f["lang"] != "all" and guess_language(it.title, it.artist) != f["lang"]:
            continue
        if f["window"] != "all":
            d = parse_date(it.published_at)
            if not d or (now - d).days > int(f["window"]):        # تاریخ نامشخص ← کنار گذاشته می‌شود
                continue
        if f["fresh"] == "new" and not is_new(it, now):
            continue
        if f["pop"] != "all" and (not it.ts or it.score < float(f["pop"])):
            continue
        if f["growth"] == "up" and not (it.max_delta and it.max_delta >= 1):
            continue
        out.append(it)
    return out


def group_items(group: str, items: list[Item], now: datetime) -> list[Item]:
    ranked = sorted([i for i in items if i.ts], key=lambda i: (-i.score, i.key))
    manual = [i for i in items if not i.ts]
    if group == "top":
        return ranked
    if group in ("ir", "fo"):
        kind = "iran" if group == "ir" else "foreign"
        return [i for i in ranked if i.kind == kind] + [i for i in manual if i.kind == kind]
    if group == "new":
        return sorted([i for i in ranked if is_new(i, now)], key=lambda i: (parse_date(i.published_at), i.score), reverse=True)
    if group == "grow":
        return sorted([i for i in ranked if i.max_delta is not None and i.max_delta >= FAST_MIN_DELTA], key=lambda i: (-i.max_delta, -i.score))
    return ranked


def available_options(ctx, items: list[Item]) -> dict:
    countries = sorted({c for i in items for c in i.countries})
    genres = sorted({i.genre for i in items if i.genre})
    return {"country": ["all"] + countries, "genre": ["all"] + genres}


def top_artists(items: list[Item], n: int = 10) -> list[dict]:
    agg: dict[str, dict] = {}
    for i in items:
        if not i.ts or not i.artist:
            continue
        a = agg.setdefault(normalize(i.artist), {"artist": i.artist, "points": 0.0, "tracks": 0, "sources": set()})
        a["points"] += i.ts.rank_points
        a["tracks"] += 1
        a["sources"] |= i.ts.sources
    return sorted(agg.values(), key=lambda a: (-a["points"], a["artist"]))[:n]


# ---------- تبدیل پیشنهاد به آهنگ (بدون فایل) ----------
def ensure_song(ctx, sug: dict, admin_id: int) -> tuple[int, str]:
    """(song_id, how) how: existing_link | linked | created. فایل ندارد؛ فقط عنوان/خواننده (و زبان فارسی اگر خط فارسی باشد)."""
    songs = ctx.repos.songs
    if sug.get("song_id") and songs.get(sug["song_id"]):
        return sug["song_id"], "linked"
    row = songs.find_by_norm(normalize(sug["title"]), normalize(sug.get("artist")))
    if row:
        ctx.repos.radar.set_suggestion(sug["id"], song_id=row["id"])
        return row["id"], "existing_link"
    sid = songs.create(title=sug["title"], artist=sug.get("artist"), created_by=admin_id)
    if looks_persian(sug["title"], sug.get("artist")):
        songs.update(sid, language_code="fa")
    ctx.repos.radar.set_suggestion(sug["id"], song_id=sid)
    ctx.repos.logs.add("radar_song_created", admin_id, f"sug={sug['id']} song={sid}")
    return sid, "created"
