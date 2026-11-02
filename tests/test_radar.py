import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from musicbot.handlers import menu, radar as rh
from musicbot.logging_setup import redact
from musicbot.publishing import scheduler as sch
from musicbot.radar import scoring
from musicbot.radar.service import ERR_FA, RadarService, validate_regions
from musicbot.radar.sources import BY_ID, SOURCES, parse_apple, parse_deezer, parse_lastfm, parse_youtube
from tests.conftest import ADMIN, make_context, make_update
from tests.helpers import buttons, cbs, txt

YT_KEY = "AIzaSyFAKEKEYFAKEKEYFAKEKEY0123456789"
LF_KEY = "0123456789abcdef0123456789abcdef"
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class Net:
    """شبکه‌ی جعلی: همه‌ی درخواست‌ها ثبت می‌شود؛ routes: تابع (request) -> Response."""

    def __init__(self, route):
        self.route, self.requests = route, []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request):
        self.requests.append(request)
        return self.route(request)

    @property
    def hosts(self):
        return {r.url.host for r in self.requests}


def yt_payload(*vids):
    return {"items": [{"id": v, "snippet": {"title": f"Artist{v} - Song{v} (Official Video)", "channelTitle": "Chan", "publishedAt": "2026-10-30T10:00:00Z"},
                       "statistics": {"viewCount": str(1000 * (i + 1))}} for i, v in enumerate(vids)]}


def apple_payload(*names):
    return {"feed": {"results": [{"id": f"id-{n}", "name": n, "artistName": f"A-{n}", "url": f"https://music.apple.com/{n}", "releaseDate": "2026-10-20"}
                                  for n in names]}}


def lastfm_payload(*names):
    return {"tracks": {"track": [{"name": n, "artist": {"name": f"A-{n}"}, "url": f"https://www.last.fm/music/{n}", "listeners": "500",
                                  "@attr": {"rank": str(i + 1)}} for i, n in enumerate(names)]}}


def default_route(request):
    u = str(request.url)
    if "googleapis.com" in u:
        return httpx.Response(200, json=yt_payload("a", "b", "c"))
    if "audioscrobbler" in u:
        return httpx.Response(200, json=lastfm_payload("T1", "T2"))
    if "deezer" in u:
        return httpx.Response(200, json={"data": [{"id": 1, "title": "D1", "link": "https://www.deezer.com/track/1", "artist": {"name": "DA"}, "position": 1, "rank": 99}]})
    if "applemarketingtools" in u:
        return httpx.Response(200, json=apple_payload("N1", "N2"))
    return httpx.Response(404)


@pytest.fixture
def clock():
    return Clock()


def make(app_ctx, route=default_route, clock=None, yt=True, lf=True):
    net = Net(route)
    if yt:
        object.__setattr__(app_ctx.settings, "youtube_api_key", YT_KEY)
    if lf:
        object.__setattr__(app_ctx.settings, "lastfm_api_key", LF_KEY)
    sleeps = []

    async def sleep(x):
        sleeps.append(x)

    svc = RadarService(app_ctx.settings, app_ctx.repos, net.client, now=clock or Clock(), sleep=sleep)
    svc.sleeps = sleeps
    app_ctx.radar = svc
    return svc, net


# ---------- تجزیه‌گرها ----------
def test_parse_youtube_defensive():
    out = parse_youtube({"items": [
        {"id": "x1", "snippet": {"title": "Ali - Shab [Official Music Video]", "channelTitle": "Ali - Topic", "publishedAt": "2026-10-30T10:00:00Z"},
         "statistics": {"viewCount": "12345"}},
        {"id": {"videoId": "x2"}, "snippet": {"title": "Only Title", "channelTitle": "SomeChannel"}},
        {"id": "x3", "snippet": {}}, "junk", {"snippet": {"title": "no id"}}, None]})
    assert [e["ext_id"] for e in out] == ["x1", "x2"]
    a, b = out
    assert (a["artist"], a["title"], a["rank"], a["native_label"], a["published_at"]) == ("Ali", "Shab", 1, "12,345 بازدید", "2026-10-30T10:00:00Z")
    assert (b["artist"], b["title"], b["native_label"], b["published_at"]) == ("SomeChannel", "Only Title", None, None)        # مقدار ناموجود حدس زده نمی‌شود
    assert a["url"] == "https://www.youtube.com/watch?v=x1"
    for garbage in (None, [], "x", {"items": "no"}, {"items": [1, 2]}):
        assert parse_youtube(garbage) == []


def test_parse_lastfm_shapes():
    one = parse_lastfm({"tracks": {"track": {"name": "T", "artist": "Plain", "url": "https://www.last.fm/x", "playcount": "9"}}})
    assert one[0]["artist"] == "Plain" and one[0]["native_label"] == "9 پخش" and one[0]["rank"] == 1
    many = parse_lastfm({"toptracks": {"track": [{"name": "A", "@attr": {"rank": "7"}}, {"name": "B"}, {"x": 1}]}})
    assert [(e["rank"], e["title"]) for e in many] == [(7, "A"), (2, "B")]
    assert parse_lastfm({"tracks": {"track": [{"name": "A", "url": "javascript:alert(1)"}]}})[0]["url"] is None
    assert parse_lastfm({}) == [] and parse_lastfm({"tracks": "x"}) == []


def test_parse_deezer_apple():
    d = parse_deezer({"data": [{"id": 5, "title": "T", "link": "https://x.y/1", "artist": {"name": "A"}, "position": "4", "rank": "123456"}, {"title": ""}, 5]})
    assert d[0]["rank"] == 4 and d[0]["native_label"] == "شاخص محبوبیت Deezer: 123,456" and len(d) == 1
    a = parse_apple(apple_payload("X", "Y"))
    assert [e["rank"] for e in a] == [1, 2] and a[0]["published_at"] == "2026-10-20"
    assert parse_apple({"feed": None}) == [] and parse_deezer({"data": "x"}) == []


# ---------- امتیازدهی ----------
def entry(rank, title="song", artist="art", ext=None, pub=None, label=None, url=None):
    from musicbot.songs.textutils import normalize

    return {"rank": rank, "title": title, "artist": artist, "ext_id": ext, "title_norm": normalize(title), "artist_norm": normalize(artist),
            "published_at": pub, "native_label": label, "url": url}


def view(src, region, entries, prev=None, stale=False):
    return scoring.ChartView(src, region, "2026-11-02T10:00:00Z", stale, entries, prev or {})


def test_score_formula_exact():
    now = T0
    w = scoring.Weights()
    s = scoring.score_tracks([view("apple_most_played", "us", [entry(1, ext="a")], prev={"a": 4})], w, now)[0]
    assert (s.rank_points, s.move_points, s.multi_points, s.fresh_points) == (25, 3, 0, 0) and s.total == 28
    assert s.appearances[0].delta == 3 and s.fresh_known is False
    # صعود بزرگ سقف +۱۰ و افت بزرگ کف −۵ دارد
    up = scoring.score_tracks([view("a", "us", [entry(1, ext="a")], prev={"a": 40})], w, now)[0]
    down = scoring.score_tracks([view("a", "us", [entry(10, ext="a")], prev={"a": 1})], w, now)[0]
    assert up.move_points == 10 and down.move_points == -5 and down.rank_points == 16


def test_no_previous_means_unknown_not_zero_change():
    s = scoring.score_tracks([view("a", "us", [entry(2)])], scoring.Weights(), T0)[0]
    assert s.appearances[0].delta is None and s.move_points == 0


def test_multi_source_counts_independent_sources_only():
    w = scoring.Weights()
    two_regions = scoring.score_tracks([view("youtube_trending", "US", [entry(1)]), view("youtube_trending", "GB", [entry(3)])], w, T0)
    assert len(two_regions) == 1 and two_regions[0].multi_points == 0                       # یک منبع، دو منطقه ← جایزه ندارد
    two_sources = scoring.score_tracks([view("youtube_trending", "US", [entry(1)]), view("apple_most_played", "us", [entry(3)])], w, T0)[0]
    assert two_sources.multi_points == 10 and two_sources.rank_points == 25 + 23 and two_sources.sources == {"youtube_trending", "apple_most_played"}
    three = scoring.score_tracks([view(s, "x", [entry(1)]) for s in ("a", "b", "c")], w, T0)[0]
    assert three.multi_points == 20


def test_freshness_only_from_source_date():
    def sc(pub):
        return scoring.score_tracks([view("a", "us", [entry(1, pub=pub)])], scoring.Weights(), T0)[0]

    assert sc("2026-10-30T10:00:00Z").fresh_points == 10 and sc("2026-10-30T10:00:00Z").fresh_known
    assert sc("2026-10-20").fresh_points == 5 and sc("2026-09-01").fresh_points == 0 and sc("2026-09-01").fresh_known
    for unknown in (None, "", "not a date"):
        s = sc(unknown)
        assert s.fresh_points == 0 and not s.fresh_known and s.published_at is None                    # تاریخ ناموجود حدس زده نمی‌شود


def test_stale_charts_excluded_and_ordering():
    w = scoring.Weights()
    out = scoring.score_tracks([view("a", "us", [entry(1, "old", "x")], stale=True), view("b", "us", [entry(5, "mid", "y"), entry(2, "top", "z")])], w, T0)
    assert [t.title for t in out] == ["top", "mid"]                                                    # کهنه در امتیاز نیست
    assert scoring.score_tracks([view("a", "us", [entry(1)], stale=True)], w, T0) == []


def test_weights_parse_dump_explain():
    w = scoring.Weights.parse("2,3,4,5")
    assert (w.rank, w.move, w.multi, w.fresh) == (2, 3, 4, 5) and w.dump() == "2,3,4,5"
    for bad in (None, "", "1,2,3", "a,b,c,d"):
        assert scoring.Weights.parse(bad).dump() == "1,1,10,1"
    scaled = scoring.score_tracks([view("a", "us", [entry(1, ext="e")], prev={"e": 2})], w, T0)[0]
    assert scaled.rank_points == 50 and scaled.move_points == 3
    text = scoring.explain(w)
    assert "داخلی" in text and "شاخص رسمی" in text and "تعداد پخش کل</b> معیار نیست" in text and "حدس زده نمی‌شود" in text


# ---------- سرویس: دسترسی و تأیید ----------
async def test_nothing_fetched_without_approval_or_for_link_only(app_ctx):
    svc, net = make(app_ctx)
    for sid in ("youtube_trending", "lastfm_geo", "deezer_chart", "apple_most_played"):
        assert (await svc.refresh_source(sid)).skipped == "disabled"
    for src in SOURCES:
        if not src.is_api:
            assert (await svc.refresh_source(src.id, force=True)).skipped == "link_only"
    assert (await svc.refresh_all(force=True)) == [] and net.requests == []                           # هیچ درخواستی نرفته
    assert svc.status(BY_ID["farsichart"]) == "link" and svc.status(BY_ID["apple_most_played"]) == "off"


async def test_missing_key_blocks_and_reports(app_ctx):
    svc, net = make(app_ctx, yt=False, lf=False)
    object.__setattr__(app_ctx.settings, "youtube_api_key", None)
    assert svc.status(BY_ID["youtube_trending"]) == "needs_key"
    app_ctx.repos.radar.set_enabled("youtube_trending", True)
    res = await svc.refresh_source("youtube_trending", force=True)
    assert res.skipped == "no_key" and net.requests == []
    assert app_ctx.repos.radar.state("youtube_trending")["last_error"] == ERR_FA["nokey"]


async def test_enable_fetch_cache_ttl_and_min_interval(app_ctx, clock):
    svc, net = make(app_ctx, clock=clock)
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    res = await svc.refresh_source("apple_most_played")
    assert [r.region for r in res.regions] == ["us", "gb", "tr"] and all(r.ok and r.count == 2 for r in res.regions)
    assert len(net.requests) == 3
    st = app_ctx.repos.radar.state("apple_most_played")
    assert st["last_status"] == "ok" and st["last_ok_at"] and st["approved_at"]
    snap = app_ctx.repos.radar.latest_snapshot("apple_most_played", "us")
    assert snap["entry_count"] == 2 and app_ctx.repos.radar.entries(snap["id"])[0]["title"] == "N1"
    assert (await svc.refresh_source("apple_most_played")).skipped == "too_soon"                       # حداقل فاصله
    clock.advance(seconds=400)
    assert (await svc.refresh_source("apple_most_played")).skipped == "fresh"                          # کش هنوز تازه
    assert (await svc.refresh_source("apple_most_played", force=True)).regions[0].ok                  # force از TTL رد می‌شود
    assert len(net.requests) == 6
    clock.advance(seconds=400)
    assert (await svc.refresh_source("apple_most_played", force=True)).regions and len(net.requests) == 9
    clock.advance(hours=13)
    assert (await svc.refresh_source("apple_most_played")).regions                                     # بعد از TTL خودکار
    assert len(net.requests) == 12


async def test_request_shapes_and_allowlist(app_ctx):
    svc, net = make(app_ctx)
    for sid in ("youtube_trending", "lastfm_geo", "deezer_chart", "apple_most_played"):
        app_ctx.repos.radar.set_enabled(sid, True)
    app_ctx.repos.radar.set_regions("youtube_trending", "US")
    app_ctx.repos.radar.set_regions("lastfm_geo", "GLOBAL,Iran")
    await svc.refresh_all(force=True)
    by_host = {}
    for r in net.requests:
        by_host.setdefault(r.url.host, []).append(r)
    yt = by_host["www.googleapis.com"][0]
    assert yt.url.path == "/youtube/v3/videos" and dict(yt.url.params) == {
        "part": "snippet,statistics", "chart": "mostPopular", "videoCategoryId": "10", "regionCode": "US", "maxResults": "25", "key": YT_KEY}
    lf = [dict(r.url.params) for r in by_host["ws.audioscrobbler.com"]]
    assert lf[0]["method"] == "chart.gettoptracks" and "country" not in lf[0] and lf[1]["method"] == "geo.gettoptracks" and lf[1]["country"] == "Iran"
    assert lf[0]["format"] == "json" and lf[0]["api_key"] == LF_KEY
    assert by_host["api.deezer.com"][0].url.path == "/chart/0/tracks"
    assert by_host["rss.applemarketingtools.com"][0].url.path == "/api/v2/us/music/most-played/25/songs.json"
    assert all("Bia2MusicBot" in r.headers["user-agent"] for r in net.requests)
    assert net.hosts <= {"www.googleapis.com", "ws.audioscrobbler.com", "api.deezer.com", "rss.applemarketingtools.com"}
    assert svc.sleeps == [1.0]                                                                         # مکث بین مناطق Last.fm


async def test_error_mapping_and_isolation(app_ctx, clock):
    state = {"mode": "ok"}

    def route(request):
        u = str(request.url)
        if "applemarketingtools" in u:
            if "/gb/" in u:
                raise httpx.ConnectError("down")
            if "/tr/" in u:
                return httpx.Response(404)
            return httpx.Response(200, json=apple_payload("N"))
        return httpx.Response(500)

    svc, net = make(app_ctx, route, clock)
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    res = await svc.refresh_source("apple_most_played")
    assert [(r.region, r.ok, r.error_fa) for r in res.regions] == [("us", True, None), ("gb", False, ERR_FA["network"]), ("tr", False, ERR_FA["notfound"])]
    st = app_ctx.repos.radar.state("apple_most_played")
    assert st["last_status"] == "partial" and "gb: " + ERR_FA["network"] in st["last_error"]
    assert app_ctx.repos.radar.latest_snapshot("apple_most_played", "gb") is None                         # شکست، عکس خالی نمی‌سازد


@pytest.mark.parametrize("status,kind", [(400, "badrequest"), (401, "auth"), (403, "forbidden"), (404, "notfound"), (429, "ratelimit"), (503, "server"), (302, "format")])
async def test_http_status_mapping(app_ctx, status, kind):
    svc, _ = make(app_ctx, lambda r: httpx.Response(status))
    app_ctx.repos.radar.set_enabled("deezer_chart", True)
    res = await svc.refresh_source("deezer_chart", force=True)
    assert res.regions[0].error_fa == ERR_FA[kind] and app_ctx.repos.radar.state("deezer_chart")["last_status"] == "error"


async def test_bad_bodies(app_ctx):
    app_ctx.repos.radar.set_enabled("deezer_chart", True)
    clock = Clock()
    for body, kind in ((httpx.Response(200, content=b"<html>"), "format"), (httpx.Response(200, json={"data": []}), "empty"),
                       (httpx.Response(200, json={"error": {"code": 4}}), "format"), (httpx.Response(200, json={"data": [{"nothing": 1}]}), "empty")):
        svc, _ = make(app_ctx, lambda r, b=body: b, clock)
        res = await svc.refresh_source("deezer_chart", force=True)
        assert res.regions[0].error_fa == ERR_FA[kind], body
        clock.advance(days=1)                                                                          # از min_interval رد شود


async def test_lastfm_error_in_200_body(app_ctx, clock):
    codes = {"Iran": 6, "Turkey": 29}

    def route(request):
        c = request.url.params.get("country")
        return httpx.Response(200, json={"error": codes[c], "message": "x"}) if c in codes else httpx.Response(200, json=lastfm_payload("G"))

    svc, _ = make(app_ctx, route, clock)
    app_ctx.repos.radar.set_enabled("lastfm_geo", True)
    app_ctx.repos.radar.set_regions("lastfm_geo", "GLOBAL,Iran,Turkey")
    res = await svc.refresh_source("lastfm_geo")
    assert [(r.region, r.error_fa) for r in res.regions] == [("GLOBAL", None), ("Iran", ERR_FA["notfound"]), ("Turkey", ERR_FA["ratelimit"])]
    app_ctx.repos.radar.set_regions("lastfm_geo", "Iran")
    clock.advance(seconds=500)
    svc2, _ = make(app_ctx, lambda r: httpx.Response(200, json={"error": 10, "message": "Invalid API key"}), clock)
    res = await svc2.refresh_source("lastfm_geo", force=True)
    assert res.regions[0].error_fa == ERR_FA["auth"]


async def test_auth_error_stops_remaining_regions(app_ctx):
    svc, net = make(app_ctx, lambda r: httpx.Response(401))
    app_ctx.repos.radar.set_enabled("youtube_trending", True)
    res = await svc.refresh_source("youtube_trending", force=True)
    assert len(res.regions) == 1 and len(net.requests) == 1                                           # بقیه‌ی مناطق بی‌فایده است


async def test_youtube_daily_quota_guard(app_ctx):
    svc, net = make(app_ctx)
    app_ctx.repos.radar.set_enabled("youtube_trending", True)
    app_ctx.repos.settings.set("radar_yt_daily_limit", "2")
    res = await svc.refresh_source("youtube_trending", force=True)       # ۳ منطقه‌ی پیش‌فرض، سقف ۲
    assert [r.ok for r in res.regions] == [True, True, False] and res.regions[2].error_fa == ERR_FA["quota"]
    assert len(net.requests) == 2 and app_ctx.repos.metrics.totals(1)["radar_yt_calls"] == 2
    app_ctx.repos.settings.set("radar_yt_daily_limit", "abc")
    assert svc.yt_limit() == 150


async def test_unexpected_exception_isolated_and_secret_not_logged(app_ctx, caplog, clock):
    def route(request):
        if "applemarketingtools" in str(request.url):
            return httpx.Response(200, json=apple_payload("OK"))
        raise RuntimeError(f"boom {request.url}")                                                     # شامل URL (و کلید)

    svc, _ = make(app_ctx, route, clock)
    for sid in ("youtube_trending", "apple_most_played"):
        app_ctx.repos.radar.set_enabled(sid, True)
    with caplog.at_level(logging.DEBUG):
        results = await svc.refresh_all(force=True)
    assert {r.source_id for r in results} == {"youtube_trending", "apple_most_played"}
    assert app_ctx.repos.radar.latest_snapshot("apple_most_played", "us")                             # منبع دیگر سالم ماند
    assert YT_KEY not in caplog.text and YT_KEY not in json.dumps([r.__dict__ for r in results], default=str)
    err = app_ctx.repos.radar.state("youtube_trending")["last_error"]
    assert YT_KEY not in err and "boom" not in err


async def test_keys_never_stored(app_ctx):
    svc, _ = make(app_ctx)
    for sid in ("youtube_trending", "lastfm_geo"):
        app_ctx.repos.radar.set_enabled(sid, True)
    await svc.refresh_all(force=True)
    dump = ""
    for t in [x["name"] for x in app_ctx.repos.db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")]:
        dump += " ".join(str(dict(r)) for r in app_ctx.repos.db.fetchall(f"SELECT * FROM {t}"))
    assert YT_KEY not in dump and LF_KEY not in dump
    assert YT_KEY not in redact(f"GET https://www.googleapis.com/youtube/v3/videos?part=x&key={YT_KEY}") and LF_KEY not in redact(f"https://ws.audioscrobbler.com/2.0/?method=x&api_key={LF_KEY}&format=json")
    assert YT_KEY not in redact(f"token {YT_KEY} leaked")


async def test_snapshot_retention_and_failed_fetch_keeps_old(app_ctx, clock):
    svc, _ = make(app_ctx, clock=clock)
    app_ctx.repos.radar.set_enabled("deezer_chart", True)
    for _ in range(12):
        await svc.refresh_source("deezer_chart", force=True)
        clock.advance(seconds=200)
    n = app_ctx.repos.db.fetchone("SELECT COUNT(*) c FROM radar_snapshots WHERE source_id='deezer_chart'")["c"]
    assert n == 10 and app_ctx.repos.db.fetchone("SELECT COUNT(*) c FROM radar_entries")["c"] == 10     # ردیف‌های حذف‌شده هم پاک شد
    svc2, _ = make(app_ctx, lambda r: httpx.Response(500), clock)
    await svc2.refresh_source("deezer_chart", force=True)
    assert app_ctx.repos.radar.latest_snapshot("deezer_chart", "GLOBAL")["ok"] == 1                    # داده‌ی قبلی می‌ماند


async def test_rank_change_between_snapshots_and_staleness(app_ctx, clock):
    order = {"v": ["a", "b", "c"]}
    svc, _ = make(app_ctx, lambda r: httpx.Response(200, json=yt_payload(*order["v"])), clock)
    app_ctx.repos.radar.set_enabled("youtube_trending", True)
    app_ctx.repos.radar.set_regions("youtube_trending", "US")
    await svc.refresh_source("youtube_trending", force=True)
    first = svc.ranked()
    assert all(a.delta is None for t in first for a in t.appearances)                                   # عکس قبلی نیست ← نامشخص
    clock.advance(hours=7)
    order["v"] = ["c", "a", "b"]
    await svc.refresh_source("youtube_trending")
    ranked = {t.title: t for t in svc.ranked()}
    assert ranked["Songc"].appearances[0].delta == 2 and ranked["Songa"].appearances[0].delta == -1 and ranked["Songb"].appearances[0].delta == -1
    assert ranked["Songc"].total > ranked["Songa"].total
    clock.advance(hours=24)                                                                              # > ۳×TTL(۶ ساعت)
    views = svc.chart_views()
    assert views[0].stale and svc.ranked() == []


# ---------- robots و مناطق ----------
async def test_robots_check(app_ctx):
    def route(request):
        if request.url.host == "farsichart.com":
            return httpx.Response(200, text="User-agent: *\nDisallow: /music/trending\nAllow: /\nSitemap: https://farsichart.com/s.xml\n# comment\n")
        return httpx.Response(404)

    svc, net = make(app_ctx, route)
    r = await svc.check_robots("https://farsichart.com/music/trending")
    assert r.fetched and r.allowed is False and "Disallow: /music/trending" in r.excerpt and "comment" not in r.excerpt
    assert (await svc.check_robots("https://farsichart.com/other")).allowed is True
    assert (await svc.check_robots("https://www.radiojavan.com/x")).allowed is True and "وجود ندارد" in (await svc.check_robots("https://www.radiojavan.com/x")).excerpt
    for evil in ("https://evil.example/x", "file:///etc/passwd", "http://127.0.0.1/robots", "https://api.deezer.com/chart"):
        bad = await svc.check_robots(evil)
        assert not bad.fetched and bad.error
    assert {r.url.host for r in net.requests} <= RadarService.robots_hosts()
    svc2, _ = make(app_ctx, lambda r: (_ for _ in ()).throw(httpx.ConnectError("x")))
    assert (await svc2.check_robots("https://farsichart.com/")).error == "ارتباط برقرار نشد"


def test_validate_regions():
    assert validate_regions(BY_ID["youtube_trending"], "us, gb ، TR, us") == ["US", "GB", "TR"]
    assert validate_regions(BY_ID["apple_most_played"], "US,Gb") == ["us", "gb"]
    assert validate_regions(BY_ID["lastfm_geo"], "global, Iran, United States") == ["GLOBAL", "Iran", "United States"]
    assert validate_regions(BY_ID["deezer_chart"], "global") == ["GLOBAL"]
    for src, bad in (("youtube_trending", "USA"), ("youtube_trending", ""), ("youtube_trending", "U1"), ("apple_most_played", "x"),
                     ("lastfm_geo", "../etc"), ("deezer_chart", "us"), ("youtube_trending", ",".join(["US"] * 9) + ",GB")):
        with pytest.raises(ValueError):
            validate_regions(BY_ID[src], bad)


# ---------- رابط ربات ----------
async def click(c, data, user=ADMIN):
    u = make_update(user_id=user, data=data)
    await (rh.radar_callback if data.startswith("x:") else menu.menu_callback)(u, c)
    return u


async def say(c, text, user=ADMIN):
    u = make_update(user_id=user, text=text)
    await menu.text_router(u, c)
    return u


async def test_hub_and_source_list(app_ctx):
    make(app_ctx)
    c = make_context(app_ctx)
    u = await click(c, "m:radar")
    t = txt(u)
    assert "رادار موسیقی‌های ترند" in t and "هیچ منبعی بدون تأیید صریح شما فعال نمی‌شود" in t and "هیچ فایلی دانلود یا منتشر نمی‌شود" in t
    assert "آخرین به‌روزرسانی داده‌ها: هنوز داده‌ای دریافت نشده" in t and "منابع API فعال: 0 از 4" in t
    u = await click(c, "x:src")
    assert len([x for x in cbs(u) if x.startswith("x:s:")]) == len(SOURCES) == 9
    labels = " ".join(b.text for b in buttons(u))
    assert "🔗 FarsiChart" in labels and "⚪ Apple Music Most Played" in labels and "🔑 YouTube Trending Music" not in labels   # کلید داده شده


async def test_key_missing_hides_approve_and_explains(app_ctx):
    make(app_ctx, yt=False)
    object.__setattr__(app_ctx.settings, "youtube_api_key", None)
    c = make_context(app_ctx)
    u = await click(c, "x:s:youtube_trending")
    assert "x:ap:youtube_trending" not in cbs(u) and "YOUTUBE_API_KEY" in txt(u) and "❌ نیست" in txt(u)
    assert "🔑" in " ".join(b.text for b in buttons(await click(c, "x:src")))
    assert "نامعتبر" in txt(await click(c, "x:ap:youtube_trending"))                                    # با دستکاری هم فعال نمی‌شود
    assert app_ctx.repos.radar.state("youtube_trending")["enabled"] == 0


async def test_approval_flow_requires_explicit_confirmation(app_ctx):
    svc, net = make(app_ctx)
    c = make_context(app_ctx)
    u = await click(c, "x:s:apple_most_played")
    assert "x:ap:apple_most_played" in cbs(u) and "من تأیید نکرده‌ام" in txt(u) and "⚠️ خیر" in txt(u)
    u = await click(c, "x:ap:apple_most_played")
    assert "شرایط را خوانده‌اید" in txt(u) and "مسئولیت رعایت شرایط" in txt(u) and "x:apy:apple_most_played" in cbs(u)
    assert net.requests == [] and app_ctx.repos.radar.state("apple_most_played")["enabled"] == 0         # تا تأیید دوم هیچ اتفاقی نیفتاده
    u = await click(c, "x:apy:apple_most_played")
    assert app_ctx.repos.radar.state("apple_most_played")["enabled"] == 1 and len(net.requests) == 3
    assert "نتیجه‌ی اولین دریافت" in txt(u) and "✅ us: 2 ردیف" in txt(u)
    assert any(l["action"] == "radar_source_enabled" for l in app_ctx.repos.logs.recent(10))
    assert {"x:f:apple_most_played", "x:off:apple_most_played", "x:rg:apple_most_played"} <= cbs(u)
    await click(c, "x:off:apple_most_played")
    assert app_ctx.repos.radar.state("apple_most_played")["enabled"] == 0
    for bad in ("x:ap:farsichart", "x:apy:farsichart", "x:ap:nope"):
        assert "نامعتبر" in txt(await click(c, bad))


async def test_link_only_source_panel_and_robots(app_ctx):
    def route(request):
        return httpx.Response(200, text="User-agent: *\nDisallow: /music/trending\n")

    svc, net = make(app_ctx, route)
    c = make_context(app_ctx)
    u = await click(c, "x:s:farsichart")
    assert "فقط لینک" in txt(u) and "x:ap:farsichart" not in cbs(u) and "x:rb:farsichart" in cbs(u)
    urls = [b.url for b in buttons(u) if b.url]
    assert "https://farsichart.com" in urls and "https://farsichart.com/music/trending" in urls
    assert net.requests == []
    u = await click(c, "x:rb:farsichart")
    assert "ممنوع است" in txt(u) and "Disallow: /music/trending" in txt(u) and "هیچ صفحه‌ای از این منبع را اسکرپ نمی‌کند" in txt(u)
    assert {r.url.path for r in net.requests} == {"/robots.txt"}                                           # فقط robots؛ نه خود صفحه


async def test_fetch_now_and_regions_edit(app_ctx, clock):
    svc, net = make(app_ctx, clock=clock)
    c = make_context(app_ctx)
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    await click(c, "x:rg:apple_most_played")
    assert c.user_data["awaiting"] == "xrg:apple_most_played"
    assert "❌" in txt(await say(c, "USA"))
    u = await say(c, "DE, fr")
    assert app_ctx.repos.radar.state("apple_most_played")["regions"] == "de,fr" and "ذخیره شد" in txt(u)
    u = await click(c, "x:f:apple_most_played")
    assert "✅ de: 2 ردیف" in txt(u) and "✅ fr: 2 ردیف" in txt(u)
    u = await click(c, "x:f:apple_most_played")
    assert "همین چند لحظه پیش" in txt(u)
    assert "نامعتبر" in txt(await click(c, "x:rg:farsichart"))


async def test_top_view_empty_then_with_data(app_ctx, clock):
    svc, _ = make(app_ctx, clock=clock)
    c = make_context(app_ctx)
    assert "هنوز هیچ منبعی داده نداده" in txt(await click(c, "x:top:0"))
    for sid in ("youtube_trending", "apple_most_played"):
        app_ctx.repos.radar.set_enabled(sid, True)
    app_ctx.repos.radar.set_regions("youtube_trending", "US")
    app_ctx.repos.radar.set_regions("apple_most_played", "us")
    u = await click(c, "x:fa")
    assert "نتیجه‌ی به‌روزرسانی" in txt(u) and "آخرین به‌روزرسانی داده‌ها: " in txt(u)
    t = txt(await click(c, "x:top:0"))
    assert "ترندهای ترکیبی" in t and "امتیاز ربات" in t and "جدا از شاخص رسمی" in t and "آخرین به‌روزرسانی" in t
    assert "Songa" in t and "YouTube Trending Music·US #1" in t and "12,345" not in t and "1,000 بازدید" in t
    assert "تغییر: نامشخص" in t and "انتشار (طبق منبع): 2026-10-30" in t
    assert "N1" in t and "A-N1" in t


async def test_top_pagination(app_ctx, clock):
    names = [f"Tune{i}" for i in range(20)]
    svc, _ = make(app_ctx, lambda r: httpx.Response(200, json=apple_payload(*names)), clock)
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    app_ctx.repos.radar.set_regions("apple_most_played", "us")
    await svc.refresh_source("apple_most_played", force=True)
    c = make_context(app_ctx)
    u = await click(c, "x:top:0")
    assert "صفحه 1 از 3" in txt(u) and "x:top:1" in cbs(u) and "Tune0" in txt(u) and "Tune9" not in txt(u)
    u = await click(c, "x:top:2")
    assert "Tune19" in txt(u) and "x:top:1" in cbs(u) and "x:top:3" not in cbs(u)
    assert len(txt(u)) < 4096
    assert "صفحه 3 از 3" in txt(await click(c, "x:top:99"))


async def test_chart_view_deltas_and_stale_warning(app_ctx, clock):
    order = {"v": ["Aa", "Bb"]}
    svc, _ = make(app_ctx, lambda r: httpx.Response(200, json=apple_payload(*order["v"])), clock)
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    app_ctx.repos.radar.set_regions("apple_most_played", "us")
    await svc.refresh_source("apple_most_played", force=True)
    c = make_context(app_ctx)
    u = await click(c, "x:cs")
    assert "x:c:apple_most_played:0" in cbs(u)
    t = txt(await click(c, "x:c:apple_most_played:0"))
    assert "عکس قبلی نیست" in t and "تغییر: نامشخص" in t and "Aa" in t
    clock.advance(hours=13)
    order["v"] = ["Bb", "Cc"]
    await svc.refresh_source("apple_most_played")
    t = txt(await click(c, "x:c:apple_most_played:0"))
    assert "🆕 تازه وارد" in t and "▲1" in t and "به‌روز نیست" not in t and "عکس قبلی نیست" not in t
    clock.advance(days=3)
    t = txt(await click(c, "x:c:apple_most_played:0"))
    assert "به‌روز نیست" in t and "جدید در نظر نگیرید" in t
    assert "⚠️ Apple" in " ".join(b.text for b in buttons(await click(c, "x:cs")))
    assert "نامعتبر" in txt(await click(c, "x:c:apple_most_played:9")) and "نامعتبر" in txt(await click(c, "x:c:nope:0"))


async def test_how_and_weights(app_ctx):
    make(app_ctx)
    c = make_context(app_ctx)
    u = await click(c, "x:how")
    assert "روش محاسبه" in txt(u) and "1,1,10,1" in txt(u) and "رتبه‌ی فعلی" in txt(u)
    await click(c, "x:w")
    for bad in ("1,2,3", "a,b,c,d", "1,2,3,200", "-1,1,1,1"):
        assert "❌" in txt(await say(c, bad))
    u = await say(c, "۲, 1, 5, 0")
    assert app_ctx.repos.settings.get("radar_weights") == "2,1,5,0" and "2,1,5,0" in txt(u)
    u = await click(c, "x:wr")
    assert "1,1,10,1" in txt(u)


async def test_manual_entries(app_ctx):
    make(app_ctx)
    c = make_context(app_ctx)
    assert "هنوز موردی ثبت نشده" in txt(await click(c, "x:ml"))
    await click(c, "x:m")
    assert c.user_data["awaiting"] == "xm"
    for bad in (" | x", "t | a | not-a-url", "t | a | ftp://x"):
        assert "❌" in txt(await say(c, bad))
    u = await say(c, "آهنگ تست | خواننده | https://farsichart.com/x | FarsiChart Trending")
    assert "آهنگ تست" in txt(u) and "FarsiChart Trending" in txt(u) and 'href="https://farsichart.com/x"' in txt(u)
    mid = app_ctx.repos.radar.manual_list(1)[0]["id"]
    await click(c, "x:m")
    await say(c, "فقط عنوان")
    assert len(app_ctx.repos.radar.manual_list()) == 2
    await click(c, f"x:md:{mid}")
    assert [m["title"] for m in app_ctx.repos.radar.manual_list()] == ["فقط عنوان"]
    assert "نامعتبر" in txt(await click(c, "x:md:abc"))
    for i in range(499):
        app_ctx.repos.radar.add_manual(f"t{i}", None, None, None)                                          # با «فقط عنوان» = ۵۰۰
    await click(c, "x:m")
    assert "حداکثر ۵۰۰" in txt(await say(c, "یکی بیشتر"))


async def test_stranger_cannot_use_radar(app_ctx):
    svc, net = make(app_ctx)
    c = make_context(app_ctx)
    for data in ("x:src", "x:apy:apple_most_played", "x:f:apple_most_played", "x:fa", "x:rb:farsichart", "x:m", "x:w"):
        u = await click(c, data, user=555)
        u.callback_query.edit_message_text.assert_not_called()
    c.user_data["awaiting"] = "xm"
    await say(c, "x | y", user=555)
    assert net.requests == [] and app_ctx.repos.radar.manual_list() == [] and app_ctx.repos.radar.state("apple_most_played")["enabled"] == 0


async def test_scheduler_refresh_radar(app_ctx, clock):
    svc, net = make(app_ctx, clock=clock)
    assert await sch.refresh_radar(app_ctx) == 0 and net.requests == []                                   # هیچ منبع فعالی نیست
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    assert await sch.refresh_radar(app_ctx) == 1 and len(net.requests) == 3
    assert await sch.refresh_radar(app_ctx) == 0                                                           # کش
    app_ctx.radar = type("Boom", (), {"refresh_all": staticmethod(lambda force=False: (_ for _ in ()).throw(RuntimeError("x")))})()
    assert await sch.refresh_radar(app_ctx) == 0                                                           # خطا مهار می‌شود


def test_radar_modules_cannot_message_or_download():
    from pathlib import Path

    root = Path(__file__).parent.parent / "musicbot"
    for f in ("radar/sources.py", "radar/service.py", "radar/scoring.py", "handlers/radar.py"):
        t = (root / f).read_text()
        for banned in ("send_message", "send_audio", "send_photo", "send_document", "forward_message", "publish_now", "publish_ad_now", "download_as_bytearray", "get_file"):
            assert banned not in t, (f, banned)
    assert "youtube-dl" not in (root / "radar/service.py").read_text() and "yt_dlp" not in (root / "radar/service.py").read_text()


async def test_http_layer_refuses_non_allowlisted_hosts(app_ctx):
    from musicbot.radar.service import RadarError

    svc, net = make(app_ctx)
    for url in ("https://evil.example/x", "http://127.0.0.1:8080/admin", "https://www.googleapis.com.evil.example/y", "https://farsichart.com/music/trending",
                "file:///etc/passwd"):
        with pytest.raises(RadarError):
            await svc._get_json(url, {})
    assert net.requests == []                                                                              # هیچ درخواستی از ربات خارج نشد


async def test_repeated_failures_never_evict_good_snapshots(app_ctx, clock):
    ok = {"v": True}
    svc, _ = make(app_ctx, lambda r: httpx.Response(200, json=apple_payload("A", "B")) if ok["v"] else httpx.Response(500), clock)
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    app_ctx.repos.radar.set_regions("apple_most_played", "us")
    for _ in range(3):
        await svc.refresh_source("apple_most_played", force=True)
        clock.advance(seconds=400)
    good_before = app_ctx.repos.db.fetchone("SELECT COUNT(*) c FROM radar_snapshots WHERE ok=1")["c"]
    ok["v"] = False
    for _ in range(15):                                                                                      # شکست‌های پیاپی بیش از سقف نگهداری
        await svc.refresh_source("apple_most_played", force=True)
        clock.advance(seconds=400)
    assert app_ctx.repos.db.fetchone("SELECT COUNT(*) c FROM radar_snapshots WHERE ok=1")["c"] == good_before == 3
    assert app_ctx.repos.db.fetchone("SELECT COUNT(*) c FROM radar_snapshots WHERE ok=0")["c"] == 0
    assert app_ctx.repos.radar.latest_snapshot("apple_most_played", "us") and app_ctx.repos.radar.previous_snapshot(
        "apple_most_played", "us", app_ctx.repos.radar.latest_snapshot("apple_most_played", "us")["id"])      # برای تغییر رتبه هنوز عکس قبلی هست
    assert app_ctx.repos.radar.state("apple_most_played")["last_status"] == "error" and app_ctx.repos.radar.state("apple_most_played")["last_ok_at"]
