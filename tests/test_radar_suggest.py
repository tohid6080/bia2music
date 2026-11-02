"""مرحله ۹: از رادار تا انتشار — فهرست‌ها، فیلترها، حذف تکراری آرشیو، کارت پیشنهاد، گزارش روزانه."""
from datetime import datetime, timedelta, timezone

import pytest

from musicbot.publishing import scheduler as sch
from musicbot.radar import report as rep
from musicbot.radar import suggest as S
from tests.conftest import ADMIN, make_context, make_update
from tests.helpers import buttons, cbs, txt
from tests.test_radar import Clock, T0, click, default_route, make, say

NOW = T0


def route(request):
    u = str(request.url)
    import httpx

    if "applemarketingtools" in u:
        return httpx.Response(200, json={"feed": {"results": [
            {"id": "1", "name": "Shab", "artistName": "علی", "url": "https://music.apple.com/1", "releaseDate": "2026-10-30"},
            {"id": "2", "name": "Rain", "artistName": "Bob", "url": "https://music.apple.com/2", "releaseDate": "2026-05-01"},
            {"id": "3", "name": "Old", "artistName": "Cat", "url": "https://music.apple.com/3"}]}})
    return default_route(request)


@pytest.fixture
def ready(app_ctx):
    clock = Clock()
    svc, net = make(app_ctx, route=route, clock=clock, yt=False, lf=False)
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    return clock, svc, net


async def fetch(app_ctx):
    await app_ctx.radar.refresh_all(force=True)


async def test_items_unique_kind_and_sync(app_ctx, ready):
    await fetch(app_ctx)
    items = S.build_items(app_ctx)
    by = {i.title: i for i in items}
    assert by["Shab"].kind == "iran" and by["Rain"].kind == "foreign"
    assert by["Shab"].sug["license_status"] == "official_link"             # فقط لینک رسمی؛ مجوز فایل نیست
    assert len({i.key for i in items}) == len(items)
    S.build_items(app_ctx)                                                 # همگام‌سازی دوباره تکراری نمی‌سازد
    assert sum(app_ctx.repos.radar.suggestion_counts().values()) == len(items)


async def test_license_unknown_for_manual_without_link(app_ctx, ready):
    app_ctx.repos.radar.add_manual("Hidden", "Zed", None, None)
    app_ctx.repos.radar.add_manual("Linked", "Zed", "https://example.org/x", None)
    await fetch(app_ctx)
    got = {i.title: i.sug for i in S.build_items(app_ctx)}
    assert got["Hidden"]["license_status"] == "unknown" and got["Hidden"]["status"] == "new"
    assert got["Shab"]["license_status"] == "official_link"


async def test_upsert_never_overwrites_admin_choices(app_ctx, ready):
    await fetch(app_ctx)
    it = S.build_items(app_ctx)[0]
    r = app_ctx.repos.radar
    r.set_suggestion(it.sug["id"], status="rejected", kind="iran" if it.kind == "foreign" else "foreign", kind_override=1,
                     license_status="licensed_by_admin", license_note="x")
    again = {i.key: i for i in S.build_items(app_ctx)}[it.key]
    assert again.sug["status"] == "rejected" and again.sug["license_status"] == "licensed_by_admin" and again.sug["kind_override"] == 1
    assert again.kind == again.sug["kind"] != it.kind


async def test_rejected_and_archive_dupes_hidden(app_ctx, ready):
    await fetch(app_ctx)
    items = S.build_items(app_ctx)
    assert {"Shab", "Rain", "Old"} <= {i.title for i in S.discoverable(items)}
    app_ctx.repos.radar.set_suggestion(next(i for i in items if i.title == "Rain").sug["id"], status="rejected")
    app_ctx.repos.songs.create(title="Shab", artist="علی", created_by=ADMIN)
    left = {i.title for i in S.discoverable(S.build_items(app_ctx))}
    assert "Rain" not in left and "Shab" not in left and "Old" in left


async def test_filters_and_groups(app_ctx, ready):
    await fetch(app_ctx)
    items = S.discoverable(S.build_items(app_ctx))
    f = dict(S.DEFAULT_FILTERS)
    names = lambda fl: {i.title for i in S.apply_filters(items, {**f, **fl}, NOW)}  # noqa: E731
    assert names({"kind": "iran"}) == {"Shab"}
    assert names({"lang": "latin"}) == {"Rain", "Old"}
    assert names({"fresh": "new"}) == {"Shab"}
    assert names({"window": "30"}) == {"Shab"}                           # تاریخ نامشخص کنار گذاشته می‌شود
    assert names({"country": "zz"}) == set()
    assert [i.title for i in S.group_items("ir", items, NOW)] == ["Shab"]
    assert "Shab" in {i.title for i in S.group_items("new", items, NOW)} and "Old" not in {i.title for i in S.group_items("new", items, NOW)}
    S.save_filters(app_ctx, {**f, "kind": "iran"})
    assert S.load_filters(app_ctx)["kind"] == "iran" and "نوع" in S.active_filters_text(S.load_filters(app_ctx))
    app_ctx.repos.settings.set("radar_filters", "{broken")
    assert S.load_filters(app_ctx) == f


def test_language_guess():
    assert S.guess_language("شب", None) == "fa" and S.guess_language("Şarkı", "x") == "tr" and S.guess_language("Night", "Bob") == "latin"


async def test_ensure_song_creates_fileless_once(app_ctx, ready):
    await fetch(app_ctx)
    it = next(i for i in S.build_items(app_ctx) if i.title == "Shab")
    sid, how = S.ensure_song(app_ctx, it.sug, ADMIN)
    assert how == "created"
    song = app_ctx.repos.songs.get(sid)
    assert song["telegram_file_id"] is None and song["language_code"] == "fa"
    sug = app_ctx.repos.radar.get_suggestion(it.sug["id"])
    assert S.ensure_song(app_ctx, sug, ADMIN) == (sid, "linked")
    app_ctx.repos.radar.set_suggestion(sug["id"], song_id=None)
    assert S.ensure_song(app_ctx, app_ctx.repos.radar.get_suggestion(sug["id"]), ADMIN) == (sid, "existing_link")


# ---------- رابط ----------
async def test_hub_groups_and_stranger(app_ctx, ready):
    await fetch(app_ctx)
    c = make_context(app_ctx)
    u = await click(c, "m:radar")
    assert {"x:gl:ir:0", "x:gl:fo:0", "x:gl:new:0", "x:gl:grow:0"} <= cbs(u)
    u = await click(c, "x:gl:ir:0")
    assert "Shab" in txt(u) and "Rain" not in txt(u)
    u = await click(c, "x:gl:fo:0", user=555)
    assert u.callback_query.edit_message_text.call_args is None or "Rain" not in txt(u)


async def test_filter_cycle_and_reset(app_ctx, ready):
    await fetch(app_ctx)
    c = make_context(app_ctx)
    await click(c, "x:fc:kind")
    assert S.load_filters(app_ctx)["kind"] == "iran"
    u = await click(c, "x:gl:top:0") if False else await click(c, "x:gl:fo:0")
    assert "Shab" not in txt(u)
    await click(c, "x:fr")
    assert S.load_filters(app_ctx) == S.DEFAULT_FILTERS
    u = await click(c, "x:fc:bogus")
    assert S.load_filters(app_ctx) == S.DEFAULT_FILTERS


async def test_card_actions_never_publish(app_ctx, ready):
    from unittest.mock import AsyncMock

    bot = type("B", (), {"send_audio": AsyncMock(), "send_message": AsyncMock()})()
    await fetch(app_ctx)
    c = make_context(app_ctx)
    it = next(i for i in S.build_items(app_ctx) if i.title == "Rain")
    sid = it.sug["id"]
    u = await click(c, f"x:sg:{sid}")
    t = txt(u)
    assert "Rain" in t and "مجوز" in t and "فایل" in t
    assert {f"x:sa:{sid}:{a}" for a in ("sv", "rj", "ar", "cp", "dr", "kd", "lc")} <= cbs(u)
    assert any(getattr(b, "url", None) == "https://music.apple.com/2" for b in buttons(u))
    await click(c, f"x:sa:{sid}:sv")
    assert app_ctx.repos.radar.get_suggestion(sid)["status"] == "saved"
    await click(c, f"x:sa:{sid}:kd")
    g = app_ctx.repos.radar.get_suggestion(sid)
    assert g["kind"] == "iran" and g["kind_override"] == 1
    u = await click(c, f"x:sa:{sid}:dr")
    g = app_ctx.repos.radar.get_suggestion(sid)
    assert g["status"] == "drafted" and g["song_id"]
    song = app_ctx.repos.songs.get(g["song_id"])
    assert song["status"] != "published" and "منتشر نمی‌شود" in txt(u)
    assert bot.send_audio.call_count == 0 and bot.send_message.call_count == 0
    await click(c, f"x:sa:{sid}:rj")
    assert app_ctx.repos.radar.get_suggestion(sid)["status"] == "rejected"
    u = await click(c, f"x:sa:{sid}:un")
    assert app_ctx.repos.radar.get_suggestion(sid)["status"] == "new"
    await click(c, f"x:sa:{sid}:nope")
    assert app_ctx.repos.radar.get_suggestion(sid)["status"] == "new"


async def test_archive_action_and_dup_limits(app_ctx, ready):
    await fetch(app_ctx)
    c = make_context(app_ctx)
    it = next(i for i in S.build_items(app_ctx) if i.title == "Old")
    sid = it.sug["id"]
    await click(c, f"x:sa:{sid}:ar")
    assert app_ctx.repos.radar.get_suggestion(sid)["status"] == "in_archive"
    assert app_ctx.repos.songs.find_by_norm(S.normalize("Old"), S.normalize("Cat"))
    other = next(i for i in S.build_items(app_ctx) if i.title == "Rain").sug["id"]
    app_ctx.repos.songs.create(title="Rain", artist="Bob", created_by=ADMIN)             # از راه دیگری وارد آرشیو شد
    u = await click(c, f"x:sg:{other}")
    assert f"x:sa:{other}:dr" not in cbs(u) and f"x:sa:{other}:ar" not in cbs(u) and "از قبل در آرشیو" in txt(u)


async def test_license_note_flow(app_ctx, ready):
    await fetch(app_ctx)
    c = make_context(app_ctx)
    sid = next(i for i in S.build_items(app_ctx) if i.title == "Rain").sug["id"]
    await click(c, f"x:sa:{sid}:lc")
    assert c.user_data["awaiting"] == f"xl:{sid}"
    await say(c, "اجازه‌ی کتبی ناشر")
    g = app_ctx.repos.radar.get_suggestion(sid)
    assert g["license_status"] == "licensed_by_admin" and g["license_note"] == "اجازه‌ی کتبی ناشر"
    await click(c, f"x:sa:{sid}:lx")
    assert app_ctx.repos.radar.get_suggestion(sid)["license_status"] == "official_link"


async def test_report_panel_toggle_time(app_ctx, ready):
    await fetch(app_ctx)
    c = make_context(app_ctx)
    st = app_ctx.repos.settings
    u = await click(c, "x:dr")
    assert "x:drt" in cbs(u)
    await click(c, "x:drt")
    assert st.get("radar_report_on") == "1"
    await click(c, "x:drh")
    await say(c, "25:99")
    assert st.get("radar_report_time", "09:30") == "09:30"
    c.user_data["awaiting"] = "xt"
    await say(c, "07:45")
    assert st.get("radar_report_time") == "07:45"
    u = await click(c, "x:drp")
    assert "پیشنهادهای موسیقی امروز" in txt(u)
    assert all(not r["reported_at"] for r in app_ctx.repos.db.fetchall("SELECT reported_at FROM radar_suggestions"))   # پیش‌نمایش علامت نمی‌زند


# ---------- گزارش و زمان‌بند ----------
async def test_build_report_content_and_repeat_suppression(app_ctx, ready):
    await fetch(app_ctx)
    now = T0
    text = rep.build_report(app_ctx, now, mark=False)
    for needle in ("موسیقی ایرانی", "موسیقی خارجی", "Shab", "Rain", "منبع و رتبه", "کشور نمودار", "لینک منبع", "آخرین به‌روزرسانی", "مجوز فایل نامشخص"):
        assert needle in text, needle
    assert rep.build_report(app_ctx, now, mark=False) == text
    rep.build_report(app_ctx, now)                                      # علامت می‌خورد
    second = rep.build_report(app_ctx, now + timedelta(hours=24))
    assert second is None or "Shab" not in second
    later = rep.build_report(app_ctx, now + timedelta(days=rep.REPEAT_DAYS + 1), mark=False)
    assert later and "Shab" in later


def test_build_report_none_when_empty(app_ctx):
    make(app_ctx, yt=False, lf=False)
    assert rep.build_report(app_ctx, T0) is None


async def test_build_report_mentions_source_errors(app_ctx):
    import httpx

    make(app_ctx, route=lambda r: httpx.Response(500), yt=False, lf=False)
    app_ctx.repos.radar.set_enabled("apple_most_played", True)
    await app_ctx.radar.refresh_all(force=True)
    text = rep.build_report(app_ctx, T0)
    assert text and "⚠️" in text


async def test_daily_report_rules(app_ctx, ready):
    from unittest.mock import AsyncMock

    bot = type("B", (), {"send_audio": AsyncMock(), "send_message": AsyncMock()})()
    await fetch(app_ctx)
    st = app_ctx.repos.settings
    tz = app_ctx.settings.tz
    day = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    assert await sch.daily_radar_report(app_ctx, bot, day) is False                  # پیش‌فرض خاموش
    st.set("radar_report_on", "1")
    st.set("radar_report_time", (day.astimezone(tz) + timedelta(hours=1)).strftime("%H:%M"))
    assert await sch.daily_radar_report(app_ctx, bot, day) is False                  # هنوز زمانش نرسیده
    st.set("radar_report_time", (day.astimezone(tz) - timedelta(hours=1)).strftime("%H:%M"))
    bot.send_message.side_effect = RuntimeError("down")
    assert await sch.daily_radar_report(app_ctx, bot, day) is False
    assert all(not r["reported_at"] for r in app_ctx.repos.db.fetchall("SELECT reported_at FROM radar_suggestions"))   # شکست ← علامت نمی‌خورد
    assert st.get("last_radar_report") in (None, "")
    bot.send_message.side_effect = None
    assert await sch.daily_radar_report(app_ctx, bot, day) is True
    assert bot.send_message.call_args.args[0] == ADMIN
    assert any(r["reported_at"] for r in app_ctx.repos.db.fetchall("SELECT reported_at FROM radar_suggestions"))
    n = bot.send_message.call_count
    assert await sch.daily_radar_report(app_ctx, bot, day + timedelta(minutes=5)) is False       # یک بار در روز
    assert bot.send_message.call_count == n
    assert bot.send_audio.call_count == 0


def test_suggest_and_report_cannot_send_or_download():
    from pathlib import Path

    root = Path(__file__).parent.parent / "musicbot"
    for f in ("radar/suggest.py", "radar/report.py"):
        t = (root / f).read_text()
        for banned in ("send_message", "send_audio", "send_document", "forward_message", "download_as_bytearray", "get_file", "yt_dlp"):
            assert banned not in t, (f, banned)
