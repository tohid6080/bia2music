import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from musicbot.handlers import importing as ih, menu, songs as sh
from musicbot.importer import ChannelImporter, ImportJob, ImportStats, guess_categories, parse_message_number
from tests.conftest import ADMIN, make_context, make_update

REF = "@bia2music1395"


def audio_msg(i, uid=None, title=None, performer=None, name=None, caption=None):
    a = SimpleNamespace(file_id=f"F{i}", file_unique_id=uid or f"U{i}", file_size=1000, duration=200,
                        performer=performer, title=title, file_name=name)
    return SimpleNamespace(message_id=10_000 + i, audio=a, document=None, caption=caption)


def text_msg(i):
    return SimpleNamespace(message_id=10_000 + i, audio=None, document=None, caption=None)


class ChannelBot:
    """فقط فوروارد/حذف دارد؛ هر متد ارسال دیگری AttributeError می‌دهد (پس آزمون ثابت می‌کند چیز دیگری فرستاده نمی‌شود)."""

    def __init__(self, posts, errors=None):
        self.posts, self.errors = posts, errors or {}
        self.forwards, self.deleted = [], []

    async def forward_message(self, chat_id, from_chat_id, message_id, disable_notification=False):
        self.forwards.append((chat_id, from_chat_id, message_id, disable_notification))
        err = self.errors.get(message_id)
        if err:
            if isinstance(err, list):
                if err:
                    raise err.pop(0)
            else:
                raise err
        if message_id not in self.posts:
            raise BadRequest("Message to forward not found")
        return self.posts[message_id]

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


async def no_sleep(_):
    return None


def importer(bot, repos, sleeps=None):
    async def sl(x):
        if sleeps is not None:
            sleeps.append(x)
    return ChannelImporter(bot, repos, REF, ADMIN, pace=0, sleep=sl)


async def run(imp, a, b, stop=None):
    st = ImportStats()
    err = await imp.run(a, b, st, stop or asyncio.Event())
    return err, st


async def test_basic_import(repos):
    bot = ChannelBot({
        1: audio_msg(1, title="شب", performer="علیرضا", caption="#پاپ #غمگین قطعه"),
        2: text_msg(2),
        4: audio_msg(4, name="Ali - Shab.mp3"),
        5: audio_msg(5, uid="U1"),                    # فایل تکراری با پست ۱
        6: audio_msg(6, title="روز", performer="کیان"),
    })
    err, st = await run(importer(bot, repos), 1, 6)
    assert err is None
    assert (st.scanned, st.imported, st.other, st.missing, st.duplicates, st.errors) == (6, 3, 1, 1, 1, 0)
    s = repos.songs.find_by_channel_message(1)
    assert s["status"] == "published" and s["post_url"] == "https://t.me/bia2music1395/1"
    assert s["title"] == "شب" and s["artist"] == "علیرضا" and s["telegram_file_id"] == "F1" and s["file_unique_id"] == "U1"
    assert s["genre_name"] == "پاپ" and s["mood_name"] == "غمگین" and s["language_code"] is None and "قطعه" in s["caption"]
    f = repos.songs.find_by_channel_message(4)
    assert (f["artist"], f["title"]) == ("Ali", "Shab")
    # همه‌ی فورواردها فقط به چت مدیر، بی‌صدا؛ و هر پیام موقت پاک شد (جز پست پاک‌شده)
    assert all(c == ADMIN and f == REF and silent for c, f, _, silent in bot.forwards)
    assert sorted(m for _, m in bot.deleted) == [10_001, 10_002, 10_004, 10_005, 10_006]
    assert all(c == ADMIN for c, _ in bot.deleted)


async def test_rerun_skips_already_imported_without_forwarding(repos):
    bot = ChannelBot({1: audio_msg(1), 2: audio_msg(2)})
    await run(importer(bot, repos), 1, 2)
    n = len(bot.forwards)
    err, st = await run(importer(bot, repos), 1, 2)
    assert len(bot.forwards) == n and st.duplicates == 2 and st.imported == 0


async def test_existing_unpublished_song_becomes_published(repos):
    sid = repos.songs.create(title="a", artist="b", telegram_file_id="OLD", file_unique_id="U7")
    repos.songs.update(sid, status="ready", language_code="fa")
    repos.queue.schedule(sid, REF, "2030-01-01T00:00:00Z")
    bot = ChannelBot({7: audio_msg(7, uid="U7")})
    _, st = await run(importer(bot, repos), 7, 7)
    s = repos.songs.get(sid)
    assert st.updated == 1 and s["status"] == "published" and s["channel_message_id"] == 7
    assert s["post_url"].endswith("/7") and repos.queue.active_for_song(sid) is None
    assert repos.songs.count() == 1


async def test_already_published_existing_is_duplicate(repos):
    sid = repos.songs.create(title="a", artist="b", telegram_file_id="OLD", file_unique_id="U8")
    repos.songs.mark_published(sid, 3, "https://t.me/x/3")
    _, st = await run(importer(ChannelBot({8: audio_msg(8, uid="U8")}), repos), 8, 8)
    assert st.duplicates == 1 and repos.songs.count() == 1


async def test_retry_after_waits_and_retries(repos):
    sleeps = []
    bot = ChannelBot({1: audio_msg(1)}, {1: [RetryAfter(3)]})
    _, st = await run(importer(bot, repos, sleeps), 1, 1)
    assert st.imported == 1 and 4.0 in sleeps and len(bot.forwards) == 2


async def test_network_errors_counted_then_continue(repos):
    bot = ChannelBot({1: audio_msg(1), 2: audio_msg(2)}, {1: TimedOut("t")})
    err, st = await run(importer(bot, repos), 1, 2)
    assert err is None and st.errors == 1 and st.imported == 1


async def test_fatal_errors_stop_run(repos):
    err, st = await run(importer(ChannelBot({}, {1: Forbidden("x")}), repos), 1, 5)
    assert "ادمین" in err and st.scanned == 0
    err, st = await run(importer(ChannelBot({}, {1: BadRequest("Chat not found")}), repos), 1, 5)
    assert err and "نپذیرفت" in err
    ok, st = await run(importer(ChannelBot({}, {1: BadRequest("Message can't be forwarded")}), repos), 1, 1)
    assert ok is None and st.missing == 1


async def test_stop_event(repos):
    bot = ChannelBot({i: audio_msg(i) for i in range(1, 11)})
    stop = asyncio.Event()
    st = ImportStats()

    async def prog(s):
        if s.scanned >= 4:
            stop.set()

    await importer(bot, repos).run(1, 10, st, stop, prog, progress_every=2)
    assert st.scanned == 4 and st.last_id == 4 and repos.songs.count() == 4


def test_guess_categories(repos):
    g = lambda *t: guess_categories(repos, *t)  # noqa: E731
    assert g("#پاپ #غمگین")["genre_id"] and g("#پاپ #غمگین")["mood_id"]
    assert g("آهنگ پاپ و رپ")["genre_id"] is None                    # مبهم ← حدس نمی‌زند
    assert g("#موزیک_ایرانی")["language_code"] == "fa"
    assert g("موزیک ایرانی")["language_code"] == "fa"
    assert g("آهنگ ترکی")["language_code"] == "tr"
    assert g("ایرانی و ترکی")["language_code"] is None               # مبهم
    assert g("سایر سبک‌ها")["genre_id"] is None
    assert g("#بی_کلام")["genre_id"] is not None
    assert g(None, "", None) == {"language_code": None, "genre_id": None, "mood_id": None}


def test_parse_message_number():
    assert parse_message_number("https://t.me/bia2music1395/2450") == 2450
    assert parse_message_number("t.me/c/1234567/89?single") == 89
    assert parse_message_number(" ۱۲ ".translate(str.maketrans("۱۲", "12"))) == 12
    assert parse_message_number("https://t.me/bia2music1395/7/") == 7
    for bad in ("", "abc", "0", "https://t.me/bia2music1395", "t.me/bia2music1395", "@bia2music1395"):
        assert parse_message_number(bad) is None


# ---------- هندلرها ----------
def txt(u):
    q = u.callback_query
    return (q.edit_message_text if q else u.effective_message.reply_text).call_args.args[0]


def cbs(u):
    q = u.callback_query
    m = (q.edit_message_text if q else u.effective_message.reply_text).call_args.kwargs["reply_markup"]
    return {b.callback_data for r in m.inline_keyboard for b in r if b.callback_data}


async def click(c, data, user=ADMIN):
    u = make_update(user_id=user, data=data)
    router = {"i": ih.import_callback, "g": sh.songs_callback, "m": menu.menu_callback}
    await router[data[0]](u, c)
    return u


def import_ctx(app_ctx, posts, errors=None):
    c = make_context(app_ctx)
    cb = ChannelBot(posts, errors)
    cb.send_message = AsyncMock(return_value=SimpleNamespace(message_id=900))
    cb.edit_message_text = AsyncMock()
    c.bot = cb
    c.application.bot = cb
    return c, cb


@pytest.fixture(autouse=True)
def fast_pace(monkeypatch):
    monkeypatch.setattr(ih, "PACE", 0)


async def test_test_mode_flow_asks_for_last_id_then_runs(app_ctx):
    posts = {i: audio_msg(i, title=f"T{i}", performer="P") for i in range(1, 31)}
    c, cb = import_ctx(app_ctx, posts)
    u = await click(c, "i:t")
    assert c.user_data["awaiting"] == "import_last" and c.user_data["import_after"] == "t"
    u = make_update(text="https://t.me/bia2music1395/30")
    await menu.text_router(u, c)
    job = c.application.bot_data["import_job"]
    await job.task
    assert (job.start, job.end, job.mode) == (11, 30, "test") and not job.running
    assert job.stats.imported == 20 and app_ctx.repos.songs.count("published") == 20
    assert app_ctx.repos.settings.get("import_last_id") == "30"
    assert app_ctx.repos.settings.get("import_next_id") is None          # حالت آزمایشی پیشرفت را عوض نمی‌کند
    final = cb.edit_message_text.call_args.args[0]
    assert "پایان" in final and "جدید: 20" in final
    assert all(call.args[0] == ADMIN for call in cb.send_message.call_args_list)   # فقط به مدیر پیام رفته


async def test_full_flow_confirm_progress_and_resume(app_ctx):
    posts = {i: audio_msg(i, title=f"T{i}", performer="P") for i in range(1, 61)}
    c, cb = import_ctx(app_ctx, posts)
    app_ctx.repos.settings.set("import_last_id", "60")
    u = await click(c, "i:s")
    assert "پست 1 تا 60" in txt(u) and "i:go" in cbs(u) and "دقیقه" in txt(u)
    assert "import_job" not in c.application.bot_data                    # تا تأیید شروع نمی‌شود
    # توقف وسط کار
    real = cb.forward_message

    async def stopper(**kw):
        if kw["message_id"] == 30:
            c.application.bot_data["import_job"].stop.set()
        return await real(**kw)

    cb.forward_message = stopper
    await click(c, "i:go")
    job = c.application.bot_data["import_job"]
    await job.task
    assert job.stats.last_id == 30 and app_ctx.repos.settings.get("import_next_id") == "31"
    assert "متوقف شد" in cb.edit_message_text.call_args.args[0]
    # ادامه از ۳۱
    cb.forward_message = real
    u = await click(c, "i:s")
    assert "پست 31 تا 60" in txt(u)
    await click(c, "i:go")
    await c.application.bot_data["import_job"].task
    assert app_ctx.repos.songs.count("published") == 60 and app_ctx.repos.settings.get("import_next_id") == "61"
    u = await click(c, "i:s")
    assert "بررسی شده‌اند" in txt(u)
    await click(c, "i:rs")
    assert app_ctx.repos.settings.get("import_next_id") == "1"


async def test_busy_and_stop_buttons(app_ctx):
    c, _ = import_ctx(app_ctx, {})
    job = ImportJob(mode="full", start=1, end=9)
    c.application.bot_data["import_job"] = job
    for data in ("i:t", "i:s", "i:go", "i:rs", "i:id"):
        assert "در حال اجراست" in txt(await click(c, data))
    u = await click(c, "i:menu")
    assert "در حال اجرا" in txt(u) and "i:x" in cbs(u)
    u = await click(c, "i:x")
    assert job.stop.is_set()


async def test_requires_channel_and_admin_status(app_ctx, bot):
    c, _ = import_ctx(app_ctx, {})
    app_ctx.repos.settings.set("import_last_id", "5")
    bot.member.status = "member"
    assert "ادمین" in txt(await click(c, "i:t"))
    assert "import_job" not in c.application.bot_data
    bot.member.status = "administrator"
    object.__setattr__(app_ctx.settings, "channel_id", None)
    assert "تنظیم نشده" in txt(await click(c, "i:t"))


async def test_bad_last_id_text_and_cancel(app_ctx):
    c, _ = import_ctx(app_ctx, {})
    await click(c, "i:id")
    u = make_update(text="هیچ")
    await menu.text_router(u, c)
    assert "معتبر نیست" in txt(u) and c.user_data["awaiting"] == "import_last"
    u = await click(c, "i:menu")
    assert "awaiting" not in c.user_data


async def test_fatal_error_reported_in_summary(app_ctx):
    c, cb = import_ctx(app_ctx, {}, {5: Forbidden("x")})
    app_ctx.repos.settings.set("import_last_id", "5")
    await click(c, "i:t")
    await c.application.bot_data["import_job"].task
    assert "ادمین" in cb.edit_message_text.call_args.args[0]


async def test_stranger_cannot_import(app_ctx):
    c, cb = import_ctx(app_ctx, {1: audio_msg(1)})
    app_ctx.repos.settings.set("import_last_id", "1")
    u = await click(c, "i:t", user=555)
    assert "import_job" not in c.application.bot_data and not cb.forwards


# ---------- دسته‌بندی سریع ----------
def pub(repos, uid, artist="Ali", lang=None, genre=None):
    sid = repos.songs.create(title=uid, artist=artist, telegram_file_id="F", file_unique_id=uid)
    repos.songs.update(sid, status="published", language_code=lang, genre_id=genre)
    return sid


async def test_apply_language_to_same_artist(app_ctx):
    r = app_ctx.repos
    a, b, cc = pub(r, "a", lang="fa"), pub(r, "b"), pub(r, "c")
    other = pub(r, "d", artist="Zed")
    keep = pub(r, "e", lang="tr")                      # قبلاً زبان دارد؛ بازنویسی نشود
    c = make_context(app_ctx)
    u = await click(c, f"g:v:{a}")
    assert f"g:aa:{a}:l" in cbs(u) and "2 آهنگ دیگر" in "".join(b_.text for r_ in
        u.callback_query.edit_message_text.call_args.kwargs["reply_markup"].inline_keyboard for b_ in r_)
    u = await click(c, f"g:aa:{a}:l")
    assert "برای 2 آهنگ" in txt(u)
    assert r.songs.get(b)["language_code"] == "fa" and r.songs.get(cc)["language_code"] == "fa"
    assert r.songs.get(other)["language_code"] is None and r.songs.get(keep)["language_code"] == "tr"
    u = await click(c, f"g:v:{a}")
    assert f"g:aa:{a}:l" not in cbs(u)
    # بدون زبان روی خود آهنگ، چیزی اعمال نمی‌شود
    assert r.songs.apply_to_same_artist(r.songs.get(other), "language_code") == 0
    assert "نامعتبر" in txt(await click(c, f"g:aa:{a}:x"))


async def test_next_unclassified_and_filter(app_ctx):
    r = app_ctx.repos
    a, b, cc = pub(r, "a", "X1"), pub(r, "b", "X2"), pub(r, "c", "X3")
    r.songs.update(b, language_code="fa")
    c = make_context(app_ctx)
    u = await click(c, "m:archive")
    assert "g:l:nolang:0" in cbs(u) and "i:menu" in cbs(u)
    u = await click(c, "g:l:nolang:0")
    assert "2 مورد" in txt(u) and f"g:v:{b}" not in cbs(u)
    u = await click(c, f"g:nx:{cc}")
    assert "X1" in txt(u) and f"g:nx:{a}" in cbs(u)         # کارت بعدیِ بدون زبان باز شد و دکمه‌ی «بعدی» دارد
    assert r.songs.next_unclassified(cc) == a and r.songs.next_unclassified(a) == cc   # چرخشی
    r.songs.update(a, language_code="fa")
    r.songs.update(cc, language_code="fa")
    assert "همه‌ی آهنگ‌های منتشرشده زبان دارند" in txt(await click(c, f"g:nx:{a}"))
    u = await click(c, "m:archive")
    assert "g:l:nolang:0" not in cbs(u)


async def test_published_card_shows_original_caption(app_ctx):
    r = app_ctx.repos
    sid = pub(r, "a")
    r.db.execute("UPDATE songs SET caption='کپشن قدیمی کانال' WHERE id=?", (sid,))
    assert "کپشن قدیمی کانال" in txt(await click(make_context(app_ctx), f"g:v:{sid}"))


async def test_all_missing_gives_warning(app_ctx):
    c, cb = import_ctx(app_ctx, {})                 # هیچ پستی وجود ندارد (مثلاً شماره‌ی آخر اشتباه)
    app_ctx.repos.settings.set("import_last_id", "25")
    await click(c, "i:t")
    await c.application.bot_data["import_job"].task
    assert "هیچ پستی خوانده نشد" in cb.edit_message_text.call_args.args[0]
