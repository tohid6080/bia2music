import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from musicbot import reports
from musicbot.handlers import stats as stats_h
from musicbot.publishing import scheduler as sch
from musicbot.publishing.timeutil import to_iso, utc_now
from musicbot.ratelimit import RateLimiter
from tests.conftest import ADMIN, make_context
from tests.helpers import ready_song

TZ = ZoneInfo("Asia/Tehran")


# ---------- شمارنده‌ها و اعضا ----------
def test_metrics_counters_and_series(repos):
    m = repos.metrics
    m.incr("search"); m.incr("search", 2); m.incr("like")
    m.incr("search", 5, day="2000-01-01")                     # خارج از بازه
    assert m.totals(7) == {"search": 3, "like": 1}
    assert m.series("search", 3) == [0, 0, 3] and m.series("search", 1) == [3]
    assert m.series("nothing", 4) == [0, 0, 0, 0]


def test_metrics_store_no_identity(repos):
    cols = [r["name"] for r in repos.db.fetchall("PRAGMA table_info(daily_metrics)")]
    assert cols == ["day", "metric", "value"]


def test_member_snapshots_and_change(repos):
    m = repos.metrics
    assert m.members_change(7) is None and not m.has_snapshot()
    for day, n in (("2026-10-01", 100), ("2026-10-20", 110), ("2026-10-27", 115), ("2026-11-02", 130)):
        m.snapshot_members(n, day)
    m.snapshot_members(131, "2026-11-02")                        # همان روز: جایگزین می‌شود
    assert m.members_change(7) == 131 - 110 and m.members_change(30) == 131 - 100   # نزدیک‌ترین عکس «حداقل N روز قبل»
    assert m.members_change(90) is None
    assert [s["members"] for s in m.snapshots(10)] == [100, 110, 115, 131]


def test_reactions_top_posts_join_songs(repos):
    sid = ready_song(repos, status="published")
    repos.metrics.set_reactions(sid, 5)
    repos.metrics.set_reactions(999, 9)
    repos.metrics.set_reactions(sid, 7)                           # به‌روز می‌شود
    top = repos.metrics.top_posts(5)
    assert [t["reactions"] for t in top] == [9, 7] and top[1]["title"] == "شب" and top[0]["title"] is None


def test_ratelimiter():
    t = [0.0]
    rl = RateLimiter(3, 10, clock=lambda: t[0])
    assert [rl.allow(1) for _ in range(4)] == [True, True, True, False]
    assert rl.allow(2)                                            # کاربر دیگر جداست
    t[0] = 11
    assert rl.allow(1)


def test_db_backup_is_valid_copy(repos, tmp_path):
    repos.songs.create(title="a", artist="b", telegram_file_id="F", file_unique_id="U")
    out = tmp_path / "b.sqlite3"
    repos.db.backup(str(out))
    con = sqlite3.connect(out)
    assert con.execute("SELECT title FROM songs").fetchone()[0] == "a"
    assert con.execute("PRAGMA user_version").fetchone()[0] >= 4


def test_migration_v3_to_v4_keeps_data(tmp_path):
    from musicbot.db import Database, schema

    db = Database(tmp_path / "t.db")
    for v in (1, 2, 3):
        db._conn.executescript(schema.MIGRATIONS[v])
    db._conn.execute("PRAGMA user_version = 3")
    db.execute("INSERT INTO users(telegram_user_id,username) VALUES (5,'old')")
    db.execute("INSERT INTO playlists(name) VALUES ('p')")
    db.migrate()
    assert db.fetchone("PRAGMA user_version")[0] == max(schema.MIGRATIONS)
    assert dict(db.fetchone("SELECT username, premium_until FROM users")) == {"username": "old", "premium_until": None}
    assert db.fetchone("SELECT is_premium FROM playlists")[0] == 0


# ---------- پرداخت و اشتراک ----------
def test_premium_grant_extend_revoke(repos):
    p = repos.payments
    with pytest.raises(ValueError):
        p.grant(5, 30)                                            # کاربر ثبت نشده
    repos.users.touch(5, "u", "U", "fa")
    first = p.grant(5, 30)
    second = p.grant(5, 30)                                       # تمدید: از پایان فعلی ادامه می‌یابد
    assert p.is_premium(5) and second > first
    assert (datetime.strptime(second, "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(first, "%Y-%m-%dT%H:%M:%SZ")).days == 30
    p.revoke(5)
    assert not p.is_premium(5) and p.premium_until(5) is None


def test_premium_expired_not_active(repos):
    repos.users.touch(5, "u", "U", "fa")
    repos.db.execute("UPDATE users SET premium_until='2020-01-01T00:00:00Z' WHERE telegram_user_id=5")
    assert not repos.payments.is_premium(5)


def test_record_payment_idempotent_and_revenue(repos):
    p = repos.payments
    repos.users.touch(5, "u", "U", "fa")
    assert p.record(5, 100, 30, "C1", "pl") is not None
    assert p.record(5, 100, 30, "C1", "pl") is None               # همان شارژ دوباره
    assert p.revenue() == {"stars": 100, "count": 1, "stars_30d": 100, "active": 1}
    first = p.premium_until(5)
    p.record(5, 50, 10, "C2", "pl")
    assert p.premium_until(5) > first


def test_refund_reduces_subscription(repos):
    p = repos.payments
    repos.users.touch(5, "u", "U", "fa")
    p.record(5, 100, 30, "C1", "x")
    pid = p.recent(1)[0]["id"]
    assert p.mark_refunded(pid) and not p.mark_refunded(pid)
    assert not p.is_premium(5) and p.revenue()["stars"] == 0 and p.get(pid)["status"] == "refunded"


# ---------- کمپین ----------
def test_campaign_repo_lifecycle(repos):
    c = repos.campaigns
    cid = c.create("ad", "اسپانسر")
    with pytest.raises(ValueError):
        c.create("weird", "x")
    with pytest.raises(ValueError):
        c.update(cid, status="done")                              # وضعیت مستقیم قابل تغییر نیست
    c.update(cid, price=500, post_text="متن")
    assert c.claim_publishing(cid) and not c.claim_publishing(cid)
    assert not c.delete(cid)                                      # در حال انتشار حذف نمی‌شود
    c.release_claim(cid)
    assert c.claim_publishing(cid)
    c.mark_published(cid, 77, 40)
    got = c.get(cid)
    assert got["status"] == "active" and got["channel_message_id"] == 77 and got["members_start"] == 40 and got["starts_at"]
    assert not c.delete(cid) and not c.start(cid, 1)
    assert c.finish(cid, 55) and c.get(cid)["members_end"] == 55 and not c.finish(cid, 1)
    assert c.income() == {"total": 500, "count": 1, "last_30d": 500}
    assert c.delete(cid) and c.get(cid) is None


def test_campaign_endings_and_snooze(repos):
    c = repos.campaigns
    cid = c.create("collab", "همکار")
    c.start(cid, 10)
    c.update(cid, ends_at="2020-01-01T00:00:00Z")
    assert [x["id"] for x in c.due_endings("2026-01-01T00:00:00Z")] == [cid]
    c.mark_reminded(cid)
    assert c.due_endings("2026-01-01T00:00:00Z") == []
    c.snooze_end(cid, "2020-01-02T00:00:00Z")
    assert len(c.due_endings("2026-01-01T00:00:00Z")) == 1


# ---------- گزارش‌ها ----------
def test_overview_and_tips(app_ctx):
    r = app_ctx.repos
    ready_song(r, "a", status="published"); ready_song(r, "b")
    r.metrics.incr("search", 4)
    r.metrics.snapshot_members(100, "2026-10-20"); r.metrics.snapshot_members(120, "2026-11-02")
    t = reports.overview(app_ctx, 120)
    assert "120" in t and "+20" in t and "جست‌وجو: 4" in t and "منتشرشده 1" in t and "بازدید" in t     # توضیح محدودیت بازدید
    tips = " ".join(reports.growth_tips(app_ctx))
    assert "امکانات کاربران خاموش" in tips and "آماده" in tips
    assert "رشد اعضا" in reports.growth_chart(app_ctx)
    assert "هنوز داده" in reports.growth_chart(make_ctx_fresh(app_ctx))


def make_ctx_fresh(ctx):
    ctx.repos.db.execute("DELETE FROM member_snapshots")
    return ctx


def test_promo_text_and_spark():
    assert "@Tohidmusic_bot" in reports.promo_post_text("Tohidmusic_bot")
    assert reports.spark([0, 0]) == "▁▁" and reports.spark([1, 8])[-1] == "█"


def test_weekly_text_includes_premium_when_on(app_ctx):
    app_ctx.repos.settings.set("premium_enabled", "1")
    assert "مشترکین فعال" in reports.weekly(app_ctx, 50) and "گزارش هفتگی" in reports.weekly(app_ctx, None)


# ---------- شمارش واکنش ----------
async def test_reaction_count_handler(app_ctx):
    c = make_context(app_ctx)

    def upd(username, mid, counts):
        return SimpleNamespace(message_reaction_count=SimpleNamespace(
            chat=SimpleNamespace(id=-100, username=username), message_id=mid, reactions=[SimpleNamespace(total_count=n) for n in counts]))

    await stats_h.reaction_count(upd("bia2music1395", 5, [3, 2]), c)
    await stats_h.reaction_count(upd("Bia2Music1395", 6, [1]), c)       # حروف بزرگ/کوچک
    await stats_h.reaction_count(upd("othermusic", 7, [9]), c)          # کانال دیگر نادیده
    await stats_h.reaction_count(SimpleNamespace(message_reaction_count=None), c)
    assert {t["mid"]: t["reactions"] for t in app_ctx.repos.metrics.top_posts(10)} == {5: 5, 6: 1}


# ---------- زمان‌بند ----------
async def test_daily_snapshot_once(app_ctx):
    assert await sch.snapshot_members_daily(app_ctx) is True
    assert app_ctx.repos.metrics.snapshots()[-1]["members"] == 22
    assert await sch.snapshot_members_daily(app_ctx) is False


def saturday(hour):
    d = datetime(2026, 11, 2, tzinfo=TZ)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=0)


async def test_weekly_report_rules(app_ctx):
    c = make_context(app_ctx)
    st = app_ctx.repos.settings
    assert await sch.weekly_report(app_ctx, c.bot, saturday(10)) is False           # خاموش
    st.set("weekly_report", "1")
    assert await sch.weekly_report(app_ctx, c.bot, saturday(8)) is False             # زود
    assert await sch.weekly_report(app_ctx, c.bot, saturday(10) + timedelta(days=1)) is False   # روز اشتباه
    c.bot.send_message.side_effect = RuntimeError("down")
    assert await sch.weekly_report(app_ctx, c.bot, saturday(10)) is False and st.get("last_weekly_report") is None
    c.bot.send_message.side_effect = None
    assert await sch.weekly_report(app_ctx, c.bot, saturday(10)) is True
    assert c.bot.send_message.call_args.args[0] == ADMIN and "گزارش هفتگی" in c.bot.send_message.call_args.args[1]
    assert await sch.weekly_report(app_ctx, c.bot, saturday(11)) is False            # همان روز فقط یک‌بار


async def test_campaign_end_reminders_only_notify(app_ctx):
    r = app_ctx.repos
    cid = r.campaigns.create("ad", "اسپانسر")
    r.campaigns.update(cid, post_text="x")
    r.campaigns.claim_publishing(cid); r.campaigns.mark_published(cid, 9, 30)
    r.campaigns.update(cid, ends_at="2020-01-01T00:00:00Z")
    c = make_context(app_ctx)
    c.bot.send_message.side_effect = RuntimeError("x")
    assert await sch.notify_campaign_endings(app_ctx, c.bot) == 0 and r.campaigns.due_endings(to_iso(utc_now()))
    c.bot.send_message.side_effect = None
    assert await sch.notify_campaign_endings(app_ctx, c.bot) == 1
    args = c.bot.send_message.call_args
    assert args.args[0] == ADMIN and "حذف کنید (ربات حذف نمی‌کند)" in args.args[1]
    assert r.campaigns.get(cid)["status"] == "active"                               # خودکار پایان نمی‌یابد
    assert not c.bot.send_audio.called
    assert await sch.notify_campaign_endings(app_ctx, c.bot) == 0
