import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, Forbidden, TelegramError, TimedOut

from musicbot.handlers import (admin_users as au, campaigns as ch, menu, playlists as plh, premium as ph, settings as sh,
                               stats as st, users as uh)
from musicbot.ratelimit import RateLimiter
from musicbot.publishing.service import ad_fingerprint
from tests.conftest import ADMIN, make_context, make_update
from tests.helpers import buttons, cbs, ready_song, txt

U1, U2 = 3001, 3002
ROUTE = {"d": ch.campaigns_callback, "v": ph.premium_callback, "u": uh.user_callback, "a": au.admin_users_callback,
         "t": st.stats_callback, "m": menu.menu_callback, "s": sh.settings_callback, "y": plh.playlists_callback}


async def click(c, data, user=ADMIN, from_audio=False):
    u = make_update(user_id=user, data=data, from_audio=from_audio)
    await ROUTE[data[0]](u, c)
    return u


async def say(c, text, user=ADMIN):
    u = make_update(user_id=user, text=text)
    await menu.text_router(u, c)
    return u


def new_campaign(repos, kind="ad", title="اسپانسر", text="متن تبلیغ", status=None):
    cid = repos.campaigns.create(kind, title)
    if kind == "ad":
        repos.campaigns.update(cid, post_text=text)
    return cid


# ======================= منوی آمار و ابزارهای رشد =======================
async def test_stats_screens(app_ctx):
    app_ctx.bot_username = "Tohidmusic_bot"
    c = make_context(app_ctx)
    u = await click(c, "m:stats")
    assert "اعضای کانال: <b>22</b>" in txt(u) and app_ctx.repos.metrics.has_snapshot()
    assert "t:g" in cbs(u) and "t:gr" in cbs(u)
    assert "هنوز داده" in txt(await click(c, "t:g"))
    u = await click(c, "t:gr")
    assert "ابزارهای رشد" in txt(u) and "https://t.me/Tohidmusic_bot" in txt(u)
    u = await click(c, "t:gp")
    assert "@Tohidmusic_bot" in txt(u) and "ربات خودکار منتشرش نمی‌کند" in txt(u)
    assert not c.bot.send_audio.called
    await click(c, "t:w")
    assert app_ctx.repos.settings.get("weekly_report") == "1"
    await click(c, "t:w")
    assert app_ctx.repos.settings.get("weekly_report") == "0"
    assert "نام کاربری ربات" in txt(await click(make_context(make_ctx_nouser(app_ctx)), "t:gp"))


def make_ctx_nouser(ctx):
    ctx.bot_username = None
    return ctx


async def test_stranger_cannot_open_stats_ads_premium(app_ctx):
    c = make_context(app_ctx)
    for data in ("t:o", "d:l:ad", "v:menu", "v:ty", "a:gp:1"):
        u = await click(c, data, user=U1)
        u.callback_query.edit_message_text.assert_not_called()
    assert app_ctx.repos.settings.get("premium_enabled") is None


# ======================= کمپین و پست تبلیغی =======================
async def test_hub_and_create_edit_ad(app_ctx):
    c = make_context(app_ctx)
    assert "تبلیغات و درآمدزایی" in txt(await click(c, "m:ads"))
    u = await click(c, "d:n:ad")
    assert c.user_data["awaiting"] == "cmpnew:ad"
    u = await say(c, "اسپانسر الف")
    cid = app_ctx.repos.campaigns.list("ad")[0]["id"]
    assert "اسپانسر الف" in txt(u) and f"d:pv:{cid}" in cbs(u)
    for field, text, check in (
        ("p", "متن تبلیغ من", lambda c_: c_["post_text"] == "متن تبلیغ من"),
        ("c", "۵۰۰٬۰۰۰", lambda c_: c_["price"] == 500000),
        ("b", "عضویت | t.me/example", lambda c_: (c_["button_label"], c_["button_url"]) == ("عضویت", "https://t.me/example")),
        ("k", "https://t.me/partner", lambda c_: c_["partner_link"] == "https://t.me/partner"),
        ("t", "@mychannel همکار", lambda c_: c_["title"] == "@mychannel همکار"),
        ("o", "یادداشت", lambda c_: c_["notes"] == "یادداشت"),
        ("n", "1405/12/20 21:30", lambda c_: c_["ends_at"] and c_["ends_at"].endswith("Z")),
    ):
        await click(c, f"d:e:{cid}:{field}")
        assert c.user_data["awaiting"] == f"cmp:{field}:{cid}"
        await say(c, text)
        assert check(app_ctx.repos.campaigns.get(cid)), field
    await click(c, f"d:e:{cid}:b")
    await say(c, "-")
    assert app_ctx.repos.campaigns.get(cid)["button_label"] is None


async def test_edit_validation(app_ctx):
    cid = new_campaign(app_ctx.repos)
    c = make_context(app_ctx)
    for field, bad in (("c", "abc"), ("b", "فقط متن"), ("b", "متن | ftp://x"), ("b", "x" * 50 + " | https://a.b"), ("s", "نامعتبر"),
                       ("p", "x" * 5000), ("t", "   ")):
        await click(c, f"d:e:{cid}:{field}")
        u = await say(c, bad)
        assert "❌" in txt(u) and c.user_data["awaiting"] == f"cmp:{field}:{cid}", (field, bad)
    assert app_ctx.repos.campaigns.get(cid)["price"] is None


async def test_collab_has_no_ad_fields_and_cannot_publish(app_ctx):
    cid = app_ctx.repos.campaigns.create("collab", "کانال X")
    c = make_context(app_ctx)
    assert "نامعتبر" in txt(await click(c, f"d:e:{cid}:p"))
    assert "نامعتبر" in txt(await click(c, f"d:e:{cid}:b"))
    u = await click(c, f"d:pv:{cid}")
    assert "پیدا نشد" in txt(u) and not c.bot.send_message.called


async def test_ad_full_publish_flow(app_ctx):
    r = app_ctx.repos
    cid = new_campaign(r, text="تبلیغ ویژه")
    r.campaigns.update(cid, button_label="عضویت", button_url="https://t.me/x")
    c = make_context(app_ctx)
    c.bot.get_chat_member_count = AsyncMock(return_value=40)
    await click(c, f"d:pv:{cid}")
    prev = c.bot.send_message.call_args.kwargs
    assert prev["chat_id"] == ADMIN and prev["text"] == "تبلیغ ویژه"
    fp = prev["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[3]
    assert prev["reply_markup"].inline_keyboard[-1][0].url == "https://t.me/x"
    channel_posts = lambda: [x for x in c.bot.send_message.call_args_list if x.kwargs.get("chat_id") == "@bia2music1395"]  # noqa: E731
    u = await click(c, f"d:ok:{cid}:{fp}", from_audio=True)
    assert not channel_posts() and r.campaigns.get(cid)["status"] == "draft"            # تأیید اول چیزی منتشر نمی‌کند
    await click(c, f"d:bk:{cid}:{fp}", from_audio=True)
    assert not channel_posts()
    u = await click(c, f"d:go:{cid}:{fp}", from_audio=True)
    post = channel_posts()[0].kwargs
    assert post["text"] == "تبلیغ ویژه" and post["reply_markup"].inline_keyboard[0][0].url == "https://t.me/x"
    got = r.campaigns.get(cid)
    assert got["status"] == "active" and got["members_start"] == 40 and got["channel_message_id"] == 900
    assert "منتشر شد" in txt(u)
    await click(c, f"d:go:{cid}:{fp}", from_audio=True)                                 # ضربه‌ی دوم
    assert len(channel_posts()) == 1


async def test_ad_preview_guards(app_ctx):
    r = app_ctx.repos
    c = make_context(app_ctx)
    empty = r.campaigns.create("ad", "بدون متن")
    assert "متن پست خالی" in txt(await click(c, f"d:pv:{empty}"))
    half = new_campaign(r)
    r.campaigns.update(half, button_label="فقط متن")
    assert "دکمه ناقص" in txt(await click(c, f"d:pv:{half}"))
    ok = new_campaign(r)
    object.__setattr__(app_ctx.settings, "channel_id", None)
    assert "تنظیم نشده" in txt(await click(c, f"d:pv:{ok}"))
    assert not c.bot.send_message.called


async def test_ad_stale_fingerprint_rejected(app_ctx):
    r = app_ctx.repos
    cid = new_campaign(r, text="نسخه ۱")
    c = make_context(app_ctx)
    await click(c, f"d:pv:{cid}")
    fp = ad_fingerprint(r.campaigns.get(cid))
    r.campaigns.update(cid, post_text="نسخه ۲")
    u = await click(c, f"d:ok:{cid}:{fp}", from_audio=True)
    assert "قدیمی" in txt(u)
    u = await click(c, f"d:go:{cid}:{fp}", from_audio=True)
    assert "تغییر کرده" in txt(u) and r.campaigns.get(cid)["status"] == "draft"
    assert not [x for x in c.bot.send_message.call_args_list if x.kwargs.get("chat_id") == "@bia2music1395"]


@pytest.mark.parametrize("exc,final,msg", [(Forbidden("x"), "draft", "اجازه"), (BadRequest("y"), "draft", "نپذیرفت"),
                                           (TimedOut("t"), "publishing", "معلوم نیست"), (TelegramError("z"), "draft", "ناموفق")])
async def test_ad_publish_failures(app_ctx, exc, final, msg):
    r = app_ctx.repos
    cid = new_campaign(r)
    c = make_context(app_ctx)
    fp = ad_fingerprint(r.campaigns.get(cid))
    c.bot.send_message.side_effect = exc
    u = await click(c, f"d:go:{cid}:{fp}", from_audio=True)
    assert msg in txt(u) and r.campaigns.get(cid)["status"] == final
    c.bot.send_message.side_effect = None
    u = await click(c, f"d:go:{cid}:{fp}", from_audio=True)
    attempts = [x for x in c.bot.send_message.call_args_list if x.kwargs.get("chat_id") == "@bia2music1395"]
    if final == "publishing":
        assert len(attempts) == 1                         # بعد از قطع نامعلوم، دوباره ارسال نمی‌شود (پست تکراری نشود)
        assert "در حال انتشار" in txt(u) or "قبلاً" in txt(u)
    else:
        assert len(attempts) == 2 and r.campaigns.get(cid)["status"] == "active"      # خطای قطعی: تلاش دوباره ممکن است


async def test_cancel_preview_publishes_nothing(app_ctx):
    cid = new_campaign(app_ctx.repos)
    c = make_context(app_ctx)
    u = await click(c, f"d:cx:{cid}", from_audio=True)
    assert "چیزی منتشر نشد" in txt(u) and app_ctx.repos.campaigns.get(cid)["status"] == "draft"


async def test_collab_start_finish_gain_and_income(app_ctx):
    r = app_ctx.repos
    cid = r.campaigns.create("collab", "کانال شریک")
    c = make_context(app_ctx)
    u = await click(c, f"d:st:{cid}")
    assert r.campaigns.get(cid)["status"] == "active" and r.campaigns.get(cid)["members_start"] == 22
    r.db.execute("UPDATE campaigns SET members_start=10 WHERE id=?", (cid,))
    assert "تا اکنون: +12" in txt(await click(c, f"d:v:{cid}"))
    u = await click(c, f"d:fin:{cid}")
    assert "نتیجه: +12" in txt(u) and r.campaigns.get(cid)["status"] == "done"
    ad = new_campaign(r)
    r.campaigns.update(ad, price=1_000_000)
    r.campaigns.claim_publishing(ad); r.campaigns.mark_published(ad, 5, 20)
    assert "1,000,000" in txt(await click(c, "d:inc"))


async def test_snooze_cancel_delete_flows(app_ctx):
    r = app_ctx.repos
    cid = r.campaigns.create("collab", "X")
    c = make_context(app_ctx)
    await click(c, f"d:st:{cid}")
    await click(c, f"d:sn:{cid}")
    got = r.campaigns.get(cid)
    assert got["ends_at"] and got["reminder_sent"] == 0 and got["status"] == "active"      # یادآوری بعدی ۱ ساعت دیگر
    assert "حذف ممکن نیست" in txt(await click(c, f"d:dy:{cid}"))               # فعال حذف نمی‌شود
    await click(c, f"d:can:{cid}")
    assert r.campaigns.get(cid)["status"] == "cancelled"
    assert "حذف شود" in txt(await click(c, f"d:del:{cid}")) and r.campaigns.get(cid)
    await click(c, f"d:dy:{cid}")
    assert r.campaigns.get(cid) is None
    for bad in ("d:v:999", "d:zzz", "d:l:bogus", "d:e:abc:t", "d:go:1"):
        assert "پیدا نشد" in txt(await click(c, bad)) or "نامعتبر" in txt(await click(c, bad))


# ======================= اشتراک ویژه (مدیر) =======================
async def test_premium_admin_menu_toggle_and_settings(app_ctx):
    c = make_context(app_ctx)
    u = await click(c, "v:menu")
    assert "خاموش" in txt(u) and "100 استارز برای 30 روز" in txt(u)
    u = await click(c, "v:t")
    assert "v:ty" in cbs(u) and app_ctx.repos.settings.get("premium_enabled") is None
    await click(c, "v:ty")
    assert ph.premium_settings(app_ctx)["enabled"]
    for field, val, key, exp in (("p", "۲۵۰", "premium_stars", "250"), ("d", "90", "premium_days", "90"), ("s", "@help_me پشتیبان", "support_text", "@help_me پشتیبان")):
        await click(c, f"v:{field}")
        await say(c, val)
        assert app_ctx.repos.settings.get(key) == exp
    for field, bad in (("p", "0"), ("p", "99999"), ("p", "abc"), ("d", "400"), ("s", "@")):
        await click(c, f"v:{field}")
        assert "❌" in txt(await say(c, bad))
    assert ph.premium_settings(app_ctx)["stars"] == 250
    await click(c, "v:t")
    assert not ph.premium_settings(app_ctx)["enabled"]


# ======================= پرداخت =======================
def enable(app_ctx, stars=100, days=30):
    st_ = app_ctx.repos.settings
    st_.set("premium_enabled", "1"); st_.set("premium_stars", str(stars)); st_.set("premium_days", str(days)); st_.set("user_features", "1")


def pre(uid, payload, amount=100, currency="XTR"):
    return SimpleNamespace(pre_checkout_query=SimpleNamespace(id="q", from_user=SimpleNamespace(id=uid), currency=currency,
                                                              total_amount=amount, invoice_payload=payload, answer=AsyncMock()))


async def test_user_sees_premium_only_when_enabled_and_buys(app_ctx):
    c = make_context(app_ctx)
    app_ctx.repos.settings.set("user_features", "1")
    assert "u:pr" not in cbs(await click(c, "u:home", U1))
    assert "فعال نیست" in txt(await click(c, "u:pr", U1))
    await click(c, "u:buy", U1)
    assert not c.bot.send_invoice.called
    enable(app_ctx)
    assert "u:pr" in cbs(await click(c, "u:home", U1))
    u = await click(c, "u:pr", U1)
    assert "100 استارز برای 30 روز" in txt(u) and "اشتراک فعالی ندارید" in txt(u) and "u:buy" in cbs(u)
    await click(c, "u:buy", U1)
    kw = c.bot.send_invoice.call_args.kwargs
    assert kw["chat_id"] == U1 and kw["currency"] == "XTR" and kw["payload"] == f"prem:{U1}:30:100"
    assert kw["prices"][0].amount == 100 and "provider_token" not in kw
    c.bot.send_invoice.side_effect = TelegramError("x")
    assert "ممکن نشد" in txt(await click(c, "u:buy", U1))


@pytest.mark.parametrize("uid,payload,amount,cur,ok", [
    (U1, f"prem:{U1}:30:100", 100, "XTR", True),
    (U2, f"prem:{U1}:30:100", 100, "XTR", False),      # کاربر دیگر
    (U1, f"prem:{U1}:30:100", 50, "XTR", False),       # مبلغ دستکاری‌شده
    (U1, f"prem:{U1}:30:100", 100, "USD", False),
    (U1, f"prem:{U1}:30:90", 100, "XTR", False),       # قیمت قدیمی
    (U1, "garbage", 100, "XTR", False),
])
async def test_precheckout(app_ctx, uid, payload, amount, cur, ok):
    enable(app_ctx)
    u = pre(uid, payload, amount, cur)
    await ph.precheckout(u, make_context(app_ctx))
    assert u.pre_checkout_query.answer.call_args.kwargs["ok"] is ok
    if not ok:
        assert u.pre_checkout_query.answer.call_args.kwargs["error_message"]


async def test_precheckout_rejects_when_disabled(app_ctx):
    u = pre(U1, f"prem:{U1}:30:100")
    await ph.precheckout(u, make_context(app_ctx))
    assert u.pre_checkout_query.answer.call_args.kwargs["ok"] is False


def paid(uid, charge="CH1", payload=None, amount=100, currency="XTR"):
    u = make_update(user_id=uid)
    u.effective_message.successful_payment = SimpleNamespace(currency=currency, total_amount=amount, telegram_payment_charge_id=charge,
                                                            invoice_payload=payload or f"prem:{uid}:30:100")
    return u


async def test_successful_payment_grants_once_and_notifies(app_ctx):
    enable(app_ctx)
    c = make_context(app_ctx)
    u = paid(U1)
    await ph.successful_payment(u, c)
    r = app_ctx.repos
    assert r.payments.is_premium(U1) and r.payments.revenue()["stars"] == 100
    assert "اشتراک ویژه شما" in u.effective_message.reply_text.call_args.args[0]
    assert c.bot.send_message.call_args.args[0] == ADMIN and "100⭐" in c.bot.send_message.call_args.args[1]
    assert r.metrics.totals(1).get("purchase") == 1
    until = r.payments.premium_until(U1)
    await ph.successful_payment(paid(U1), c)                       # همان شارژ دوباره
    assert r.payments.premium_until(U1) == until and r.payments.revenue()["count"] == 1
    await ph.successful_payment(paid(U1, charge="CH2"), c)         # خرید دوم: تمدید
    assert r.payments.premium_until(U1) > until


async def test_payment_with_unexpected_payload_still_grants_and_logs(app_ctx):
    enable(app_ctx)
    await ph.successful_payment(paid(U1, payload="weird"), make_context(app_ctx))
    assert app_ctx.repos.payments.is_premium(U1)
    assert any(l["action"] == "payment_unexpected_payload" for l in app_ctx.repos.logs.recent(20))


# ======================= دریافت فایل و مزایا =======================
async def test_download_gating(app_ctx):
    r = app_ctx.repos
    sid = ready_song(r, status="published")
    c = make_context(app_ctx)
    r.settings.set("user_features", "1")
    assert "u:dl" not in "".join(cbs(await click(c, f"u:v:{sid}", U1)))               # اشتراک خاموش: دکمه نیست
    assert "فعلاً فعال نیست" in txt(await click(c, f"u:dl:{sid}", U1))
    enable(app_ctx)
    assert f"u:dl:{sid}" in cbs(await click(c, f"u:v:{sid}", U1))
    u = await click(c, f"u:dl:{sid}", U1)
    assert "مخصوص مشترکین" in txt(u) and not c.bot.send_audio.called                  # غیرمشترک: فایل نمی‌رود
    r.users.touch(U1, "u", "U", "fa")
    r.payments.grant(U1, 30)
    u = await click(c, f"u:dl:{sid}", U1)
    kw = c.bot.send_audio.call_args.kwargs
    assert kw["chat_id"] == U1 and kw["audio"] == "FILEu1" and kw["protect_content"] is True
    assert "فایل ارسال شد" in txt(u) and r.metrics.totals(1).get("download") == 1
    c.bot.send_audio.side_effect = TelegramError("x")
    assert "ممکن نشد" in txt(await click(c, f"u:dl:{sid}", U1))


async def test_download_unpublished_or_missing(app_ctx):
    enable(app_ctx)
    sid = ready_song(app_ctx.repos)                       # منتشرنشده
    c = make_context(app_ctx)
    for s_ in (sid, 999):
        assert "پیدا نشد" in txt(await click(c, f"u:dl:{s_}", U1))
    assert not c.bot.send_audio.called


async def test_admin_can_download_without_subscription(app_ctx):
    enable(app_ctx)
    sid = ready_song(app_ctx.repos, status="published")
    c = make_context(app_ctx)
    await click(c, f"u:dl:{sid}", ADMIN)
    assert c.bot.send_audio.call_args.kwargs["chat_id"] == ADMIN


async def test_premium_playlist_lock(app_ctx):
    r = app_ctx.repos
    enable(app_ctx)
    sid = ready_song(r, status="published")
    pid = r.playlists.create("ویژه")
    r.playlists.add_song(pid, sid)
    c = make_context(app_ctx)
    u = await click(c, f"y:pm:{pid}")
    assert r.playlists.get(pid)["is_premium"] == 1 and "فقط مشترکین" in txt(u)
    assert any("⭐" in b.text for b in buttons(await click(c, "u:p", U1)))
    u = await click(c, f"u:pl:{pid}:0", U1)
    assert "مخصوص" in txt(u) or "ویژه" in txt(u)
    assert f"u:v:{sid}" not in cbs(u)
    r.users.touch(U1, "u", "U", "fa"); r.payments.grant(U1, 5)
    assert f"u:v:{sid}" in cbs(await click(c, f"u:pl:{pid}:0", U1))
    await click(c, f"y:pm:{pid}")
    assert r.playlists.get(pid)["is_premium"] == 0


async def test_premium_user_higher_request_limit(app_ctx):
    r = app_ctx.repos
    enable(app_ctx)
    r.users.touch(U1, "u", "U", "fa"); r.users.touch(U2, "v", "V", "fa")
    r.payments.grant(U1, 30)
    for uid in (U1, U2):
        for _ in range(3):
            r.userdata.add_request(uid, "x")
    c = make_context(app_ctx)
    await click(c, "u:q", U1)
    assert "ارسال شد" in txt(await say(c, "چهارم", U1))                   # مشترک تا ۱۰
    await click(c, "u:q", U2)
    assert "حداکثر 3" in txt(await say(c, "چهارم", U2))


# ======================= بازپرداخت و هدیه =======================
async def test_refund_flow(app_ctx):
    r = app_ctx.repos
    enable(app_ctx)
    r.users.touch(U1, "ali", "علی", "fa")
    r.payments.record(U1, 100, 30, "CHX", f"prem:{U1}:30:100")
    pid = r.payments.recent(1)[0]["id"]
    c = make_context(app_ctx)
    assert "علی" in txt(await click(c, "v:l")) or f"v:pv:{pid}" in cbs(await click(c, "v:l"))
    assert "v:rf:" in "".join(cbs(await click(c, f"v:pv:{pid}")))
    u = await click(c, f"v:rf:{pid}")
    assert "قابل بازگشت نیست" in txt(u) and not c.bot.refund_star_payment.called
    c.bot.refund_star_payment.side_effect = TelegramError("no")
    assert "نپذیرفت" in txt(await click(c, f"v:rfy:{pid}"))
    assert r.payments.get(pid)["status"] == "paid" and r.payments.is_premium(U1)
    c.bot.refund_star_payment.side_effect = None
    await click(c, f"v:rfy:{pid}")
    assert c.bot.refund_star_payment.call_args.kwargs == {"user_id": U1, "telegram_payment_charge_id": "CHX"}
    assert r.payments.get(pid)["status"] == "refunded" and not r.payments.is_premium(U1)
    assert "قابل بازپرداخت نیست" in txt(await click(c, f"v:rfy:{pid}"))          # دوباره ممکن نیست
    assert c.bot.refund_star_payment.call_count == 2


async def test_admin_gift_and_revoke(app_ctx):
    r = app_ctx.repos
    r.users.touch(U1, "u", "U", "fa")
    c = make_context(app_ctx)
    assert "اشتراک ویژه: —" in txt(await click(c, f"a:uv:{U1}"))
    await click(c, f"a:gp:{U1}")
    assert r.payments.is_premium(U1) and "اشتراک ویژه: ✅" in txt(await click(c, f"a:uv:{U1}"))
    await click(c, f"a:rp:{U1}")
    assert not r.payments.is_premium(U1)
    assert "نامعتبر" in txt(await click(c, f"a:gp:{ADMIN}"))
    assert "نامعتبر" in txt(await click(c, "a:gp:424242"))


async def test_terms_and_paysupport(app_ctx):
    c = make_context(app_ctx)
    u = make_update(user_id=U1)
    await ph.terms_command(u, c)
    assert "شرایط اشتراک" in txt(u) and "/paysupport" in txt(u)
    u = make_update(user_id=U1)
    await ph.paysupport_command(u, c)
    assert "از طریق کانال" in txt(u)
    app_ctx.repos.settings.set("support_text", "@help_me")
    u = make_update(user_id=U1)
    await ph.paysupport_command(u, c)
    assert "@help_me" in txt(u)


# ======================= شمارنده‌های تعامل و محدودیت نرخ =======================
async def test_interaction_metrics_counted(app_ctx):
    r = app_ctx.repos
    r.settings.set("user_features", "1")
    sid = ready_song(r, status="published")
    c = make_context(app_ctx)
    u = make_update(user_id=U1)
    await menu.start(u, c)
    await say(c, "شب", U1)
    await click(c, f"u:v:{sid}", U1)
    await click(c, f"u:cy:{sid}", U1)                    # رضایت + پسند
    await click(c, "u:r", U1)
    await click(c, "u:q", U1)
    await say(c, "درخواست", U1)
    tot = r.metrics.totals(1)
    assert {"start": 1, "search": 1, "like": 1, "suggest": 1, "request": 1}.items() <= tot.items() and tot["song_view"] >= 2
    assert str(U1) not in "".join(str(dict(x)) for x in r.db.fetchall("SELECT * FROM daily_metrics"))


async def test_rate_limit_blocks_spam_but_not_admin(app_ctx):
    app_ctx.repos.settings.set("user_features", "1")
    app_ctx.limiter = RateLimiter(2, 60)
    c = make_context(app_ctx)
    await click(c, "u:home", U1)
    await click(c, "u:home", U1)
    u = await click(c, "u:home", U1)
    u.callback_query.edit_message_text.assert_not_called()
    assert "آهسته" in u.callback_query.answer.call_args.args[0]
    n = len(app_ctx.repos.users.recent(5))
    await say(c, "شب", U1)                               # متن هم نادیده گرفته می‌شود
    assert app_ctx.repos.metrics.totals(1).get("search") is None
    for _ in range(5):
        u = await click(c, "u:home", ADMIN)
    u.callback_query.edit_message_text.assert_called()


# ======================= پشتیبان و وضعیت سیستم =======================
async def test_backup_sent_only_to_admin_and_valid(app_ctx):
    app_ctx.repos.songs.create(title="آهنگ پشتیبان", artist="x", telegram_file_id="F", file_unique_id="U")
    c = make_context(app_ctx)
    captured = {}

    async def fake_send_document(chat_id, document, filename, caption=None):
        captured["chat_id"], captured["filename"] = chat_id, filename
        captured["bytes"] = document.read()

    c.bot.send_document = fake_send_document
    u = await click(c, "s:backup")
    assert captured["chat_id"] == ADMIN and captured["filename"].endswith(".sqlite3") and "ارسال شد" in txt(u)
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(captured["bytes"])
    con = sqlite3.connect(f.name)
    assert con.execute("SELECT title FROM songs").fetchone()[0] == "آهنگ پشتیبان"
    con.close(); os.unlink(f.name)
    c.bot.send_document = AsyncMock(side_effect=TelegramError("x"))
    assert "ناموفق" in txt(await click(c, "s:backup"))
    u = await click(make_context(app_ctx), "s:backup", user=U1)
    u.callback_query.edit_message_text.assert_not_called()


async def test_health_screen(app_ctx):
    app_ctx.repos.logs.add("boom", None, "detail", level="error")
    c = make_context(app_ctx)
    c.application.bot_data["started_at"] = __import__("musicbot.publishing.timeutil", fromlist=["x"]).utc_now()
    u = await click(c, "s:health")
    t = txt(u)
    assert "وضعیت سیستم" in t and "1.0.0" in t and "زمان‌بند: ❌ متوقف" in t and "boom" in t
    labels = " ".join(b.text for b in buttons(await click(c, "m:settings")))
    assert "پشتیبان" in labels and "وضعیت سیستم" in labels
