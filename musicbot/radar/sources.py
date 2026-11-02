"""تعریف منابع رادار و تجزیه‌گرهای پاسخ. اصول: هیچ منبعی بدون تأیید صریح مدیر فعال نمی‌شود؛ منبعی که API رسمی/عمومی
مطمئن ندارد «فقط لینک» است (اسکرپ نمی‌شود)؛ تجزیه‌گرها دفاعی‌اند و هیچ مقدار (رتبه، تاریخ، آمار) را حدس نمی‌زنند."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class ChartSource:
    id: str
    name: str
    kind: str                              # iran | foreign
    mode: str                              # api | link
    home_url: str
    terms_url: str
    note: str                              # توضیح روش/محدودیت
    key_attr: Optional[str] = None         # نام فیلد کلید در Settings (اگر لازم باشد)
    key_env: Optional[str] = None          # نام متغیر محیطی برای راهنما
    default_regions: tuple[str, ...] = ()
    region_help: str = ""
    ttl_s: int = 6 * 3600
    min_interval_s: int = 120
    pause_s: float = 0.0                   # مکث بین درخواست‌های مناطق
    verified_live: bool = False            # با داده‌ی واقعی در این پروژه آزموده شده؟
    terms_verified: bool = False           # شرایط استفاده توسط من خوانده شده؟
    links: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def is_api(self) -> bool:
        return self.mode == "api"


SOURCES: tuple[ChartSource, ...] = (
    ChartSource(
        id="youtube_trending", name="YouTube Trending Music", kind="foreign", mode="api",
        home_url="https://www.youtube.com/feed/trending?bp=4gINGgt5dG1hX2NoYXJ0cw%3D%3D",
        terms_url="https://developers.google.com/youtube/terms/api-services-terms-of-service",
        note="API رسمی YouTube Data v3 (videos.list با chart=mostPopular و دسته‌ی موسیقی). نیاز به کلید رایگان گوگل. "
             "هر درخواست ۱ واحد از سهمیه‌ی روزانه‌ی ۱۰٬۰۰۰ واحد. ممکن است برای برخی کشورها (مثلاً IR) داده ندهد.",
        key_attr="youtube_api_key", key_env="YOUTUBE_API_KEY", default_regions=("US", "GB", "TR"),
        region_help="کد دوحرفی کشور، مثل US,GB,TR,DE", ttl_s=6 * 3600, min_interval_s=120),
    ChartSource(
        id="lastfm_geo", name="Last.fm Top Tracks", kind="foreign", mode="api",
        home_url="https://www.last.fm/charts", terms_url="https://www.last.fm/api/tos",
        note="API رسمی Last.fm (geo.getTopTracks برای کشور، chart.getTopTracks برای جهانی). نیاز به کلید رایگان. "
             "داده‌ی برخی کشورها (مثلاً Iran) ممکن است کم باشد. شرایط استفاده را قبل از تأیید بخوانید.",
        key_attr="lastfm_api_key", key_env="LASTFM_API_KEY", default_regions=("GLOBAL", "Iran", "Turkey", "United States"),
        region_help="نام انگلیسی کشور (مثل Iran,Turkey) یا GLOBAL برای جهانی", ttl_s=6 * 3600, min_interval_s=120, pause_s=1.0, terms_verified=False),
    ChartSource(
        id="deezer_chart", name="Deezer Chart", kind="foreign", mode="api",
        home_url="https://www.deezer.com/en/channels/charts", terms_url="https://developers.deezer.com/",
        note="API عمومی Deezer (chart/0/tracks) بدون کلید. شرایط استفاده را من نخوانده‌ام؛ قبل از تأیید در صفحه‌ی توسعه‌دهندگان بخوانید.",
        default_regions=("GLOBAL",), region_help="فقط GLOBAL", ttl_s=6 * 3600, min_interval_s=120),
    ChartSource(
        id="apple_most_played", name="Apple Music Most Played", kind="foreign", mode="api",
        home_url="https://rss.marketingtools.apple.com/", terms_url="https://rss.marketingtools.apple.com/",
        note="فید رسمی Apple Marketing Tools (most-played/songs) بدون کلید؛ شامل تاریخ انتشار از طرف خود Apple. "
             "آدرس دقیق songs و شرایط را من تأیید نکرده‌ام؛ ابتدا «🧪 آزمایش» بزنید.",
        default_regions=("us", "gb", "tr"), region_help="کد دوحرفی کوچک کشور، مثل us,gb,tr", ttl_s=12 * 3600, min_interval_s=300),
    # ----- فقط لینک: API رسمی/عمومی مطمئن ندارد؛ هیچ داده‌ای خودکار گرفته نمی‌شود -----
    ChartSource(
        id="farsichart", name="FarsiChart", kind="iran", mode="link",
        home_url="https://farsichart.com", terms_url="https://farsichart.com",
        note="نمودار موسیقی فارسی. شرایط و robots آن را بررسی نکرده‌ام؛ فعلاً فقط لینک. با «🧪 بررسی robots.txt» خودتان ببینید و "
             "آهنگ‌های دلخواه را دستی ثبت کنید.",
        links=(("Trending", "https://farsichart.com/music/trending"),)),
    ChartSource(
        id="radiojavan", name="Radio Javan", kind="iran", mode="link", home_url="https://www.radiojavan.com",
        terms_url="https://www.radiojavan.com", note="API عمومی رسمی نمی‌شناسم؛ فقط لینک و ثبت دستی."),
    ChartSource(
        id="youtube_charts", name="YouTube Music Charts / Shorts", kind="foreign", mode="link", home_url="https://charts.youtube.com",
        terms_url="https://charts.youtube.com", note="نمودارهای رسمی YouTube Music و Shorts API رسمی ندارند؛ فقط لینک (اسکرپ نمی‌شود)."),
    ChartSource(
        id="spotify_charts", name="Spotify Charts", kind="foreign", mode="link", home_url="https://charts.spotify.com",
        terms_url="https://charts.spotify.com", note="نمودارهای Spotify نیازمند ورود است و API عمومی رایگان ندارد؛ فقط لینک."),
    ChartSource(
        id="shazam_charts", name="Shazam Charts", kind="foreign", mode="link", home_url="https://www.shazam.com/charts",
        terms_url="https://www.shazam.com/charts", note="API عمومی رایگان رسمی ندارد؛ فقط لینک."),
)
BY_ID = {s.id: s for s in SOURCES}
API_HOSTS = frozenset({"www.googleapis.com", "ws.audioscrobbler.com", "api.deezer.com", "rss.applemarketingtools.com"})


# ---------- ابزارهای تجزیه ----------
def _s(x: Any, limit: int = 200) -> Optional[str]:
    if x is None or isinstance(x, (dict, list)):
        return None
    t = re.sub(r"\s+", " ", str(x)).strip()
    return t[:limit] or None


def _int(x: Any) -> Optional[int]:
    try:
        return int(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _url(x: Any) -> Optional[str]:
    u = _s(x, 500)
    return u if u and re.match(r"^https?://\S+$", u, re.I) else None


def _list(x: Any) -> list:
    if isinstance(x, list):
        return x
    return [x] if isinstance(x, dict) else []


_DECOR = re.compile(r"\s*[\(\[][^\)\]]*(official|video|audio|lyric|clip|mv)[^\)\]]*[\)\]]\s*$", re.I)


def parse_youtube(data: Any) -> list[dict]:
    out = []
    for i, item in enumerate(_list(data.get("items") if isinstance(data, dict) else None)):
        if not isinstance(item, dict):
            continue
        vid = item.get("id")
        vid = _s(vid.get("videoId")) if isinstance(vid, dict) else _s(vid)
        sn = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        title, channel = _s(sn.get("title")), _s(sn.get("channelTitle"))
        if not vid or not title:
            continue
        artist = re.sub(r"\s*-\s*Topic$", "", channel or "") or None
        if " - " in title:                                   # «Artist - Song (Official)» رایج است؛ فقط وقتی الگو واضح است
            left, right = title.split(" - ", 1)
            if left.strip() and right.strip():
                artist, title = left.strip(), right.strip()
        title = _DECOR.sub("", title).strip() or title
        views = _int((item.get("statistics") or {}).get("viewCount")) if isinstance(item.get("statistics"), dict) else None
        out.append({"rank": i + 1, "ext_id": vid, "title": title, "artist": artist, "url": f"https://www.youtube.com/watch?v={vid}",
                    "native_label": f"{views:,} بازدید" if views is not None else None, "native_score": float(views) if views is not None else None,
                    "published_at": _s(sn.get("publishedAt"))})
    return out


def parse_lastfm(data: Any) -> list[dict]:
    root = data if isinstance(data, dict) else {}
    box = root.get("tracks") or root.get("toptracks") or {}
    out = []
    for i, t in enumerate(_list(box.get("track") if isinstance(box, dict) else None)):
        if not isinstance(t, dict):
            continue
        name = _s(t.get("name"))
        artist = t.get("artist")
        artist = _s(artist.get("name")) if isinstance(artist, dict) else _s(artist)
        if not name:
            continue
        attr = t.get("@attr") if isinstance(t.get("@attr"), dict) else {}
        rank = _int(attr.get("rank")) or i + 1
        listeners, plays = _int(t.get("listeners")), _int(t.get("playcount"))
        label = f"{listeners:,} شنونده" if listeners is not None else (f"{plays:,} پخش" if plays is not None else None)
        out.append({"rank": rank, "ext_id": _url(t.get("url")), "title": name, "artist": artist, "url": _url(t.get("url")),
                    "native_label": label, "native_score": float(listeners if listeners is not None else plays) if (listeners is not None or plays is not None) else None})
    return out


def parse_deezer(data: Any) -> list[dict]:
    out = []
    for i, t in enumerate(_list(data.get("data") if isinstance(data, dict) else None)):
        if not isinstance(t, dict):
            continue
        title = _s(t.get("title"))
        artist = t.get("artist")
        artist = _s(artist.get("name")) if isinstance(artist, dict) else None
        if not title:
            continue
        pop = _int(t.get("rank"))
        out.append({"rank": _int(t.get("position")) or i + 1, "ext_id": _s(t.get("id")), "title": title, "artist": artist,
                    "url": _url(t.get("link")), "native_score": float(pop) if pop is not None else None,
                    "native_label": f"شاخص محبوبیت Deezer: {pop:,}" if pop is not None else None})
    return out


def parse_apple(data: Any) -> list[dict]:
    feed = data.get("feed") if isinstance(data, dict) else None
    out = []
    for i, t in enumerate(_list(feed.get("results") if isinstance(feed, dict) else None)):
        if not isinstance(t, dict):
            continue
        name = _s(t.get("name"))
        if not name:
            continue
        genres = [g.get("name") for g in _list(t.get("genres")) if isinstance(g, dict) and g.get("name")]
        out.append({"rank": i + 1, "ext_id": _s(t.get("id")), "title": name, "artist": _s(t.get("artistName")), "url": _url(t.get("url")),
                    "published_at": _s(t.get("releaseDate")), "genre": _s(genres[0]) if genres else None})
    return out
