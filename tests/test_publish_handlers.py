from datetime import timedelta

from musicbot.handlers import captions as ch, menu, publish as ph, settings as settings_h, songs as sh
from musicbot.publishing import captions as C
from musicbot.publishing import scheduler
from musicbot.publishing import timeutil as TU
from tests.conftest import ADMIN, make_context, make_update


def txt(u):
    q = u.callback_query
    if q and q.message.audio:
        return q.message.reply_text.call_args.args[0]
    return (q.edit_message_text if q else u.effective_message.reply_text).call_args.args[0]


def buttons(u):
    q = u.callback_query
    if q and q.message.audio:
        m = q.message.reply_text.call_args.kwargs["reply_markup"]
    else:
        m = (q.edit_message_text if q else u.effective_message.reply_text).call_args.kwargs["reply_markup"]
    return [b for row in m.inline_keyboard for b in row]


async def click(app_ctx, c, data, from_audio=False, user_id=ADMIN):
    u = make_update(data=data, from_audio=from_audio, user_id=user_id)
    router = {"g": sh.songs_callback, "p": ph.publish_callback, "k": ch.captions_callback, "m": menu.menu_callback, "s": settings_h.settings_callback}
    await router[data[0]](u, c)
    return u


def ready_song(repos, uid="u1", caption="کپشن", hashtags="#a"):
    sid = repos.songs.create(title="شب", artist="علی", telegram_file_id="FILE", file_unique_id=uid, duration_seconds=100)
    repos.songs.update(sid, language_code="fa", status="ready", caption=caption, hashtags=hashtags)
    return sid


def preview_fp(c):
    """اثر انگشت از دکمه‌های پیش‌نمایشی که به مدیر فرستاده شد."""
    kb = c.bot.send_audio.call_args.kwargs["reply_markup"]
    return kb.inline_keyboard[0][0].callback_data.split(":")[3]


async def test_preview_goes_only_to_admin_not_channel(app_ctx):
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    u = await click(app_ctx, c, f"p:pv:{sid}")
    kw = c.bot.send_audio.call_args.kwargs
    assert kw["chat_id"] == ADMIN and kw["caption"] == "کپشن\n\n#a" and kw["audio"] == "FILE"
    assert "هنوز چیزی منتشر نشده" in txt(u)
    assert app_ctx.repos.songs.get(sid)["status"] == "ready"
    labels = [b.text for b in c.bot.send_audio.call_args.kwargs["reply_markup"].inline_keyboard[0]]
    assert labels == ["✅ تأیید و انتشار"]


async def test_full_publish_requires_two_confirmations(app_ctx):
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    fp = preview_fp(c)
    # تأیید اول: فقط دکمه تأیید نهایی را نشان می‌دهد
    u = await click(app_ctx, c, f"p:ok:{sid}:{fp}", from_audio=True)
    assert c.bot.send_audio.call_count == 1                     # فقط پیش‌نمایش (به مدیر)
    assert app_ctx.repos.songs.get(sid)["status"] == "ready"
    u.callback_query.edit_message_reply_markup.assert_awaited_once()
    # تأیید نهایی
    u = await click(app_ctx, c, f"p:go:{sid}:{fp}", from_audio=True)
    assert c.bot.send_audio.call_count == 2
    ch_call = c.bot.send_audio.call_args.kwargs
    assert ch_call["chat_id"] == "@bia2music1395" and ch_call.get("reply_markup") is None
    s = app_ctx.repos.songs.get(sid)
    assert s["status"] == "published" and "منتشر شد" in txt(u)
    # ضربه دوم (یا تکرار) هیچ پست دومی نمی‌سازد
    u = await click(app_ctx, c, f"p:go:{sid}:{fp}", from_audio=True)
    assert c.bot.send_audio.call_count == 2 and "قبلاً منتشر" in txt(u)


async def test_edit_after_preview_invalidates_old_buttons(app_ctx):
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    old = preview_fp(c)
    app_ctx.repos.songs.update(sid, caption="کپشن جدید")
    u = await click(app_ctx, c, f"p:ok:{sid}:{old}", from_audio=True)
    assert "قدیمی" in txt(u)
    u = await click(app_ctx, c, f"p:go:{sid}:{old}", from_audio=True)
    assert c.bot.send_audio.call_count == 1 and "تغییر کرده" in txt(u)
    assert app_ctx.repos.songs.get(sid)["status"] == "ready"


async def test_back_from_confirm_does_not_publish(app_ctx):
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    fp = preview_fp(c)
    u = await click(app_ctx, c, f"p:bk:{sid}:{fp}", from_audio=True)
    restored = u.callback_query.edit_message_reply_markup.call_args.kwargs["reply_markup"]
    assert restored.inline_keyboard[0][0].callback_data == f"p:ok:{sid}:{fp}"
    assert c.bot.send_audio.call_count == 1


async def test_cancel_and_draft_do_not_publish(app_ctx):
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    u = await click(app_ctx, c, f"p:cx:{sid}", from_audio=True)
    assert "چیزی منتشر نشد" in txt(u) and app_ctx.repos.songs.get(sid)["status"] == "ready"
    await click(app_ctx, c, f"p:dr:{sid}", from_audio=True)
    assert app_ctx.repos.songs.get(sid)["status"] == "draft" and c.bot.send_audio.call_count == 1


async def test_stranger_cannot_publish(app_ctx):
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    fp = C.fingerprint(app_ctx.repos.songs.get(sid))
    u = await click(app_ctx, c, f"p:go:{sid}:{fp}", user_id=555)
    assert c.bot.send_audio.call_count == 0 and app_ctx.repos.songs.get(sid)["status"] == "ready"
    u.callback_query.answer.assert_awaited_with("دسترسی مجاز نیست.", show_alert=True)


async def test_preview_refused_for_draft_missing_channel_or_problems(app_ctx):
    repos = app_ctx.repos
    sid = repos.songs.create(title="a", artist="b", telegram_file_id="F", file_unique_id="d")
    c = make_context(app_ctx)
    assert "ثبت‌شده در آرشیو" in txt(await click(app_ctx, c, f"p:pv:{sid}"))
    ready = ready_song(repos, "r", caption="x" * 1100)
    assert "حداکثر" in txt(await click(app_ctx, c, f"p:pv:{ready}"))
    ok = ready_song(repos, "ok")
    object.__setattr__(app_ctx.settings, "channel_id", None)
    assert "تنظیم نشده" in txt(await click(app_ctx, c, f"p:pv:{ok}"))
    assert c.bot.send_audio.call_count == 0


async def test_preview_generates_caption_when_missing(app_ctx):
    sid = ready_song(app_ctx.repos, caption="", hashtags="")
    app_ctx.repos.songs.update(sid, caption=None)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    assert "علی" in c.bot.send_audio.call_args.kwargs["caption"]


async def test_publish_error_shown_and_state_kept(app_ctx):
    from telegram.error import Forbidden

    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    fp = preview_fp(c)
    c.bot.send_audio.side_effect = Forbidden("no")
    u = await click(app_ctx, c, f"p:go:{sid}:{fp}", from_audio=True)
    assert "ادمین" in txt(u) and app_ctx.repos.songs.get(sid)["status"] == "ready"


# ---------- کپشن ----------
async def test_caption_panel_flow(app_ctx):
    repos = app_ctx.repos
    sid = repos.songs.create(title="شب", artist="علی", telegram_file_id="F", file_unique_id="x")
    c = make_context(app_ctx)
    u = await click(app_ctx, c, f"k:{sid}")
    assert "قالب و قوانین" in txt(u) and "هوش مصنوعی واقعی نیست" in txt(u)
    assert repos.songs.get(sid)["caption"]
    await click(app_ctx, c, f"k:ec:{sid}")
    assert c.user_data["awaiting"] == f"caption:{sid}"
    u = make_update(text="کپشن دستی من")
    await menu.text_message(u, c)
    assert repos.songs.get(sid)["caption"] == "کپشن دستی من" and "ذخیره شد" in txt(u)
    await click(app_ctx, c, f"k:eh:{sid}")
    await menu.text_message(make_update(text="#پاپ علی، شاد"), c)
    assert repos.songs.get(sid)["hashtags"] == "#پاپ #علی #شاد"
    await click(app_ctx, c, f"k:gen:{sid}")
    assert repos.songs.get(sid)["caption"] != "کپشن دستی من"


async def test_caption_validation(app_ctx):
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"k:ec:{sid}")
    u = make_update(text="x" * 1100)
    await menu.text_message(u, c)
    assert "خیلی بلند" in txt(u) and app_ctx.repos.songs.get(sid)["caption"] == "کپشن"
    await click(app_ctx, c, f"k:eh:{sid}")
    u = make_update(text="!!!")
    await menu.text_message(u, c)
    assert "معتبری" in txt(u)
    u = await click(app_ctx, c, "k:999")
    assert "پیدا نشد" in txt(u)


async def test_published_caption_locked(app_ctx):
    sid = ready_song(app_ctx.repos)
    app_ctx.repos.db.execute("UPDATE songs SET status='published' WHERE id=?", (sid,))
    c = make_context(app_ctx)
    assert "قابل ویرایش نیست" in txt(await click(app_ctx, c, f"k:{sid}"))


# ---------- زمان‌بندی ----------
async def test_schedule_quick_and_custom(app_ctx):
    repos = app_ctx.repos
    sid = ready_song(repos)
    c = make_context(app_ctx)
    u = await click(app_ctx, c, f"p:st:{sid}:h3")
    assert "زمان‌بندی شد" in txt(u) and repos.songs.get(sid)["status"] == "scheduled"
    assert repos.queue.active_for_song(sid)["scheduled_at"]
    assert c.bot.send_audio.call_count == 0
    await click(app_ctx, c, f"p:sx:{sid}")
    assert c.user_data["awaiting"] == f"sched:{sid}"
    u = make_update(text="خراب")
    await menu.text_message(u, c)
    assert "نامعتبر" in txt(u) and c.user_data["awaiting"] == f"sched:{sid}"
    u = make_update(text="1405/12/20 21:30")
    await menu.text_message(u, c)
    assert "1405/12/20 21:30" in txt(u) and "awaiting" not in c.user_data
    assert len(repos.queue.list_active()) == 1                  # قبلی جایگزین شد


async def test_schedule_requires_caption_and_ready(app_ctx):
    repos = app_ctx.repos
    sid = repos.songs.create(title="a", artist="b", telegram_file_id="F", file_unique_id="d")
    c = make_context(app_ctx)
    assert "ثبت‌شده در آرشیو" in txt(await click(app_ctx, c, f"p:sc:{sid}"))
    assert "پیدا نشد" in txt(await click(app_ctx, c, "p:st:999:h1"))
    no_cap = ready_song(repos, "nc", caption="")
    repos.songs.update(no_cap, caption=None)
    assert "کپشن" in txt(await click(app_ctx, c, f"p:st:{no_cap}:h1"))
    assert repos.queue.list_active() == []


async def test_due_notification_never_publishes(app_ctx):
    repos = app_ctx.repos
    sid = ready_song(repos)
    past = TU.to_iso(TU.utc_now() - timedelta(minutes=5))
    repos.queue.schedule(sid, "@bia2music1395", past)
    c = make_context(app_ctx)
    sent = await scheduler.notify_due(app_ctx, c.bot)
    assert sent == 1 and c.bot.send_audio.call_count == 0
    kw = c.bot.send_message.call_args
    assert kw.args[0] == ADMIN and "انتشار خودکار انجام نمی‌شود" in kw.args[1]
    assert repos.songs.get(sid)["status"] == "scheduled" and repos.songs.get(sid)["channel_message_id"] is None
    assert repos.queue.active_for_song(sid)["status"] == "due"
    assert await scheduler.notify_due(app_ctx, c.bot) == 0      # یادآوری تکراری نمی‌رود


async def test_due_not_marked_when_notification_fails(app_ctx):
    repos = app_ctx.repos
    sid = ready_song(repos)
    repos.queue.schedule(sid, "@c", TU.to_iso(TU.utc_now() - timedelta(minutes=1)))
    c = make_context(app_ctx)
    c.bot.send_message.side_effect = RuntimeError("net")
    assert await scheduler.notify_due(app_ctx, c.bot) == 0
    assert repos.queue.active_for_song(sid)["status"] == "pending"   # دور بعد دوباره تلاش می‌شود
    c.bot.send_message.side_effect = None
    assert await scheduler.notify_due(app_ctx, c.bot) == 1


async def test_future_schedule_not_notified_and_orphans_cleaned(app_ctx):
    repos = app_ctx.repos
    sid = ready_song(repos)
    repos.queue.schedule(sid, "@c", TU.to_iso(TU.utc_now() + timedelta(hours=1)))
    c = make_context(app_ctx)
    assert await scheduler.notify_due(app_ctx, c.bot) == 0
    repos.queue.schedule(sid, "@c", TU.to_iso(TU.utc_now() - timedelta(minutes=1)))
    repos.db.execute("UPDATE songs SET status='draft' WHERE id=?", (sid,))
    assert await scheduler.notify_due(app_ctx, c.bot) == 0
    assert repos.queue.active_for_song(sid) is None


async def test_due_then_explicit_approval_publishes(app_ctx):
    repos = app_ctx.repos
    sid = ready_song(repos)
    repos.queue.schedule(sid, "@bia2music1395", TU.to_iso(TU.utc_now() - timedelta(minutes=1)))
    c = make_context(app_ctx)
    await scheduler.notify_due(app_ctx, c.bot)
    await click(app_ctx, c, f"p:pv:{sid}")                       # دکمه یادآوری
    fp = preview_fp(c)
    await click(app_ctx, c, f"p:ok:{sid}:{fp}", from_audio=True)
    assert c.bot.send_audio.call_count == 1
    await click(app_ctx, c, f"p:go:{sid}:{fp}", from_audio=True)
    assert repos.songs.get(sid)["status"] == "published" and repos.queue.active_for_song(sid) is None


async def test_queue_list_item_cancel_snooze(app_ctx):
    repos = app_ctx.repos
    sid = ready_song(repos)
    c = make_context(app_ctx)
    assert "زمان‌بندی‌شده‌ای نیست" in txt(await click(app_ctx, c, "p:q"))
    await click(app_ctx, c, f"p:st:{sid}:m21")
    u = await click(app_ctx, c, "m:schedule")
    assert any(b.callback_data == f"p:i:{sid}" for b in buttons(u))
    assert "منتظر زمان مقرر" in txt(await click(app_ctx, c, f"p:i:{sid}"))
    old = repos.queue.active_for_song(sid)["scheduled_at"]
    await click(app_ctx, c, f"p:sn:{sid}")
    assert repos.queue.active_for_song(sid)["scheduled_at"] != old
    u = await click(app_ctx, c, f"p:qc:{sid}")
    assert repos.songs.get(sid)["status"] == "ready" and repos.queue.active_for_song(sid) is None
    assert "ندارد" in txt(await click(app_ctx, c, f"p:i:{sid}"))


async def test_menus_and_card_buttons(app_ctx):
    repos = app_ctx.repos
    sid = ready_song(repos)
    c = make_context(app_ctx)
    assert "آماده انتشار: 1" in txt(await click(app_ctx, c, "m:publish"))
    assert "کپشن" in txt(await click(app_ctx, c, "m:captions"))
    u = await click(app_ctx, c, f"g:v:{sid}")
    cbs = {b.callback_data for b in buttons(u)}
    assert {f"k:{sid}", f"p:pv:{sid}"} <= cbs
    repos.queue.schedule(sid, "@c", "2030-01-01T00:00:00Z")
    assert f"p:i:{sid}" in {b.callback_data for b in buttons(await click(app_ctx, c, f"g:v:{sid}"))}
    # آهنگ منتشرشده حذف یا ویرایش کپشن ندارد
    repos.db.execute("UPDATE songs SET status='published' WHERE id=?", (sid,))
    cbs = {b.callback_data for b in buttons(await click(app_ctx, c, f"g:v:{sid}"))}
    assert f"k:{sid}" not in cbs and f"g:d:{sid}" not in cbs and f"p:pv:{sid}" not in cbs


async def test_publishing_state_recovery_button(app_ctx):
    sid = ready_song(app_ctx.repos)
    app_ctx.repos.db.execute("UPDATE songs SET status='publishing' WHERE id=?", (sid,))
    c = make_context(app_ctx)
    u = await click(app_ctx, c, f"g:v:{sid}")
    assert "نامشخص" in txt(u)
    await click(app_ctx, c, f"g:u:{sid}")
    assert app_ctx.repos.songs.get(sid)["status"] == "ready"


async def test_bad_callbacks(app_ctx):
    c = make_context(app_ctx)
    for data in ("p:zzz:1", "p:pv:abc", "p:st:1:xx", "p:go:1", "k:ec:abc", "p:pv"):
        assert "نامعتبر" in txt(await click(app_ctx, c, data)) or "پیدا نشد" in txt(await click(app_ctx, c, data))
    assert c.bot.send_audio.call_count == 0


# ---------- معرفی ربات در پست‌ها ----------
async def test_promo_button_and_footer_in_preview_and_post(app_ctx):
    app_ctx.bot_username = "Tohidmusic_bot"
    app_ctx.repos.settings.set("promo_footer", "1")          # دکمه پیش‌فرض روشن است
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    prev = c.bot.send_audio.call_args.kwargs
    assert prev["caption"] == "کپشن\n\n#a\n\n🤖 @Tohidmusic_bot"
    url_row = prev["reply_markup"].inline_keyboard[-1][0]
    assert url_row.url == "https://t.me/Tohidmusic_bot"
    fp = preview_fp(c)
    await click(app_ctx, c, f"p:ok:{sid}:{fp}", from_audio=True)
    await click(app_ctx, c, f"p:go:{sid}:{fp}", from_audio=True)
    sent = c.bot.send_audio.call_args.kwargs
    assert sent["chat_id"] == "@bia2music1395"
    assert sent["caption"] == prev["caption"]                      # دقیقاً همان که در پیش‌نمایش دیده شد
    assert sent["reply_markup"].inline_keyboard[0][0].url == "https://t.me/Tohidmusic_bot"
    assert len(sent["reply_markup"].inline_keyboard) == 1          # دکمه‌های کنترلی مدیر در کانال نمی‌رود


async def test_promo_off_means_plain_post(app_ctx):
    app_ctx.bot_username = "Tohidmusic_bot"
    app_ctx.repos.settings.set("promo_button", "0")
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    fp = preview_fp(c)
    await click(app_ctx, c, f"p:go:{sid}:{fp}", from_audio=True)
    sent = c.bot.send_audio.call_args.kwargs
    assert sent["caption"] == "کپشن\n\n#a" and sent["reply_markup"] is None


async def test_toggling_promo_after_preview_invalidates_it(app_ctx):
    app_ctx.bot_username = "Tohidmusic_bot"
    sid = ready_song(app_ctx.repos)
    c = make_context(app_ctx)
    await click(app_ctx, c, f"p:pv:{sid}")
    fp = preview_fp(c)
    app_ctx.repos.settings.set("promo_footer", "1")
    u = await click(app_ctx, c, f"p:go:{sid}:{fp}", from_audio=True)
    assert c.bot.send_audio.call_count == 1 and "تغییر کرده" in txt(u)


async def test_footer_counts_toward_caption_limit(app_ctx):
    app_ctx.bot_username = "Tohidmusic_bot"
    app_ctx.repos.settings.set("promo_footer", "1")
    sid = ready_song(app_ctx.repos, caption="x" * 1000, hashtags="#" + "h" * 15)
    c = make_context(app_ctx)
    assert "حداکثر" in txt(await click(app_ctx, c, f"p:pv:{sid}"))
    assert c.bot.send_audio.call_count == 0


async def test_promo_settings_toggles(app_ctx):
    c = make_context(app_ctx)
    u = await click(app_ctx, c, "s:promo_ft")
    assert app_ctx.repos.settings.get("promo_footer") == "1"
    await click(app_ctx, c, "s:promo_btn")
    assert app_ctx.repos.settings.get("promo_button") == "0"
    await click(app_ctx, c, "s:promo_btn")
    assert app_ctx.repos.settings.get("promo_button") == "1"
    labels = [b.text for b in buttons(await click(app_ctx, c, "m:settings"))]
    assert any("دکمه‌ی ربات" in l and "✅" in l for l in labels)


async def test_no_username_no_promo(app_ctx):
    assert app_ctx.post_options().footer is None and app_ctx.post_options().button_url is None
