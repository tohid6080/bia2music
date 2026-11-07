"""فعالیت کاربران داخل ربات: فقط با رضایت جداگانه، فقط برای مدیر، قابل حذف."""
import pytest

from musicbot.handlers import admin_users as au, users as uh
from tests.conftest import ADMIN, make_context, make_update
from tests.test_users_phase4 import ROUTE, btns, cbs, click, song, txt  # noqa: F401

U1, U2, U3 = 3001, 3002, 3003
NAMES = {U1: ("Ali", "ali_u"), U2: ("Sara", "sara_u"), U3: ("Reza", "reza_u")}


async def click_as(c, data, uid):
    """مثل click ولی با نام/نام‌کاربری متمایز برای هر کاربر (touch نام را از update می‌خواند)."""
    u = make_update(user_id=uid, data=data)
    u.effective_user.first_name, u.effective_user.username = NAMES[uid]
    await ROUTE[data[0]](u, c)
    return u


@pytest.fixture
def on(app_ctx):
    app_ctx.repos.settings.set_user_features(True)
    for uid, name in ((U1, "علی"), (U2, "سارا"), (U3, "رضا")):
        app_ctx.repos.users.touch(uid, f"user{uid}", name, "fa")
    return app_ctx


def events(repos):
    return [dict(r) for r in repos.db.fetchall("SELECT * FROM song_events")]


async def test_nothing_recorded_without_activity_consent(on):
    c = make_context(on)
    s = song(on.repos, "e1", "شب")
    await click(c, f"u:v:{s}", user=U1)
    on.repos.userdata.give_consent(U1)                       # رضایت پایه (علایق) کافی نیست
    await click(c, f"u:lk:{s}", user=U1)
    assert events(on.repos) == [] and on.repos.userdata.is_liked(U1, s)


async def test_consent_flow_is_opt_in_and_requires_base_consent(on):
    c = make_context(on)
    u = await click(c, "u:ac", user=U1)
    assert "پیش‌فرض: <b>خاموش</b>" in txt(u) and "u:acy" in cbs(u)
    u = await click(c, "u:acy", user=U1)                     # بدون رضایت پایه ← ابتدا همان
    assert "u:cy:0" in cbs(u) and not on.repos.userdata.has_activity_consent(U1)
    on.repos.userdata.give_consent(U1)
    u = await click(c, "u:acy", user=U1)
    assert on.repos.userdata.has_activity_consent(U1) and "u:acn" in cbs(u)


async def test_events_recorded_after_consent_and_view_deduped(on):
    c = make_context(on)
    s = song(on.repos, "e2", "شب")
    on.repos.userdata.give_consent(U1)
    on.repos.userdata.set_activity_consent(U1, True)
    await click(c, f"u:v:{s}", user=U1)
    await click(c, f"u:v:{s}", user=U1)                       # بازدید تکراری نزدیک ← یک ردیف
    await click(c, f"u:lk:{s}", user=U1)
    kinds = [e["kind"] for e in events(on.repos)]
    assert kinds == ["view", "like"]                  # بازدیدهای نزدیک به هم (حتی کارت پس از پسند) یک‌بار ثبت می‌شوند؛ پسند یک‌بار
    await click(c, f"u:lk:{s}", user=U1)                      # برداشتن پسند ← رویداد جدید نمی‌سازد
    assert [e["kind"] for e in events(on.repos)].count("like") == 1


async def test_withdrawing_consent_deletes_history(on):
    c = make_context(on)
    s = song(on.repos, "e3", "شب")
    on.repos.userdata.give_consent(U1)
    on.repos.userdata.set_activity_consent(U1, True)
    await click(c, f"u:v:{s}", user=U1)
    assert events(on.repos)
    u = await click(c, "u:acn", user=U1)
    assert events(on.repos) == [] and not on.repos.userdata.has_activity_consent(U1) and "سابقه پاک شد" in txt(u)


async def test_delete_all_removes_events_and_consent(on):
    s = song(on.repos, "e4", "شب")
    on.repos.userdata.give_consent(U1)
    on.repos.userdata.set_activity_consent(U1, True)
    on.repos.userdata.record_event(U1, s, "view")
    on.repos.userdata.delete_all(U1)
    assert events(on.repos) == [] and not on.repos.userdata.has_activity_consent(U1)


async def test_admin_sees_only_consenting_users_by_name(on):
    c = make_context(on)
    s = song(on.repos, "e5", "شب")
    for uid in (U1, U2, U3):
        on.repos.userdata.give_consent(uid)
    on.repos.userdata.set_activity_consent(U1, True)
    on.repos.userdata.set_activity_consent(U2, True)          # U3 اجازه نداده
    for uid in (U1, U2, U3):
        await click_as(c, f"u:v:{s}", uid)
    await click_as(c, f"u:lk:{s}", U2)
    u = await click(c, "a:ev:0", user=ADMIN)
    assert "فقط کارهای انجام‌شده <b>داخل ربات</b>" in txt(u) and "در دسترس نیست" in txt(u)
    assert f"a:evs:{s}" in cbs(u)
    u = await click(c, f"a:evs:{s}", user=ADMIN)
    t = txt(u)
    assert "Ali" in t and "Sara" in t and "@sara_u" in t and "پسندید" in t
    assert "Reza" not in t and "reza_u" not in t                      # بدون اجازه ← هرگز نمایش داده نمی‌شود


async def test_strangers_cannot_open_admin_activity(on):
    c = make_context(on)
    s = song(on.repos, "e6", "شب")
    on.repos.userdata.give_consent(U1)
    on.repos.userdata.set_activity_consent(U1, True)
    on.repos.userdata.record_event(U1, s, "view")
    on.repos.users.touch(U1, "ali_u", "Ali", "fa")
    u = make_update(user_id=U2, data="a:ev:0")
    await au.admin_users_callback(u, c)
    assert u.callback_query.edit_message_text.call_args is None or "Ali" not in txt(u)
    u = make_update(user_id=U2, data=f"a:evs:{s}")
    await au.admin_users_callback(u, c)
    assert u.callback_query.edit_message_text.call_args is None or "Ali" not in txt(u)


def test_old_events_purged(on):
    s = song(on.repos, "e7", "شب")
    on.repos.userdata.give_consent(U1)
    on.repos.userdata.set_activity_consent(U1, True)
    on.repos.userdata.record_event(U1, s, "like")
    on.repos.db.execute("UPDATE song_events SET at='2020-01-01T00:00:00Z'")
    assert on.repos.userdata.purge_old_events() == 1 and events(on.repos) == []


def test_privacy_text_discloses_optional_named_activity():
    from musicbot.ui import user_ui as UU

    assert "نمایش فعالیت من به مدیر" in UU.PRIVACY and "خاموش" in UU.PRIVACY
    assert "۹۰ روز" in UU.ACTIVITY_INFO and "داخل خود کانال" in UU.ACTIVITY_INFO
