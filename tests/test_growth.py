from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import Forbidden, TelegramError

from musicbot import growth_reports as GR
from musicbot import qr
from musicbot.db.repositories import GrowthRepo
from musicbot.handlers import growth as gh, menu
from tests.conftest import ADMIN, make_context, make_update
from tests.helpers import buttons, cbs, txt

U_BIG = 918273645          # شناسه‌ی نامعمول تا در جست‌وجوی «شناسه در دیتابیس» تصادف رخ ندهد
LINK = "https://t.me/+AbC123"


def member_event(old, new, link=None, user_id=U_BIG, is_bot=False, username="bia2music1395", chat_id=-100123):
    return SimpleNamespace(chat_member=SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, username=username), date=datetime.now(timezone.utc),
        old_chat_member=SimpleNamespace(status=old),
        new_chat_member=SimpleNamespace(status=new, user=SimpleNamespace(id=user_id, is_bot=is_bot)),
        invite_link=SimpleNamespace(invite_link=link) if link else None))


# ---------- ریپازیتوری ----------
def test_growth_repo_basics(repos):
    g = repos.growth
    a = g.create_campaign("instagram", "استوری", LINK, "استوری")
    assert g.campaign_by_link(LINK)["id"] == a and g.campaign_by_link("x") is None and g.campaign_by_link(None) is None
    with pytest.raises(ValueError):
        g.create_campaign("buy_fake_members", "x", None, None)         # نوع نامعتبر
    g.record("2026-11-01", a, joins=3); g.record("2026-11-01", a, leaves=1); g.record("2026-11-01", 0, joins=2)
    assert g.per_campaign(None) == {a: {"joins": 3, "leaves": 1}, 0: {"joins": 2, "leaves": 0}}
    assert not g.delete_campaign(a)                                     # فعال حذف نمی‌شود
    assert g.mark_revoked(a) and not g.mark_revoked(a)
    assert g.delete_campaign(a)
    assert g.per_campaign(None) == {0: {"joins": 5, "leaves": 1}}      # آمار به «نامشخص» منتقل شد؛ جمع کل حفظ شد
    assert g.totals(None) == {"joins": 5, "leaves": 1}


def test_campaign_limit(repos):
    for i in range(GrowthRepo.MAX_CAMPAIGNS):
        repos.growth.create_campaign("other", f"c{i}", f"l{i}", None)
    with pytest.raises(ValueError):
        repos.growth.create_campaign("other", "extra", "lx", None)


def test_daily_series_and_hashes(repos):
    g = repos.growth
    today = repos.metrics.today()
    g.record(today, 0, joins=2, leaves=1)
    d = g.daily(3)
    assert len(d) == 3 and d[-1] == {"day": today, "joins": 2, "leaves": 1} and d[0]["joins"] == 0
    g.remember_hash("h", 5, today)
    assert g.pop_hash("h") == 5 and g.pop_hash("h") is None
    g.remember_hash("h2", 5, today); g.clear_hashes()
    assert g.pop_hash("h2") is None


# ---------- رویداد عضویت ----------
async def test_join_attributed_to_campaign_and_meta(app_ctx):
    r = app_ctx.repos
    cid = r.growth.create_campaign("whatsapp", "گروه خانواده", LINK, "x")
    c = make_context(app_ctx)
    await gh.chat_member_update(member_event("left", "member", LINK), c)
    await gh.chat_member_update(member_event("left", "member", "https://t.me/+other"), c)    # لینکی که این ربات نساخته
    await gh.chat_member_update(member_event("left", "member", None), c)                       # از جست‌وجو/نام عمومی
    assert r.growth.per_campaign(None) == {cid: {"joins": 1, "leaves": 0}, 0: {"joins": 2, "leaves": 0}}
    m = GR.events_meta(app_ctx)
    assert m["total"] == 3 and m["with_link"] == 2 and m["last_at"]


async def test_leave_counted_unattributed_by_default(app_ctx):
    cid = app_ctx.repos.growth.create_campaign("friends", "دوستان", LINK, None)
    c = make_context(app_ctx)
    await gh.chat_member_update(member_event("left", "member", LINK), c)
    await gh.chat_member_update(member_event("member", "left"), c)
    await gh.chat_member_update(member_event("member", "kicked"), c)
    assert app_ctx.repos.growth.per_campaign(None) == {cid: {"joins": 1, "leaves": 0}, 0: {"joins": 0, "leaves": 2}}
    assert app_ctx.repos.db.fetchone("SELECT COUNT(*) c FROM member_hashes")["c"] == 0


async def test_leave_attributed_when_hashing_on_and_hash_removed(app_ctx):
    r = app_ctx.repos
    r.settings.set("growth_hash", "1")
    cid = r.growth.create_campaign("friends", "دوستان", LINK, None)
    c = make_context(app_ctx)
    await gh.chat_member_update(member_event("left", "member", LINK), c)
    assert r.db.fetchone("SELECT COUNT(*) c FROM member_hashes")["c"] == 1
    await gh.chat_member_update(member_event("member", "left"), c)
    assert r.growth.per_campaign(None)[cid] == {"joins": 1, "leaves": 1}
    assert r.db.fetchone("SELECT COUNT(*) c FROM member_hashes")["c"] == 0           # با خروج پاک شد
    await gh.chat_member_update(member_event("member", "left", user_id=1), c)         # خروج ناشناس
    assert r.growth.per_campaign(None)[0]["leaves"] == 1


async def test_no_personal_data_stored_anywhere(app_ctx):
    r = app_ctx.repos
    r.settings.set("growth_hash", "1")
    r.growth.create_campaign("friends", "دوستان", LINK, None)
    c = make_context(app_ctx)
    await gh.chat_member_update(member_event("left", "member", LINK), c)
    dump = ""
    for t in [x["name"] for x in r.db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")]:
        dump += " ".join(str(dict(row)) for row in r.db.fetchall(f"SELECT * FROM {t}"))
    assert str(U_BIG) not in dump                                                      # حتی هش، شناسه را فاش نمی‌کند


async def test_irrelevant_events_ignored(app_ctx):
    r = app_ctx.repos
    c = make_context(app_ctx)
    await gh.chat_member_update(member_event("left", "member", None, is_bot=True), c)           # ربات
    await gh.chat_member_update(member_event("member", "administrator"), c)                      # تغییر نقش
    await gh.chat_member_update(member_event("administrator", "member"), c)
    await gh.chat_member_update(member_event("member", "restricted"), c)
    assert r.growth.totals(None) == {"joins": 0, "leaves": 0}
    assert GR.events_meta(app_ctx)["total"] == 4                                                # رویداد «دریافت شد»
    await gh.chat_member_update(member_event("left", "member", None, username="othermusic"), c)  # کانال دیگر
    assert GR.events_meta(app_ctx)["total"] == 4
    await gh.chat_member_update(SimpleNamespace(chat_member=None), c)
    assert r.growth.totals(None) == {"joins": 0, "leaves": 0}


# ---------- منو و کمپین ----------
async def click(c, data, user=ADMIN):
    u = make_update(user_id=user, data=data)
    await (gh.growth_callback if data.startswith("r:") else menu.menu_callback)(u, c)
    return u


async def test_hub_honest_without_events(app_ctx):
    c = make_context(app_ctx)
    u = await click(c, "m:growth")
    t = txt(u)
    assert "اعضای فعلی: <b>22</b>" in t and "در دسترس نیست" in t and "عضو فیک" in t
    assert {"r:l", "r:rep", "r:ch", "r:cap", "r:hs"} <= cbs(u)
    assert app_ctx.repos.metrics.has_snapshot()


async def test_create_campaign_with_named_invite_link(app_ctx):
    r = app_ctx.repos
    c = make_context(app_ctx)
    kinds = [b.callback_data for b in buttons(await click(c, "r:n")) if b.callback_data.startswith("r:nk:")]
    assert set(kinds) == {f"r:nk:{k}" for k in GrowthRepo.KINDS} and len(kinds) == 7
    await click(c, "r:nk:instagram")
    assert c.user_data["awaiting"] == "grnew:instagram"
    long_name = "استوری اینستاگرام مهرماه با نام خیلی طولانی برای آزمون"
    u = make_update(text=long_name)
    await menu.text_router(u, c)
    kw = c.bot.create_chat_invite_link.call_args.kwargs
    assert kw["chat_id"] == "@bia2music1395" and len(kw["name"]) <= 32 and kw["name"] == long_name[:32]
    assert "creates_join_request" not in kw and "member_limit" not in kw                 # لینک ساده؛ بدون محدودیت و بدون درخواست
    camp = r.growth.list_campaigns()[0]
    assert camp["invite_link"] == LINK and camp["kind"] == "instagram" and camp["name"] == long_name[:40]
    assert LINK in txt(u) and "کلیک در دسترس نیست" in txt(u) and "در دسترس نیست" in txt(u)
    assert {f"r:qr:{camp['id']}", f"r:lk:{camp['id']}", f"r:rv:{camp['id']}"} <= cbs(u)


async def test_create_failure_and_limit(app_ctx):
    c = make_context(app_ctx)
    c.bot.create_chat_invite_link.side_effect = Forbidden("no rights")
    await click(c, "r:nk:ads")
    u = make_update(text="تبلیغ")
    await menu.text_router(u, c)
    assert "Invite Users" in txt(u) and app_ctx.repos.growth.list_campaigns() == []
    c.bot.create_chat_invite_link.side_effect = None
    for i in range(GrowthRepo.MAX_CAMPAIGNS):
        app_ctx.repos.growth.create_campaign("other", f"c{i}", f"l{i}", None)
    await click(c, "r:nk:other")
    u = make_update(text="یکی بیشتر")
    await menu.text_router(u, c)
    assert "حداکثر" in txt(u)
    object.__setattr__(app_ctx.settings, "channel_id", None)
    await click(c, "r:nk:other")
    assert "تنظیم نشده" in txt(await _say(c, "x"))


async def _say(c, text):
    u = make_update(text=text)
    await menu.text_router(u, c)
    return u


async def test_empty_and_invalid_names(app_ctx):
    c = make_context(app_ctx)
    await click(c, "r:nk:friends")
    assert "❌" in txt(await _say(c, "   "))
    assert not c.bot.create_chat_invite_link.called
    assert "نامعتبر" in txt(await click(c, "r:nk:buy_members"))


async def test_qr_and_link_actions(app_ctx):
    r = app_ctx.repos
    cid = r.growth.create_campaign("instagram", "استوری", LINK, "x")
    c = make_context(app_ctx)
    u = await click(c, f"r:qr:{cid}")
    kw = c.bot.send_photo.call_args.kwargs
    assert kw["chat_id"] == ADMIN and kw["photo"][:4] == b"\x89PNG" and LINK in kw["caption"] and "ارسال شد" in txt(u)
    assert LINK in txt(await click(c, f"r:lk:{cid}"))
    c.bot.send_photo.side_effect = TelegramError("x")
    assert "ممکن نشد" in txt(await click(c, f"r:qr:{cid}"))


async def test_qr_without_segno_falls_back_to_text(app_ctx, monkeypatch):
    monkeypatch.setattr(gh, "make_qr_png", lambda text: None)
    cid = app_ctx.repos.growth.create_campaign("instagram", "استوری", LINK, "x")
    c = make_context(app_ctx)
    u = await click(c, f"r:qr:{cid}")
    assert "pip install segno" in txt(u) and LINK in txt(u) and not c.bot.send_photo.called


def test_segno_missing_returns_none(monkeypatch):
    import builtins

    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == "segno" else real(n, *a, **k))
    assert qr.make_qr_png("x") is None


async def test_revoke_and_delete_flow(app_ctx):
    r = app_ctx.repos
    cid = r.growth.create_campaign("partner", "کانال همکار", LINK, "x")
    r.growth.record(r.metrics.today(), cid, joins=4)
    c = make_context(app_ctx)
    u = await click(c, f"r:rv:{cid}")
    assert "قابل بازگشت نیست" in txt(u) and not c.bot.revoke_chat_invite_link.called and r.growth.get_campaign(cid)["status"] == "active"
    c.bot.revoke_chat_invite_link.side_effect = TelegramError("no")
    assert "نپذیرفت" in txt(await click(c, f"r:rvy:{cid}")) and r.growth.get_campaign(cid)["status"] == "active"
    c.bot.revoke_chat_invite_link.side_effect = None
    u = await click(c, f"r:rvy:{cid}")
    kw = c.bot.revoke_chat_invite_link.call_args.kwargs
    assert kw == {"chat_id": "@bia2music1395", "invite_link": LINK} and r.growth.get_campaign(cid)["status"] == "revoked"
    assert "r:qr" not in "".join(cbs(u)) and f"r:del:{cid}" in cbs(u)
    assert "منتقل می‌شود" in txt(await click(c, f"r:del:{cid}"))
    await click(c, f"r:dy:{cid}")
    assert r.growth.get_campaign(cid) is None and r.growth.totals(None)["joins"] == 4
    assert "نامعتبر" in txt(await click(c, f"r:rv:{cid}"))


# ---------- گزارش‌ها ----------
async def test_report_without_events_is_honest(app_ctx):
    app_ctx.repos.growth.create_campaign("instagram", "استوری", LINK, None)
    c = make_context(app_ctx)
    t = txt(await click(c, "r:rep"))
    assert "عضویت کمپین‌ها: در دسترس نیست" in t and "کلیک لینک در دسترس نیست" in t and "ورود/خروج: در دسترس نیست" in t
    assert "0 عضو" not in t and "عضو جدید" not in t and "بهترین کمپین" not in t        # هیچ عددِ ساختگی نمی‌آید


async def test_report_with_events(app_ctx):
    r = app_ctx.repos
    a = r.growth.create_campaign("instagram", "استوری", LINK, None)
    b = r.growth.create_campaign("whatsapp", "گروه", "https://t.me/+zzz", None)
    c = make_context(app_ctx)
    for _ in range(3):
        await gh.chat_member_update(member_event("left", "member", LINK, user_id=1), c)
    await gh.chat_member_update(member_event("left", "member", "https://t.me/+zzz", user_id=2), c)
    await gh.chat_member_update(member_event("left", "member", None, user_id=3), c)
    await gh.chat_member_update(member_event("member", "left", user_id=3), c)
    r.metrics.snapshot_members(10, "2026-10-20"); r.metrics.snapshot_members(22, r.metrics.today())
    t = txt(await click(c, "r:rep"))
    assert "«استوری»: 3 عضو جدید" in t and "«گروه»: 1 عضو جدید" in t
    assert "بهترین کمپین:</b> 📸 اینستاگرام «استوری» با 3 عضو" in t and "بیشترین عضو آورده: 📸 اینستاگرام (3)" in t
    assert "منبع نامشخص/ارگانیک (بدون لینک): 1" in t
    assert "ورود 5 / خروج 1" in t and "خروج‌ها به‌تفکیک کمپین ثبت نمی‌شود" in t
    assert "کلیک لینک در دسترس نیست" in t and "UTC" in t
    assert "+5 ورود · −1 خروج" in txt(await click(c, "m:growth"))
    ch = txt(await click(c, "r:ch"))
    assert "نمودار رشد" in ch and "ورود" in ch and "خروج" in ch


async def test_chart_without_data(app_ctx):
    t = GR.chart_text(app_ctx)
    assert "هنوز داده‌ی کافی نیست" in t and "ورود/خروج روزانه: در دسترس نیست" in t


async def test_capability_screen_variants(app_ctx, bot):
    c = make_context(app_ctx)
    t = txt(await click(c, "r:cap"))
    assert "حق «Invite Users»" in t and "✅" in t and "هیچ رویداد عضویتی نیامده" in t and "آزمون" in t and "کلیک" in t
    bot.member.can_invite_users = False
    assert "❌ حق «Invite Users»" in txt(await click(c, "r:cap"))
    st = app_ctx.repos.settings
    st.set("ce_total", "5"); st.set("ce_with_link", "0"); st.set("ce_last_at", "2026-11-02T10:00:00Z")
    assert "منبع عضویت قابل شناسایی نیست" in txt(await click(c, "r:cap"))
    st.set("ce_with_link", "2")
    assert "عضویت هر کمپین قابل شمارش است" in txt(await click(c, "r:cap"))
    bot.chat.type = "supergroup"
    assert "کانال در دسترس نیست" in txt(await click(c, "r:cap"))


# ---------- حریم خصوصی: هش اختیاری ----------
async def test_hash_toggle_needs_confirmation_and_off_clears(app_ctx):
    r = app_ctx.repos
    c = make_context(app_ctx)
    u = await click(c, "r:hs")
    assert "r:hsy" in cbs(u) and "هش نمکی" in txt(u) and r.settings.get("growth_hash") is None
    await click(c, "r:hsy")
    assert r.settings.get("growth_hash") == "1"
    r.growth.remember_hash("x", 1, "2026-11-01")
    u = await click(c, "r:hs")
    assert r.settings.get("growth_hash") == "0" and r.db.fetchone("SELECT COUNT(*) c FROM member_hashes")["c"] == 0 and "پاک شدند" in txt(u)


async def test_stranger_cannot_use_growth(app_ctx):
    c = make_context(app_ctx)
    for data in ("r:l", "r:n", "r:rep", "r:hsy", "r:qr:1"):
        u = await click(c, data, user=555)
        u.callback_query.edit_message_text.assert_not_called()
    assert app_ctx.repos.settings.get("growth_hash") is None
    c.user_data["awaiting"] = "grnew:ads"
    u = make_update(user_id=555, text="تبلیغ")
    await menu.text_router(u, c)
    assert not c.bot.create_chat_invite_link.called


def test_app_registers_chat_member_handler():
    from telegram.ext import ChatMemberHandler

    from musicbot.app import build_application
    from musicbot.config import load_settings
    from tests.conftest import make_env
    import tempfile, pathlib

    d = pathlib.Path(tempfile.mkdtemp()) / "x.db"
    app = build_application(load_settings(make_env(DATABASE_PATH=str(d)), load_dotenv_file=False))
    assert any(isinstance(h, ChatMemberHandler) for hs in app.handlers.values() for h in hs)
