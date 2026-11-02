from types import SimpleNamespace

from musicbot.handlers import menu, songs as sh
from musicbot.ui import song_ui as U
from tests.conftest import make_context, make_update


def txt(u):
    q = u.callback_query
    return (q.edit_message_text if q else u.effective_message.reply_text).call_args.args[0]


def kb(u):
    q = u.callback_query
    m = (q.edit_message_text if q else u.effective_message.reply_text).call_args.kwargs["reply_markup"]
    return [b for row in m.inline_keyboard for b in row]


def audio(uid="U1", performer="علی", title="شب", size=1000):
    return SimpleNamespace(file_id="F" + uid, file_unique_id=uid, file_size=size, duration=185,
                           performer=performer, title=title, file_name="a.mp3")


async def add(app_ctx, c=None, **kw):
    c = c or make_context(app_ctx)
    uid = kw.get("uid", "U1")
    # محتوای هر فایل متفاوت است، مگر اینکه آزمایش خودش برخورد هش بخواهد
    if not kw.pop("same_content", False) and hasattr(c.bot.get_file, "return_value"):
        c.bot.get_file.return_value.download_as_bytearray.return_value = bytearray(uid.encode())
    u = make_update(audio=audio(**kw))
    await sh.receive_audio(u, c)
    return u, c


async def click(app_ctx, c, data):
    u = make_update(data=data)
    await (sh.songs_callback if data.startswith("g:") else menu.menu_callback)(u, c)
    return u


async def test_intake_creates_draft_card(app_ctx):
    u, c = await add(app_ctx)
    assert "پیش‌نویس ساخته شد" in txt(u) and "شب" in txt(u) and "علی" in txt(u)
    assert app_ctx.repos.songs.count() == 1
    assert app_ctx.repos.songs.get(1)["file_hash"]
    assert app_ctx.repos.songs.get(1)["status"] == "draft"


async def test_intake_duplicate(app_ctx):
    await add(app_ctx)
    u, _ = await add(app_ctx)
    assert "آهنگ تکراری" in txt(u) and app_ctx.repos.songs.count() == 1
    assert any(b.callback_data == "g:v:1" for b in kb(u))


async def test_hash_duplicate_different_unique_id(app_ctx):
    await add(app_ctx, uid="U1", same_content=True)
    u, _ = await add(app_ctx, uid="U2", same_content=True)
    assert "آهنگ تکراری" in txt(u) and app_ctx.repos.songs.count() == 1


async def test_complete_flow_register(app_ctx):
    _, c = await add(app_ctx, performer=None, title=None)  # بدون برچسب
    song = app_ctx.repos.songs.get(1)
    # ثبت ناقص رد می‌شود
    u = await click(app_ctx, c, "g:r:1")
    assert "نام خواننده" in txt(u) and "زبان" in txt(u)  # عنوان از نام فایل آمده
    assert app_ctx.repos.songs.get(1)["status"] == "draft"
    # ویرایش متن
    u = await click(app_ctx, c, "g:e:1:t")
    assert c.user_data["awaiting"] == "song_t:1"
    u = make_update(text="شبِ  @spam من")
    await menu.text_message(u, c)
    assert app_ctx.repos.songs.get(1)["title"] == "شبِ من" and "awaiting" not in c.user_data
    await click(app_ctx, c, "g:e:1:a")
    await menu.text_message(make_update(text="علیرضا"), c)
    # دسته‌بندی
    u = await click(app_ctx, c, "g:e:1:l")
    assert any(b.callback_data == "g:s:1:l:fa" for b in kb(u))
    await click(app_ctx, c, "g:s:1:l:fa")
    await click(app_ctx, c, "g:s:1:g:1")
    u = await click(app_ctx, c, "g:s:1:m:1")
    s = app_ctx.repos.songs.get(1)
    assert (s["language_name"], s["genre_name"], s["mood_name"]) == ("فارسی", "پاپ", "عاشقانه")
    u = await click(app_ctx, c, "g:r:1")
    assert app_ctx.repos.songs.get(1)["status"] == "ready" and "ثبت شد" in txt(u)
    assert {"song_registered", "song_updated", "song_added"} <= {l["action"] for l in app_ctx.repos.logs.recent(50)}
    # بازگشت به پیش‌نویس
    await click(app_ctx, c, "g:u:1")
    assert app_ctx.repos.songs.get(1)["status"] == "draft"


async def test_invalid_category_rejected(app_ctx):
    _, c = await add(app_ctx)
    u = await click(app_ctx, c, "g:s:1:g:9999")
    assert "نامعتبر" in txt(u)
    assert app_ctx.repos.songs.get(1)["genre_id"] is None
    u = await click(app_ctx, c, "g:s:1:l:zz")
    assert "نامعتبر" in txt(u)


async def test_clear_category(app_ctx):
    _, c = await add(app_ctx)
    await click(app_ctx, c, "g:s:1:l:fa")
    await click(app_ctx, c, "g:s:1:l:0")
    assert app_ctx.repos.songs.get(1)["language_code"] is None


async def test_delete_requires_confirmation(app_ctx):
    _, c = await add(app_ctx)
    u = await click(app_ctx, c, "g:d:1")
    assert "حذف شود" in txt(u) and app_ctx.repos.songs.count() == 1
    assert any(b.callback_data == "g:v:1" for b in kb(u))  # لغو
    await click(app_ctx, c, "g:dy:1")
    assert app_ctx.repos.songs.count() == 0


async def test_published_cannot_be_deleted(app_ctx):
    _, c = await add(app_ctx)
    app_ctx.repos.db.execute("UPDATE songs SET status='published' WHERE id=1")
    u = await click(app_ctx, c, "g:d:1")
    assert "حذف نمی‌شود" in txt(u)
    await click(app_ctx, c, "g:dy:1")
    assert app_ctx.repos.songs.count() == 1


async def test_missing_song_and_bad_callbacks(app_ctx):
    c = make_context(app_ctx)
    for data in ("g:v:999", "g:e:999:t", "g:r:999", "g:d:999", "g:dy:999"):
        assert "پیدا نشد" in txt(await click(app_ctx, c, data))
    for data in ("g:v:abc", "g:zzz", "g:l:all", "g:s:1:x:1", "g:l:bogus:0"):
        assert "نامعتبر" in txt(await click(app_ctx, c, data))


async def test_cancel_awaiting_by_button(app_ctx):
    _, c = await add(app_ctx)
    await click(app_ctx, c, "g:e:1:t")
    await click(app_ctx, c, "g:v:1")  # دکمه لغو
    assert "awaiting" not in c.user_data


async def test_empty_text_rejected(app_ctx):
    _, c = await add(app_ctx)
    await click(app_ctx, c, "g:e:1:t")
    u = make_update(text="@only https://t.me/x")
    await menu.text_message(u, c)
    assert "متن معتبر" in txt(u) and c.user_data["awaiting"] == "song_t:1"


async def test_list_pagination_and_filters(app_ctx):
    c = make_context(app_ctx)
    for i in range(11):
        await add(app_ctx, c, uid=f"U{i}", title=f"t{i}", performer="p")
    u = await click(app_ctx, c, "g:l:all:0")
    btns = kb(u)
    assert sum(b.callback_data.startswith("g:v:") for b in btns) == U.PAGE_SIZE
    assert any(b.callback_data == "g:l:all:1" for b in btns) and "11 مورد" in txt(u)
    u = await click(app_ctx, c, "g:l:all:1")
    assert sum(b.callback_data.startswith("g:v:") for b in kb(u)) == 3
    u = await click(app_ctx, c, "g:l:all:99")  # خارج از بازه ← آخرین صفحه
    assert "صفحه 2 از 2" in txt(u)
    u = await click(app_ctx, c, "g:l:draft:0")
    assert "11 مورد" in txt(u)
    u = await click(app_ctx, c, "g:l:ready:0")
    assert "موردی پیدا نشد" in txt(u)


async def test_search_flow(app_ctx):
    c = make_context(app_ctx)
    await add(app_ctx, c, uid="A", performer="علیرضا", title="شب")
    await add(app_ctx, c, uid="B", performer="كيان", title="روز")  # ك/ي عربی
    u = await click(app_ctx, c, "g:q")
    assert c.user_data["awaiting"] == "search"
    u = make_update(text="کیان")
    await menu.text_message(u, c)
    assert "1 مورد" in txt(u)
    u = await click(app_ctx, c, "g:l:q:0")  # صفحه‌بندی با همان جست‌وجو
    assert "1 مورد" in txt(u)
    u = make_update(text="نیست")
    c.user_data["awaiting"] = "search"
    await menu.text_message(u, c)
    assert "موردی پیدا نشد" in txt(u)


async def test_search_state_expired(app_ctx):
    u = await click(app_ctx, make_context(app_ctx), "g:l:q:0")
    assert "منقضی" in txt(u)


async def test_category_browse(app_ctx):
    _, c = await add(app_ctx)
    await click(app_ctx, c, "g:s:1:l:fa")
    u = await click(app_ctx, c, "g:cd:l")
    assert any(b.text == "فارسی (1)" and b.callback_data == "g:l:l.fa:0" for b in kb(u))
    u = await click(app_ctx, c, "g:l:l.fa:0")
    assert "زبان: فارسی" in txt(u) and "1 مورد" in txt(u)


async def test_menus(app_ctx):
    c = make_context(app_ctx)
    await add(app_ctx, c)
    u = await click(app_ctx, c, "m:songs")
    assert "مدیریت آهنگ‌ها" in txt(u) and "پیش‌نویس: 1" in txt(u)
    u = await click(app_ctx, c, "m:archive")
    assert "آرشیو موسیقی" in txt(u)
    u = await click(app_ctx, c, "g:add")
    assert "فایل صوتی" in txt(u)


async def test_stranger_cannot_use_songs(app_ctx):
    c = make_context(app_ctx)
    u = make_update(user_id=555, data="g:dy:1")
    await sh.songs_callback(u, c)
    u.callback_query.edit_message_text.assert_not_called()
    u = make_update(user_id=555, audio=audio())
    await sh.receive_audio(u, c)
    assert app_ctx.repos.songs.count() == 0


async def test_non_audio_document_rejected(app_ctx):
    doc = SimpleNamespace(file_id="d", file_unique_id="d", file_size=1, file_name="a.pdf", mime_type="application/pdf")
    u = make_update(document=doc)
    await sh.receive_audio(u, make_context(app_ctx))
    assert "فقط فایل صوتی" in txt(u) and app_ctx.repos.songs.count() == 0


async def test_download_failure_still_creates(app_ctx):
    c = make_context(app_ctx)
    async def boom(_): raise RuntimeError("x")
    c.bot.get_file = boom
    u, _ = await add(app_ctx, c)
    assert "پیش‌نویس ساخته شد" in txt(u) and app_ctx.repos.songs.get(1)["file_hash"] is None


def test_all_song_callbacks_fit_and_have_back():
    song = {"id": 123456789, "status": "draft", "title": "t", "artist": "a", "language_name": None,
            "genre_name": None, "mood_name": None, "duration_seconds": 1, "file_size": 1}
    sim = [{"id": 987654321, "status": "ready", "title": "t", "artist": "a"}]
    for status in ("draft", "ready", "archived"):
        song["status"] = status
        k = U.song_card_keyboard(song, sim)
        assert any("بازگشت" in b.text for r in k.inline_keyboard for b in r)
        for r in k.inline_keyboard:
            assert len(r) <= 2
