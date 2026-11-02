"""سرویس دریافت داده‌ی رادار: فقط منابع API تأییدشده توسط مدیر، با کش (TTL)، حداقل فاصله‌ی درخواست، سقف روزانه و جداسازی خطا.
هیچ فایل صوتی دانلود نمی‌شود و فقط به میزبان‌های فهرست‌شده درخواست می‌رود."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from musicbot.config import Settings
from musicbot.db import Repositories
from musicbot.publishing.timeutil import from_iso, to_iso, utc_now
from musicbot.radar import scoring
from musicbot.radar.sources import API_HOSTS, BY_ID, SOURCES, ChartSource, parse_apple, parse_deezer, parse_lastfm, parse_youtube

log = logging.getLogger(__name__)
USER_AGENT = "Bia2MusicBot/1.0 (+https://t.me/bia2music1395)"
ROBOTS_TOKEN = "Bia2MusicBot"
STALE_FACTOR = 3                       # بیش از ۳ برابر TTL = «به‌روز نیست»
YT_DAILY_DEFAULT = 150
ERR_FA = {
    "network": "ارتباط با منبع برقرار نشد", "auth": "کلید API نامعتبر است", "forbidden": "دسترسی یا سهمیه‌ی منبع رد شد",
    "notfound": "منطقه/آدرس پیدا نشد", "ratelimit": "محدودیت نرخ منبع", "server": "خطای سرور منبع", "badrequest": "درخواست نامعتبر (منطقه یا کلید)",
    "format": "ساختار پاسخ منبع شناخته نشد", "empty": "منبع داده‌ی خالی برگرداند", "nokey": "کلید API تنظیم نشده", "quota": "سقف درخواست روزانه‌ی ربات برای این منبع پر شد",
}
_REGION_RE = {
    "youtube_trending": re.compile(r"^[A-Za-z]{2}$"), "apple_most_played": re.compile(r"^[A-Za-z]{2}$"),
    "lastfm_geo": re.compile(r"^(GLOBAL|[A-Za-z][A-Za-z .'-]{1,40})$"), "deezer_chart": re.compile(r"^GLOBAL$", re.I),
}


class RadarError(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


@dataclass
class RegionResult:
    region: str
    ok: bool
    count: int = 0
    error_fa: Optional[str] = None


@dataclass
class RefreshResult:
    source_id: str
    regions: list[RegionResult] = field(default_factory=list)
    skipped: Optional[str] = None      # link_only | disabled | no_key | too_soon | fresh | unknown


@dataclass
class RobotsResult:
    fetched: bool
    allowed: Optional[bool]
    excerpt: str
    error: Optional[str] = None


def validate_regions(src: ChartSource, text: str) -> list[str]:
    """ValueError اگر نامعتبر؛ مناطق تمیز و بدون تکرار (حداکثر ۸)."""
    pat = _REGION_RE.get(src.id)
    items = [x.strip() for x in re.split(r"[,،\n]+", text or "") if x.strip()]
    if not pat or not items or len(items) > 8:
        raise ValueError("regions")
    out = []
    for x in items:
        if not pat.match(x):
            raise ValueError("regions")
        norm = x.upper() if src.id == "youtube_trending" else (x.lower() if src.id == "apple_most_played" else x)
        if norm.upper() == "GLOBAL":
            norm = "GLOBAL"
        if norm not in out:
            out.append(norm)
    return out


class RadarService:
    def __init__(self, settings: Settings, repos: Repositories, http: Any = None, *, now: Callable = utc_now, sleep: Callable = asyncio.sleep):
        self.settings, self.repos, self._http, self._now, self._sleep = settings, repos, http, now, sleep
        self._lock = asyncio.Lock()

    # ---------- پایه ----------
    def _client(self):
        if self._http is None:
            import httpx

            self._http = httpx.AsyncClient(timeout=20.0, follow_redirects=False)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and hasattr(self._http, "aclose"):
            await self._http.aclose()

    def key_for(self, src: ChartSource) -> Optional[str]:
        return getattr(self.settings, src.key_attr, None) if src.key_attr else None

    def regions_for(self, src: ChartSource) -> list[str]:
        raw = self.repos.radar.state(src.id)["regions"]
        return [x for x in (raw or "").split(",") if x] or list(src.default_regions)

    def is_stale(self, src: ChartSource, fetched_at: str) -> bool:
        return (self._now() - from_iso(fetched_at)).total_seconds() > src.ttl_s * STALE_FACTOR

    def due(self, src: ChartSource, region: str) -> bool:
        snap = self.repos.radar.latest_snapshot(src.id, region)
        return snap is None or (self._now() - from_iso(snap["fetched_at"])).total_seconds() >= src.ttl_s

    def status(self, src: ChartSource) -> str:
        """link | needs_key | off | never | ok | partial | error"""
        if not src.is_api:
            return "link"
        st = self.repos.radar.state(src.id)
        if src.key_attr and not self.key_for(src):
            return "needs_key"
        if not st["enabled"]:
            return "off"
        return st["last_status"] or "never"

    # ---------- دریافت ----------
    def _yt_calls(self) -> int:
        return self.repos.metrics.totals(1).get("radar_yt_calls", 0)

    def yt_limit(self) -> int:
        try:
            return max(0, int(self.repos.settings.get("radar_yt_daily_limit", str(YT_DAILY_DEFAULT))))
        except ValueError:
            return YT_DAILY_DEFAULT

    async def _get_json(self, url: str, params: dict, headers: Optional[dict] = None) -> Any:
        import httpx

        if urlparse(url).hostname not in API_HOSTS:
            raise RadarError("network")                            # دفاع: فقط میزبان‌های فهرست‌شده
        try:
            resp = await self._client().get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
        except httpx.HTTPError:
            raise RadarError("network") from None
        code = resp.status_code
        if code != 200:
            raise RadarError({400: "badrequest", 401: "auth", 403: "forbidden", 404: "notfound", 429: "ratelimit"}.get(code, "server" if code >= 500 else "format"))
        try:
            return resp.json()
        except ValueError:
            raise RadarError("format") from None

    async def _fetch_region(self, src: ChartSource, region: str) -> list[dict]:
        key = self.key_for(src)
        if src.id == "youtube_trending":
            if not key:
                raise RadarError("nokey")
            if self._yt_calls() >= self.yt_limit():
                raise RadarError("quota")
            self.repos.metrics.incr("radar_yt_calls")
            data = await self._get_json("https://www.googleapis.com/youtube/v3/videos",
                                        {"part": "snippet,statistics", "chart": "mostPopular", "videoCategoryId": "10",
                                         "regionCode": region.upper(), "maxResults": 25, "key": key})
            return parse_youtube(data)
        if src.id == "lastfm_geo":
            if not key:
                raise RadarError("nokey")
            params = {"api_key": key, "format": "json", "limit": 25}
            params.update({"method": "chart.gettoptracks"} if region == "GLOBAL" else {"method": "geo.gettoptracks", "country": region})
            data = await self._get_json("https://ws.audioscrobbler.com/2.0/", params)
            if isinstance(data, dict) and "error" in data:                  # Last.fm خطا را با HTTP 200 می‌دهد
                code = data.get("error")
                raise RadarError("auth" if code in (10, 26) else "ratelimit" if code == 29 else "notfound" if code == 6 else "server")
            return parse_lastfm(data)
        if src.id == "deezer_chart":
            data = await self._get_json("https://api.deezer.com/chart/0/tracks", {"limit": 25})
            if isinstance(data, dict) and "error" in data:
                raise RadarError("format")
            return parse_deezer(data)
        if src.id == "apple_most_played":
            if not re.fullmatch(r"[a-z]{2}", region):
                raise RadarError("notfound")
            return parse_apple(await self._get_json(f"https://rss.applemarketingtools.com/api/v2/{region}/music/most-played/25/songs.json", {}))
        raise RadarError("format")

    async def refresh_source(self, source_id: str, force: bool = False) -> RefreshResult:
        src = BY_ID.get(source_id)
        if src is None:
            return RefreshResult(source_id, skipped="unknown")
        if not src.is_api:
            return RefreshResult(source_id, skipped="link_only")
        st = self.repos.radar.state(source_id)
        if not st["enabled"]:
            return RefreshResult(source_id, skipped="disabled")
        if src.key_attr and not self.key_for(src):
            self.repos.radar.record_fetch(source_id, "needs_key", ERR_FA["nokey"], ok=False, at=to_iso(self._now()))
            return RefreshResult(source_id, skipped="no_key")
        async with self._lock:
            if st["last_fetch_at"] and (self._now() - from_iso(st["last_fetch_at"])).total_seconds() < src.min_interval_s:
                return RefreshResult(source_id, skipped="too_soon")
            regions = [r for r in self.regions_for(src) if force or self.due(src, r)]
            if not regions:
                return RefreshResult(source_id, skipped="fresh")
            result = RefreshResult(source_id)
            errors = []
            for i, region in enumerate(regions):
                if i and src.pause_s:
                    await self._sleep(src.pause_s)
                try:
                    entries = await self._fetch_region(src, region)
                    if not entries:
                        raise RadarError("empty")
                    self.repos.radar.add_snapshot(source_id, region, entries, True, at=to_iso(self._now()))
                    result.regions.append(RegionResult(region, True, len(entries)))
                except RadarError as exc:
                    msg = ERR_FA.get(exc.kind, ERR_FA["format"])
                    result.regions.append(RegionResult(region, False, 0, msg))
                    errors.append(f"{region}: {msg}")
                    if exc.kind in ("quota", "nokey", "auth"):
                        break                                          # ادامه بی‌فایده است
                except Exception:  # noqa: BLE001 - خطای یک منبع بقیه را متوقف نمی‌کند؛ جزئیات (ممکن است شامل URL/کلید باشد) ثبت نمی‌شود
                    log.warning("radar fetch failed for %s", source_id)
                    result.regions.append(RegionResult(region, False, 0, ERR_FA["format"]))
                    errors.append(f"{region}: {ERR_FA['format']}")
            oks = [r for r in result.regions if r.ok]
            status = "ok" if len(oks) == len(result.regions) else ("partial" if oks else "error")
            self.repos.radar.record_fetch(source_id, status, "؛ ".join(errors) or None, ok=bool(oks), at=to_iso(self._now()))
            return result

    async def refresh_all(self, force: bool = False) -> list[RefreshResult]:
        out = []
        for src in SOURCES:
            if src.is_api and self.repos.radar.state(src.id)["enabled"]:
                try:
                    out.append(await self.refresh_source(src.id, force))
                except Exception:  # noqa: BLE001
                    log.warning("radar refresh crashed for %s", src.id)
        return out

    # ---------- داده برای نمایش/امتیاز ----------
    def chart_views(self) -> list[scoring.ChartView]:
        views = []
        for src in SOURCES:
            if not src.is_api or not self.repos.radar.state(src.id)["enabled"]:
                continue
            for region in self.regions_for(src):
                snap = self.repos.radar.latest_snapshot(src.id, region)
                if not snap:
                    continue
                prev = self.repos.radar.previous_snapshot(src.id, region, snap["id"])
                prev_ranks = {scoring.row_key(e): e["rank"] for e in self.repos.radar.entries(prev["id"])} if prev else {}
                views.append(scoring.ChartView(src.id, region, snap["fetched_at"], self.is_stale(src, snap["fetched_at"]),
                                               self.repos.radar.entries(snap["id"]), prev_ranks))
        return views

    def weights(self) -> scoring.Weights:
        return scoring.Weights.parse(self.repos.settings.get("radar_weights"))

    def ranked(self) -> list[scoring.TrackScore]:
        return scoring.score_tracks(self.chart_views(), self.weights(), self._now())

    # ---------- robots.txt (اطلاعات برای تصمیم مدیر؛ هیچ اسکرپی انجام نمی‌شود) ----------
    @staticmethod
    def robots_hosts() -> set[str]:
        hosts = set()
        for s in SOURCES:
            if not s.is_api:
                for u in (s.home_url, s.terms_url, *(l[1] for l in s.links)):
                    hosts.add(urlparse(u).hostname or "")
        return hosts - {""}

    async def check_robots(self, url: str) -> RobotsResult:
        import httpx

        p = urlparse(url)
        if p.scheme not in ("http", "https") or p.hostname not in self.robots_hosts():
            return RobotsResult(False, None, "", "این آدرس مجاز نیست")
        try:
            resp = await self._client().get(f"{p.scheme}://{p.hostname}/robots.txt", headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError:
            return RobotsResult(False, None, "", "ارتباط برقرار نشد")
        if resp.status_code == 404:
            return RobotsResult(True, True, "(robots.txt وجود ندارد)", None)
        if resp.status_code != 200:
            return RobotsResult(False, None, "", f"پاسخ غیرمنتظره ({resp.status_code})")
        text = resp.text[:20000]
        rp = RobotFileParser()
        rp.parse(text.splitlines())
        lines = [l.strip() for l in text.splitlines() if re.match(r"(?i)^\s*(user-agent|disallow|allow|crawl-delay|sitemap)\s*:", l)]
        return RobotsResult(True, rp.can_fetch(ROBOTS_TOKEN, url), "\n".join(lines[:40]), None)
