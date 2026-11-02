from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from telegram.error import BadRequest, Forbidden, TimedOut

from musicbot.publishing import captions as C
from musicbot.publishing import timeutil as TU
from musicbot.publishing.jalali import gregorian_to_jalali, jalali_to_gregorian, jalali_month_length
from musicbot.publishing.service import PublishError, post_url_for, publish_now, readiness_problems
from tests.conftest import ADMIN

TZ = ZoneInfo("Asia/Tehran")
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)  # 13:30 تهران


def test_jalali_known_dates_and_roundtrip():
    assert jalali_to_gregorian(1403, 1, 1) == date(2024, 3, 20)
    assert jalali_to_gregorian(1404, 1, 1) == date(2025, 3, 21)
    assert jalali_to_gregorian(1403, 12, 30) == date(2025, 3, 20)   # سال کبیسه
    assert gregorian_to_jalali(date(2026, 11, 2)) == (1405, 8, 11)
    d = date(2020, 1, 1)
    for _ in range(4000):
        assert jalali_to_gregorian(*gregorian_to_jalali(d)) == d
        d += timedelta(days=1)
    assert jalali_month_length(1404, 12) == 29
    with pytest.raises(ValueError):
        jalali_to_gregorian(1404, 12, 30)
    with pytest.raises(ValueError):
        jalali_to_gregorian(1404, 13, 1)


def test_parse_times():
    p = TU.parse_user_datetime("۲۱:۳۰", NOW, TZ)
    assert (p.hour, p.minute, p.day) == (21, 30, 2)
    assert TU.parse_user_datetime("13:00", NOW, TZ).day == 3          # گذشته ← فردا
    j = TU.parse_user_datetime("1405/08/20 21:30", NOW, TZ)
    assert j.date() == date(2026, 11, 11) and j.hour == 21
    g = TU.parse_user_datetime("2026-11-10 08:05", NOW, TZ)
    assert g.date() == date(2026, 11, 10)
    for bad in ("", "abc", "25:00", "12:99", "1405/13/01 10:00", "1405/12/30 10:00", "2026-02-30 10:00", "1400/01/01 10:00"):
        with pytest.raises(ValueError):
            TU.parse_user_datetime(bad, NOW, TZ)


def test_quick_times_and_format():
    assert TU.quick_time("h1", NOW, TZ).hour == 14
    assert TU.quick_time("t21", NOW, TZ).day == 2
    late = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)  # 21:30 تهران
    assert TU.quick_time("t21", late, TZ).day == 3
    assert TU.quick_time("m10", NOW, TZ).hour == 10
    iso = TU.to_iso(TU.quick_time("m21", NOW, TZ))
    assert TU.format_local(iso, TZ) == "1405/08/12 21:00"
    with pytest.raises(ValueError):
        TU.quick_time("zz", NOW, TZ)


def test_hashtags_and_caption():
    assert C.normalize_hashtags("#علی  پاپ, pop،#علی  بی کلام") == ["#علی", "#پاپ", "#pop", "#بی", "#کلام"]
    assert C.normalize_hashtags("!!! ###") == []
    song = {"caption": "متن", "hashtags": "#a #b", "title": "t", "artist": "a", "file_unique_id": "u"}
    assert C.final_caption(song) == "متن\n\n#a #b"
    fp = C.fingerprint(song)
    assert C.fingerprint({**song, "caption": "متن۲"}) != fp and C.fingerprint({**song, "hashtags": "#a"}) != fp
    assert C.fingerprint(dict(song)) == fp


async def test_ensure_caption(app_ctx, repos):
    sid = repos.songs.create(title="شب", artist="علی", telegram_file_id="f", file_unique_id="u")
    assert await C.ensure_caption(app_ctx, sid) is False        # قالب‌محور، AI واقعی نیست
    s = repos.songs.get(sid)
    assert "علی" in s["caption"] and "#Bia2Music" in s["hashtags"]
    repos.songs.update(sid, caption="دستی")
    assert await C.ensure_caption(app_ctx, sid) is None          # بازنویسی نمی‌کند
    assert repos.songs.get(sid)["caption"] == "دستی"
    await C.ensure_caption(app_ctx, sid, force=True)
    assert repos.songs.get(sid)["caption"] != "دستی"


def make_ready(repos, uid="u1", **over):
    sid = repos.songs.create(title="شب", artist="علی", telegram_file_id="FILE", file_unique_id=uid, duration_seconds=100)
    repos.songs.update(sid, language_code="fa", status="ready", caption="کپشن", hashtags="#a")
    if over:
        repos.songs.update(sid, **over)
    return sid


class Bot:
    def __init__(self, exc=None):
        self.sent, self.exc = [], exc

    async def send_audio(self, **kw):
        if self.exc:
            raise self.exc
        self.sent.append(kw)
        from types import SimpleNamespace
        return SimpleNamespace(message_id=77)


async def go(repos, bot, sid, ref="@bia2music1395", fp=None):
    fp = fp or C.fingerprint(repos.songs.get(sid))
    return await publish_now(bot, repos, ref, sid, ADMIN, fp)


async def test_publish_success_records_everything(repos):
    sid = make_ready(repos)
    bot = Bot()
    res = await go(repos, bot, sid)
    assert bot.sent[0]["chat_id"] == "@bia2music1395" and bot.sent[0]["caption"] == "کپشن\n\n#a"
    assert bot.sent[0]["audio"] == "FILE" and bot.sent[0]["title"] == "شب" and bot.sent[0]["performer"] == "علی"
    s = repos.songs.get(sid)
    assert s["status"] == "published" and s["channel_message_id"] == 77 and s["post_url"] == "https://t.me/bia2music1395/77"
    assert res.post_url == s["post_url"]
    row = repos.db.fetchone("SELECT * FROM publication_queue WHERE status='published'")
    assert row["approved_by"] == ADMIN and row["approved_at"] and row["song_id"] == sid
    assert any(l["action"] == "song_published" for l in repos.logs.recent())


async def test_publish_twice_rejected(repos):
    sid = make_ready(repos)
    bot = Bot()
    await go(repos, bot, sid)
    with pytest.raises(PublishError, match="قبلاً منتشر"):
        await go(repos, bot, sid)
    assert len(bot.sent) == 1


async def test_publish_rejects_stale_fingerprint(repos):
    sid = make_ready(repos)
    old = C.fingerprint(repos.songs.get(sid))
    repos.songs.update(sid, caption="تغییر کرد")
    bot = Bot()
    with pytest.raises(PublishError, match="تغییر کرده"):
        await go(repos, bot, sid, fp=old)
    assert not bot.sent and repos.songs.get(sid)["status"] == "ready"


@pytest.mark.parametrize("status", ["draft", "archived", "publishing"])
async def test_publish_requires_ready(repos, status):
    sid = make_ready(repos, status=status)
    bot = Bot()
    with pytest.raises(PublishError):
        await go(repos, bot, sid)
    assert not bot.sent


async def test_publish_blocked_by_problems(repos):
    bot = Bot()
    sid = make_ready(repos, caption="")
    with pytest.raises(PublishError, match="کپشن"):
        await go(repos, bot, sid, fp=C.fingerprint(repos.songs.get(sid)))
    sid2 = make_ready(repos, uid="u2", caption="x" * 1100)
    with pytest.raises(PublishError, match="1024"):
        await go(repos, bot, sid2)
    sid3 = make_ready(repos, uid="u3")
    repos.db.execute("UPDATE songs SET language_code=NULL WHERE id=?", (sid3,))
    with pytest.raises(PublishError, match="زبان"):
        await go(repos, bot, sid3)
    with pytest.raises(PublishError, match="تنظیم نشده"):
        await go(repos, bot, sid3, ref=None)
    assert not bot.sent
    assert readiness_problems(repos.songs.get(sid3))


@pytest.mark.parametrize("exc", [Forbidden("x"), BadRequest("y")])
async def test_definitive_failure_releases_claim(repos, exc):
    sid = make_ready(repos)
    with pytest.raises(PublishError):
        await go(repos, Bot(exc), sid)
    s = repos.songs.get(sid)
    assert s["status"] == "ready" and s["channel_message_id"] is None
    assert any(l["action"] == "publish_failed" for l in repos.logs.recent())


async def test_uncertain_failure_blocks_republish(repos):
    sid = make_ready(repos)
    with pytest.raises(PublishError) as e:
        await go(repos, Bot(TimedOut("t")), sid)
    assert e.value.uncertain and repos.songs.get(sid)["status"] == "publishing"
    bot = Bot()
    with pytest.raises(PublishError):
        await go(repos, bot, sid)       # دوباره ارسال نمی‌شود تا مدیر کانال را بررسی کند
    assert not bot.sent


async def test_scheduled_song_can_be_published_and_queue_cleared(repos):
    sid = make_ready(repos)
    repos.queue.schedule(sid, "@c", "2026-01-01T00:00:00Z")
    assert repos.songs.get(sid)["status"] == "scheduled"
    await go(repos, Bot(), sid)
    assert repos.queue.active_for_song(sid) is None
    assert repos.songs.get(sid)["status"] == "published"


def test_queue_repo(repos):
    a, b = make_ready(repos, "a"), make_ready(repos, "b")
    q1 = repos.queue.schedule(a, "@c", "2026-01-01T10:00:00Z")
    q2 = repos.queue.schedule(a, "@c", "2026-01-02T10:00:00Z")      # جایگزین قبلی
    repos.queue.schedule(b, "@c", "2026-01-01T09:00:00Z")
    assert [i["song_id"] for i in repos.queue.list_active()] == [b, a]
    assert repos.queue.active_for_song(a)["id"] == q2 != q1
    assert [i["song_id"] for i in repos.queue.due_pending("2026-01-01T12:00:00Z")] == [b]
    repos.queue.cancel_for_song(a)
    assert repos.songs.get(a)["status"] == "ready" and repos.queue.active_for_song(a) is None


def test_post_url():
    assert post_url_for("@x1234", 5) == "https://t.me/x1234/5"
    assert post_url_for("-1001234567", 5) == "https://t.me/c/1234567/5"
    assert post_url_for("weird", 5) is None
