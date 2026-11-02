import re
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from musicbot import growth_plan as GP
from musicbot import growth_texts as GT
from musicbot.handlers import growth_content as gc, menu
from musicbot.publishing import scheduler as sch
from tests.conftest import ADMIN, make_context, make_update
from tests.helpers import buttons, cbs, ready_song, txt

TZ = ZoneInfo("Asia/Tehran")
LINK = "https://t.me/+AbC123"


def saturday(hour=10, week_offset=0):
    d = datetime(2026, 11, 2, tzinfo=TZ)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return (d + timedelta(weeks=week_offset)).replace(hour=hour, minute=0)


def publish_n(repos, n, prefix="p"):
    ids = []
    for i in range(n):
        sid = repos.songs.create(title=f"آهنگ{i}", artist=f"خواننده{i}", telegram_file_id="F", file_unique_id=f"{prefix}{i}")
        repos.songs.update(sid, status="published", language_code="fa", genre_id=1)
        ids.append(sid)
    return ids


# ---------- ریپازیتوری ----------
def test_text_repo_and_cap(repos):
    g = repos.gcontent
    first = g.add_text("whatsapp", 0, 0, "الف")
    assert g.get_text(first)["edited"] == 0
    g.edit_text(first, "ب")
    assert g.get_text(first)["text"] == "ب" and g.get_text(first)["edited"] == 1
    g.regenerate_text(first, 2, "ج")
    assert (g.get_text(first)["variant"], g.get_text(first)["edited"]) == (2, 0)
    for i in range(70):
        g.add_text("invite", 0, 0, f"t{i}")
    assert len(g.list_texts(100)) == g.MAX_TEXTS and g.get_text(first) is None      # قدیمی‌ها حذف می‌شوند
    g.delete_text(g.list_texts(1)[0]["id"])


def test_plan_repo_prunes(repos):
    for i in range(15):
        repos.gcontent.save_plan(f"2026-W{i + 10}", f"p{i}")
    repos.gcontent.save_plan("2026-W24", "updated")
    assert repos.gcontent.get_plan("2026-W24")["text"] == "updated" and repos.gcontent.get_plan("2026-W10") is None


def test_milestones_seed_edit_stage(repos):
    g = repos.gcontent
    assert [m["members"] for m in g.milestones()] == [22, 100, 500, 1000]
    assert g.stage(None) == {"current": None, "next": g.milestones()[0], "tier": 0}
    assert g.stage(10)["tier"] == 0 and g.stage(10)["current"] is None
    assert g.stage(22)["current"]["members"] == 22 and g.stage(22)["tier"] == 0 and g.stage(22)["next"]["members"] == 100   # ۲۲ = مرحله‌ی شروع
    assert g.stage(150)["tier"] == 1 and g.stage(600)["tier"] == 2 and g.stage(1000)["tier"] == 3 and g.stage(5000)["next"] is None
    mid = g.add_milestone(300, "جدید", None)
    assert g.stage(350)["current"]["members"] == 300
    with pytest.raises(Exception):
        g.add_milestone(300, "تکراری", None)
    for bad in (0, -5, 10**9):
        with pytest.raises(ValueError):
            g.add_milestone(bad, "x", None)
    g.update_milestone(mid, members=310, title="عنوان")
    with pytest.raises(ValueError):
        g.update_milestone(mid, members=0)
    with pytest.raises(ValueError):
        g.update_milestone(mid, id=5)
    assert g.delete_milestone(mid)
    for m in g.milestones()[1:]:
        assert g.delete_milestone(m["id"])
    assert not g.delete_milestone(g.milestones()[0]["id"])                           # حداقل یکی می‌ماند
    for i in range(g.MAX_MILESTONES - 1):
        g.add_milestone(1000 + i, "m", None)
    with pytest.raises(ValueError):
        g.add_milestone(99999, "x", None)


# ---------- موتور متن ----------
def test_texts_use_only_real_data(app_ctx):
    # بدون آهنگ: خط شمارش/نمونه نیامده و عددی ساخته نمی‌شود
    for kind in ("whatsapp", "instagram", "telegram", "partner", "invite"):
        for v in range(3):
            t, used = GT.generate(app_ctx, kind, 0, v)
            assert "https://t.me/bia2music1395" in t and used == v
            assert "آهنگ در آرشیو" not in t and "مثلاً" not in t and "نمونه:" not in t
            assert not re.search(r"\d{2,} (عضو|آهنگ)", t)
    publish_n(app_ctx.repos, 7)
    t, _ = GT.generate(app_ctx, "whatsapp", 0, 0)
    assert "7 آهنگ در آرشیو" in t and "خواننده6 - آهنگ6" in t                          # تازه‌ترین‌ها
    few = publish_n(app_ctx.repos, 0)
    assert len({GT.generate(app_ctx, "whatsapp", 0, v)[0] for v in range(3)}) == 3     # سه نسخه‌ی متفاوت
    assert GT.generate(app_ctx, "invite", 0, 5)[1] == 2                                  # چرخشی


def test_texts_threshold_for_count(app_ctx):
    publish_n(app_ctx.repos, 4)
    assert "آهنگ در آرشیو" not in GT.generate(app_ctx, "whatsapp", 0, 0)[0]            # کمتر از ۵: ادعای تعداد نمی‌شود


def test_instagram_hashtags_and_partner_honesty(app_ctx):
    publish_n(app_ctx.repos, 6)
    t, _ = GT.generate(app_ctx, "instagram", 0, 0)
    assert "#Bia2Music" in t and "#موزیک" in t and "#پاپ" in t and "بیو" in t
    for v in range(3):
        p, _ = GT.generate(app_ctx, "partner", 0, v)
        assert "بدون خرید عضو" in p or "تبادل" in p
        assert not re.search(r"\d+ عضو", p)                                              # عدد عضو ساخته نمی‌شود


def test_songs_text_needs_data_and_labels_honestly(app_ctx):
    with pytest.raises(GT.NoData):
        GT.generate(app_ctx, "songs", 0, 0)
    ids = publish_n(app_ctx.repos, 3)
    t, _ = GT.generate(app_ctx, "songs", 0, 0)
    assert "تازه‌ترین" in t and "محبوب‌ترین" not in t and "ترند" not in t                # بدون پسند، ادعای «محبوب» نمی‌شود
    app_ctx.repos.users.touch(5, "u", "U", "fa"); app_ctx.repos.userdata.give_consent(5)
    app_ctx.repos.userdata.toggle_like(5, ids[1])
    t, _ = GT.generate(app_ctx, "songs", 0, 0)
    assert "محبوب‌ترین" in t and "بر اساس پسند" in t and "خواننده1 - آهنگ1" in t


def test_link_resolution(app_ctx):
    r = app_ctx.repos
    cid = r.growth.create_campaign("instagram", "استوری", LINK, "x")
    assert GT.channel_link(app_ctx, cid) == LINK and LINK in GT.generate(app_ctx, "invite", cid, 0)[0]
    r.growth.mark_revoked(cid)
    with pytest.raises(GT.NoData):
        GT.generate(app_ctx, "invite", cid, 0)                                           # لینک ابطال‌شده درج نمی‌شود
    object.__setattr__(app_ctx.settings, "channel_id", "-1001234567")
    with pytest.raises(GT.NoData):
        GT.generate(app_ctx, "invite", 0, 0)                                              # کانال خصوصی بدون لینک عمومی
    with pytest.raises(ValueError):
        GT.generate(app_ctx, "sms", 0, 0)


# ---------- برنامه‌ی هفتگی ----------
def test_plan_without_data_is_honest(app_ctx):
    t = GP.build_plan(app_ctx, 22, saturday())
    assert "هیچ (هنوز داده‌ای نیست)" in t and "در دسترس نیست" in t and "تضمین" in t and "پیشنهاد آزمایشی" in t
    assert "مرحله: «مرحله شروع و آزمایش محتوا»" in t and "نقطه‌ی بعدی: 100" in t
    assert "علایق مخاطبان هنوز ثبت نشده" in t and "3 تا 4 پست" in t and "آزمایش 3:" in t
    assert "نام کانال خاصی را حدس نمی‌زنم" in t and "بازدید پست در دسترس ربات نیست" in t
    for banned in ("قطعاً", "حتماً زیاد", "بهترین زمان:", "افزایش می‌یابد", "تضمین می‌شود"):
        assert banned not in t


def test_plan_slots_deterministic_and_rotate():
    a = GP.experiment_slots(saturday())
    assert a == GP.experiment_slots(saturday()) and len(a) == 3
    assert GP.experiment_slots(saturday(week_offset=1)) != a
    assert len({s.split(" · ")[0] for s in a}) == 3                                        # سه روز متفاوت


def test_plan_uses_real_data(app_ctx):
    r = app_ctx.repos
    ids = publish_n(app_ctx.repos, 4)
    for uid in (11, 12):
        r.users.touch(uid, f"u{uid}", "U", "fa"); r.userdata.give_consent(uid)
        r.userdata.toggle_interest(uid, "genre", "2")
    r.userdata.toggle_interest(11, "mood", "3")
    r.userdata.toggle_like(11, ids[0])
    ready_song(r, "rd")                                                                    # فقط ۱ آماده
    r.metrics.snapshot_members(10, "2026-10-20"); r.metrics.snapshot_members(30, r.metrics.today())
    t = GP.build_plan(app_ctx, 30, saturday())
    assert "علایق ثبت‌شده‌ی مخاطبان (بر پایه‌ی 2 کاربر)" in t and "نمونه‌ی کوچک" in t and "سبک: رپ" in t
    assert "پرپسندترین‌ها: آهنگ0" in t
    assert "فقط 1 آهنگ «آماده‌ی انتشار»" in t
    assert "آرشیو منتشرشده (4)" in t and "علایق 2 کاربر" in t and "پسندها" in t
    assert "ترکیب فعلی آرشیو منتشرشده" in t


def test_plan_collab_history_and_exits(app_ctx):
    r = app_ctx.repos
    cid = r.campaigns.create("collab", "کانال شریک")
    r.campaigns.start(cid, 20); r.campaigns.finish(cid, 31)
    app_ctx.repos.settings.set("ce_total", "10")
    for _ in range(2):
        r.growth.record(r.metrics.today(), 0, joins=1)
    r.growth.record(r.metrics.today(), 0, leaves=4)
    t = GP.build_plan(app_ctx, 50, saturday())
    assert "«کانال شریک» +11 عضو" in t and "معلول همان همکاری نیست" in t
    assert "خروج بیشتر از ورود" in t and "ورود/خروج" in t.split("داده‌ی استفاده‌شده:")[1].split("\n")[0]


def test_plan_tier_changes_depth(app_ctx):
    low = GP.build_plan(app_ctx, 22, saturday())
    high = GP.build_plan(app_ctx, 1200, saturday())
    assert "3 تا 4 پست" in low and "5 تا 7 پست" in high
    assert "تنوع: در هفته حداقل ۲ سبک" in high and "تنوع: در هفته حداقل ۲ سبک" not in low
    assert "کدام زبان را بیشتر" in high and "کدام زبان را بیشتر" not in low


def test_split_message_respects_limit():
    text = "\n".join(f"خط {i} " + "ی" * 80 for i in range(120))
    parts = GP.split_message(text, 1000)
    assert len(parts) > 1 and all(len(p) <= 1000 for p in parts) and "\n".join(parts).count("خط") == 120


# ---------- هندلرها ----------
async def click(c, data, user=ADMIN):
    u = make_update(user_id=user, data=data)
    await (gc.content_callback if data.startswith("w:") else menu.menu_callback)(u, c)
    return u


async def say(c, text, user=ADMIN):
    u = make_update(user_id=user, text=text)
    await menu.text_router(u, c)
    return u


async def test_text_generation_flow(app_ctx):
    publish_n(app_ctx.repos, 6)
    c = make_context(app_ctx)
    u = await click(c, "m:growth")
    assert {"w:tx", "w:pl", "w:ms"} <= cbs(u)
    u = await click(c, "w:tx")
    assert len([x for x in cbs(u) if x.startswith("w:k:")]) == 6
    u = await click(c, "w:k:whatsapp")
    assert "w:g:whatsapp:0" in cbs(u)
    u = await click(c, "w:g:whatsapp:0")
    tid = app_ctx.repos.gcontent.list_texts(1)[0]["id"]
    t = txt(u)
    assert "<code>" in t and "https://t.me/bia2music1395" in t and "کپی" in t and "ارسال انبوه ناخواسته ممنوع" in t
    assert {f"w:e:{tid}", f"w:n:{tid}", f"w:d:{tid}"} <= cbs(u)
    assert not c.bot.send_message.called                                                   # ربات چیزی نمی‌فرستد
    # ویرایش
    await click(c, f"w:e:{tid}")
    assert c.user_data["awaiting"] == f"wtx:{tid}"
    u = await say(c, "متن ویرایش‌شده‌ی من 🌹")
    assert "متن ویرایش‌شده‌ی من" in txt(u) and "ویرایش‌شده" in txt(u) and app_ctx.repos.gcontent.get_text(tid)["edited"] == 1
    # نسخه‌ی دیگر: چون ویرایش شده، تأیید می‌خواهد
    u = await click(c, f"w:n:{tid}")
    assert "جایگزین می‌کند" in txt(u) and app_ctx.repos.gcontent.get_text(tid)["text"] == "متن ویرایش‌شده‌ی من 🌹"
    u = await click(c, f"w:ny:{tid}")
    row = app_ctx.repos.gcontent.get_text(tid)
    assert row["variant"] == 1 and row["edited"] == 0 and "نسخه 2" in txt(u)
    u = await click(c, f"w:n:{tid}")                                                       # بدون ویرایش: مستقیم
    assert app_ctx.repos.gcontent.get_text(tid)["variant"] == 2
    assert "w:v:" in "".join(cbs(await click(c, "w:l")))
    await click(c, f"w:d:{tid}")
    assert app_ctx.repos.gcontent.get_text(tid) is None


async def test_text_edit_validation_and_missing(app_ctx):
    tid = app_ctx.repos.gcontent.add_text("invite", 0, 0, "x")
    c = make_context(app_ctx)
    await click(c, f"w:e:{tid}")
    assert "❌" in txt(await say(c, "ی" * 4500)) and c.user_data["awaiting"] == f"wtx:{tid}"
    for bad in ("w:v:999", "w:e:999", "w:n:999", "w:k:sms", "w:zzz", "w:v:abc"):
        t = txt(await click(c, bad))
        assert "نامعتبر" in t or "پیدا نشد" in t, bad


async def test_campaign_link_choice_and_nodata(app_ctx):
    r = app_ctx.repos
    cid = r.growth.create_campaign("instagram", "استوری مهر", LINK, "x")
    r.growth.create_campaign("friends", "ابطال‌شده", "https://t.me/+zzz", "y")
    r.growth.mark_revoked(2)
    c = make_context(app_ctx)
    u = await click(c, "w:k:invite")
    assert f"w:g:invite:{cid}" in cbs(u) and "w:g:invite:2" not in cbs(u)
    u = await click(c, f"w:g:invite:{cid}")
    assert LINK in txt(u)
    assert "هنوز آهنگ منتشرشده" in txt(await click(c, "w:g:songs:0"))


async def test_plan_screens_and_toggle(app_ctx):
    c = make_context(app_ctx)
    u = await click(c, "w:pl")
    assert "برنامه‌ی پیشنهادی رشد" in txt(u)
    week = GP.week_key(gc.now_local(app_ctx))
    assert app_ctx.repos.gcontent.get_plan(week)
    app_ctx.repos.gcontent.save_plan(week, "<b>قدیمی</b>")
    assert "قدیمی" in txt(await click(c, "w:pl"))                                           # از ذخیره
    assert "برنامه‌ی پیشنهادی رشد" in txt(await click(c, "w:pr"))                             # دوباره ساخته شد
    assert any("⛔" not in b.text and "ارسال خودکار" in b.text for b in buttons(await click(c, "w:pl")))
    await click(c, "w:pw")
    assert app_ctx.repos.settings.get("weekly_plan") == "0"
    assert not c.bot.send_message.called and not c.bot.send_audio.called


async def test_milestone_screens_and_edits(app_ctx):
    r = app_ctx.repos
    c = make_context(app_ctx)
    u = await click(c, "w:ms")
    t = txt(u)
    assert "✅ 22" in t and "⬜ 100" in t and "هیچ انتشار خودکاری فعال نمی‌شود" in t and "تا نقطه‌ی بعد (100): 78 عضو" in t
    await click(c, "w:mn")
    assert "قالب: تعداد | عنوان | یادداشت" in txt(await say(c, "فقط عنوان"))
    assert "❌" in txt(await say(c, "abc | عنوان"))
    assert "❌" in txt(await say(c, "22 | تکراری"))
    u = await say(c, "۳۰۰ | همکاری‌ها | یادداشت من")
    assert "⬜ 300" in txt(u)                                                                 # ۲۲ عضو؛ هنوز به ۳۰۰ نرسیده
    mid = [m for m in r.gcontent.milestones() if m["members"] == 300][0]["id"]
    for f, val, check in (("m", "310", lambda m: m["members"] == 310), ("t", "عنوان تازه", lambda m: m["title"] == "عنوان تازه"),
                          ("n", "-", lambda m: m["note"] is None)):
        await click(c, f"w:me:{mid}:{f}")
        await say(c, val)
        assert check(r.gcontent.get_milestone(mid)), f
    await click(c, f"w:me:{mid}:m")
    assert "❌" in txt(await say(c, "100")) and r.gcontent.get_milestone(mid)["members"] == 310       # تکراری
    assert "حذف شود" in txt(await click(c, f"w:md:{mid}")) and r.gcontent.get_milestone(mid)
    await click(c, f"w:mdy:{mid}")
    assert r.gcontent.get_milestone(mid) is None
    assert "نامعتبر" in txt(await click(c, "w:me:999:m"))


async def test_stranger_cannot_use_content(app_ctx):
    c = make_context(app_ctx)
    for data in ("w:tx", "w:g:invite:0", "w:pl", "w:pw", "w:ms", "w:mn"):
        u = await click(c, data, user=555)
        u.callback_query.edit_message_text.assert_not_called()
    c.user_data["awaiting"] = "wms:new"
    await say(c, "500 | x", user=555)
    assert len(app_ctx.repos.gcontent.milestones()) == 4 and app_ctx.repos.settings.get("weekly_plan") is None


# ---------- زمان‌بند ----------
async def test_weekly_plan_job_rules(app_ctx):
    c = make_context(app_ctx)
    st = app_ctx.repos.settings
    assert await sch.weekly_plan(app_ctx, c.bot, saturday(8)) is False                        # زود
    assert await sch.weekly_plan(app_ctx, c.bot, saturday(10) + timedelta(days=1)) is False   # روز اشتباه
    c.bot.send_message.side_effect = RuntimeError("down")
    assert await sch.weekly_plan(app_ctx, c.bot, saturday(10)) is False and st.get("last_weekly_plan") is None
    c.bot.send_message.side_effect = None
    assert await sch.weekly_plan(app_ctx, c.bot, saturday(10)) is True
    assert all(call.args[0] == ADMIN for call in c.bot.send_message.call_args_list)
    assert "برنامه‌ی پیشنهادی رشد" in c.bot.send_message.call_args_list[0].args[1]
    assert await sch.weekly_plan(app_ctx, c.bot, saturday(11)) is False                      # یک‌بار در هفته
    assert await sch.weekly_plan(app_ctx, c.bot, saturday(10, 1)) is True                    # هفته‌ی بعد دوباره
    st.set("weekly_plan", "0")
    assert await sch.weekly_plan(app_ctx, c.bot, saturday(10, 2)) is False
    assert not c.bot.send_audio.called


async def test_milestone_notifications_message_only(app_ctx):
    r = app_ctx.repos
    c = make_context(app_ctx)
    assert await sch.notify_milestones(app_ctx, c.bot) == 0                                   # هنوز عکسی نیست
    song = ready_song(r)
    queue_before = r.db.fetchone("SELECT COUNT(*) c FROM publication_queue")["c"]
    r.metrics.snapshot_members(22, "2026-11-01")
    assert await sch.notify_milestones(app_ctx, c.bot) == 0                                   # اولین اجرا: پایه بی‌صدا
    assert r.settings.get("ms_notified") == "22" and not c.bot.send_message.called
    r.metrics.snapshot_members(104, "2026-11-02")
    c.bot.send_message.side_effect = RuntimeError("down")
    assert await sch.notify_milestones(app_ctx, c.bot) == 0 and r.settings.get("ms_notified") == "22"   # شکست ← دوباره تلاش
    c.bot.send_message.side_effect = None
    assert await sch.notify_milestones(app_ctx, c.bot) == 1
    args = c.bot.send_message.call_args
    assert args.args[0] == ADMIN and "به 100 عضو رسیدید" in args.args[1] and "هیچ انتشار خودکاری فعال نمی‌شود" in args.args[1]
    assert await sch.notify_milestones(app_ctx, c.bot) == 0                                   # دوباره نه
    # رسیدن به نقطه‌ی عطف هیچ‌چیز را منتشر یا تغییر نمی‌دهد
    assert not c.bot.send_audio.called and not c.bot.send_photo.called
    assert r.songs.get(song)["status"] == "ready" and r.db.fetchone("SELECT COUNT(*) c FROM publication_queue")["c"] == queue_before
    assert r.settings.get("auto_publish") is None
    r.gcontent.add_milestone(150, "نقطه‌ی من", "یادداشت")
    r.metrics.snapshot_members(160, "2026-11-03")
    assert await sch.notify_milestones(app_ctx, c.bot) == 1 and "نقطه‌ی من" in c.bot.send_message.call_args.args[1]


def test_content_modules_cannot_send_or_publish():
    from pathlib import Path

    root = Path(__file__).parent.parent / "musicbot"
    for f in ("growth_texts.py", "growth_plan.py", "handlers/growth_content.py"):
        t = (root / f).read_text()
        for banned in ("send_message", "send_audio", "send_photo", "send_document", "publish_now", "publish_ad_now", "forward_message", "claim_for_publishing"):
            assert banned not in t, (f, banned)
