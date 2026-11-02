from musicbot.handlers import menu, settings as sh, songs as songs_h
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from tests.conftest import ADMIN, make_context, make_update


def last_text(update):
    q = update.callback_query
    call = (q.edit_message_text if q else update.effective_message.reply_text).call_args
    return call.args[0]


def markup_of(update):
    q = update.callback_query
    call = (q.edit_message_text if q else update.effective_message.reply_text).call_args
    return call.kwargs.get("reply_markup")


async def test_admin_start_shows_menu(app_ctx):
    u, c = make_update(), make_context(app_ctx)
    await menu.start(u, c)
    assert T.MAIN_MENU == last_text(u)
    labels = [b.text for row in markup_of(u).inline_keyboard for b in row]
    assert len(labels) == 15 and "⚙️ تنظیمات" in labels


async def test_stranger_start_has_no_menu(app_ctx):
    u, c = make_update(user_id=555), make_context(app_ctx)
    await menu.start(u, c)
    u.effective_message.reply_text.assert_awaited_once_with(T.NOT_ADMIN)
    assert app_ctx.repos.users.count() == 1
    assert any(l["action"] == "unauthorized_start" for l in app_ctx.repos.logs.recent())


async def test_stranger_callback_blocked(app_ctx):
    u, c = make_update(user_id=555, data="m:settings"), make_context(app_ctx)
    await menu.menu_callback(u, c)
    u.callback_query.answer.assert_awaited_once_with(T.NOT_ADMIN_ALERT, show_alert=True)
    u.callback_query.edit_message_text.assert_not_called()


async def test_admin_in_group_blocked(app_ctx):
    u, c = make_update(data="m:settings", chat_type="supergroup"), make_context(app_ctx)
    await menu.menu_callback(u, c)
    u.callback_query.edit_message_text.assert_not_called()


async def test_stranger_text_and_media_blocked(app_ctx):
    for fn in (menu.text_message, songs_h.receive_audio):
        u, c = make_update(user_id=555, text="hi"), make_context(app_ctx)
        await fn(u, c)
        u.effective_message.reply_text.assert_awaited_once_with(T.NOT_ADMIN)


async def test_disabled_sections_show_coming_later(app_ctx):
    for key, title, active in T.MENU_ITEMS:
        if active:
            continue
        u, c = make_update(data=f"m:{key}"), make_context(app_ctx)
        await menu.menu_callback(u, c)
        assert "مرحله بعدی فعال خواهد شد" in last_text(u)
        assert any(b.callback_data == "m:main" for row in markup_of(u).inline_keyboard for b in row)


async def test_active_sections(app_ctx):
    for key, frag in (("ai", "وضعیت هوش مصنوعی"), ("settings", "تنظیمات"), ("help", "راهنما")):
        u, c = make_update(data=f"m:{key}"), make_context(app_ctx)
        await menu.menu_callback(u, c)
        assert frag in last_text(u)


async def test_ai_status_text_honest(app_ctx):
    u, c = make_update(data="m:ai"), make_context(app_ctx)
    await menu.menu_callback(u, c)
    t = last_text(u)
    assert "غیرفعال" in t and "هوش مصنوعی واقعی نیست" in t


async def test_non_audio_not_stored(app_ctx):
    u, c = make_update(), make_context(app_ctx)
    await songs_h.receive_audio(u, c)
    assert "فقط فایل صوتی" in last_text(u)
    assert app_ctx.repos.db.fetchone("SELECT COUNT(*) c FROM songs")["c"] == 0


async def test_channel_status_view(app_ctx, bot):
    u, c = make_update(data="s:channel"), make_context(app_ctx)
    await sh.settings_callback(u, c)
    assert "ربات ادمین کانال است" in last_text(u) and "✅" in last_text(u)
    assert "bia2music1395" in last_text(u)


async def test_channel_change_flow_with_confirm(app_ctx, bot):
    c = make_context(app_ctx)
    u = make_update(data="s:channel_change")
    await sh.settings_callback(u, c)
    assert c.user_data["awaiting"] == "channel"
    # ورودی نامعتبر
    u2 = make_update(text="سلام")
    await menu.text_message(u2, c)
    assert "معتبر نیست" in last_text(u2) and c.user_data["awaiting"] == "channel"
    # ورودی معتبر
    u3 = make_update(text="https://t.me/newchan123")
    await menu.text_message(u3, c)
    assert c.user_data["pending_channel"][0] == "@newchan123"
    assert app_ctx.repos.channel.get_active() is None  # تا تأیید ذخیره نمی‌شود
    u4 = make_update(data="c:confirm")
    await sh.channel_confirm_callback(u4, c)
    assert app_ctx.effective_channel_ref() == "@newchan123"
    assert any(l["action"] == "channel_changed" for l in app_ctx.repos.logs.recent())


async def test_channel_change_cancel(app_ctx):
    c = make_context(app_ctx)
    await sh.settings_callback(make_update(data="s:channel_change"), c)
    u = make_update(data="s:cancel")
    await sh.settings_callback(u, c)
    assert "awaiting" not in c.user_data and T.CANCELLED in last_text(u)
    assert app_ctx.effective_channel_ref() == "@bia2music1395"


async def test_confirm_without_pending(app_ctx):
    u = make_update(data="c:confirm")
    await sh.channel_confirm_callback(u, make_context(app_ctx))
    assert "منقضی" in last_text(u)


async def test_logs_view(app_ctx):
    app_ctx.repos.logs.add("admin_start", ADMIN)
    u = make_update(data="s:logs")
    await sh.settings_callback(u, make_context(app_ctx))
    assert "ورود مدیر" in last_text(u)


def test_keyboards_valid():
    for kb in (K.main_menu(), K.settings_menu(), K.back_to_settings(), K.cancel_to_settings(),
               K.confirm_channel(), K.back_to_menu()):
        for row in kb.inline_keyboard:
            assert len(row) <= 2
            for b in row:
                assert len(b.callback_data.encode()) <= 64
    # هر صفحه زیرمنو بازگشت یا لغو دارد
    for kb in (K.settings_menu(), K.back_to_settings(), K.cancel_to_settings(), K.confirm_channel(), K.back_to_menu()):
        texts = " ".join(b.text for row in kb.inline_keyboard for b in row)
        assert "بازگشت" in texts or "لغو" in texts or "منوی اصلی" in texts
