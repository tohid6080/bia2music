import random

import pytest

from musicbot.handlers import admin_users as au, menu, playlists as pl, settings as sh, users as uh
from musicbot.recommend import audience_rank, score_song, suggest_for_user
from tests.conftest import ADMIN, make_context, make_update

U1, U2 = 2001, 2002


def txt(u):
    q = u.callback_query
    return (q.edit_message_text if q else u.effective_message.reply_text).call_args.args[0]


def btns(u):
    q = u.callback_query
    m = (q.edit_message_text if q else u.effective_message.reply_text).call_args.kwargs["reply_markup"]
    return [b for r in m.inline_keyboard for b in r]


def cbs(u):
    return {b.callback_data for b in btns(u) if b.callback_data}


ROUTE = {"u": uh.user_callback, "a": au.admin_users_callback, "y": pl.playlists_callback, "s": sh.settings_callback, "m": menu.menu_callback}


async def click(c, data, user=ADMIN):
    u = make_update(user_id=user, data=data)
    await ROUTE[data[0]](u, c)
    return u


async def say(c, text, user=U1):
    u = make_update(user_id=user, text=text)
    await menu.text_router(u, c)
    return u


def song(repos, uid, title, artist="Ali", status="published", **kw):
    sid = repos.songs.create(title=title, artist=artist, telegram_file_id="F" + uid, file_unique_id=uid)
    repos.songs.update(sid, language_code=kw.get("lang", "fa"), status=status, genre_id=kw.get("genre"), mood_id=kw.get("mood"))
    if status == "published":
        repos.db.execute("UPDATE songs SET post_url=?, channel_message_id=? WHERE id=?", (f"https://t.me/bia2music1395/{sid}", sid, sid))
    return sid


@pytest.fixture
def on(app_ctx):
    app_ctx.repos.settings.set_user_features(True)
    return app_ctx


# ---------- روشن/خاموش ----------
async def test_disabled_by_default_users_see_admin_only_message(app_ctx):
    c = make_context(app_ctx)
    u = make_update(user_id=U1)
    await menu.start(u, c)
    u.effective_message.reply_text.assert_awaited_once()
    assert "اختصاصی مدیر" in u.effective_message.reply_text.call_args.args[0]
    u = await say(c, "سلام")
    assert "اختصاصی مدیر" in txt(u)
    u = await click(c, "u:home", U1)
    u.callback_query.answer.assert_awaited_with("🚧 این بخش فعلاً فعال نیست.", show_alert=True)


async def test_admin_toggle_with_confirmation(app_ctx):
    c = make_context(app_ctx)
    u = await click(c, "s:users")
    assert not app_ctx.repos.settings.user_features_enabled() and "s:users_yes" in cbs(u)
    await click(c, "s:users_yes")
    assert app_ctx.repos.settings.user_features_enabled()
    u = await click(c, "m:settings")
    assert "s:users_off" in cbs(u)
    await click(c, "s:users_off")
    assert not app_ctx.repos.settings.user_features_enabled()
    for a in ("user_features_on", "user_features_off"):
        assert any(l["action"] == a for l in app_ctx.repos.logs.recent(20))


async def test_stranger_cannot_toggle(app_ctx):
    u = make_update(user_id=U1, data="s:users_yes")
    await sh.settings_callback(u, make_context(app_ctx))
    assert not app_ctx.repos.settings.user_features_enabled()


async def test_start_shows_user_menu_when_enabled(on):
    c = make_context(on)
    u = make_update(user_id=U1)
    await menu.start(u, c)
    assert "خوش آمدید" in txt(u)
    assert len(btns(u)) >= 9
    assert on.repos.users.get(U1)


async def test_admin_start_still_admin_menu(on):
    u = make_update()
    await menu.start(u, make_context(on))
    assert "منوی اصلی" in txt(u)


async def test_blocked_user_locked_out(on):
    c = make_context(on)
    await click(c, "u:home", U1)
    on.repos.users.set_blocked(U1, True)
    u = await click(c, "u:home", U1)
    u.callback_query.answer.assert_awaited_with("⛔ دسترسی شما محدود شده است.", show_alert=True)
    u = await say(c, "شب")
    assert "محدود" in txt(u)
    u = make_update(user_id=U1)
    await menu.start(u, c)
    assert "اختصاصی مدیر" in txt(u)


# ---------- جست‌وجو و فقط منتشرشده ----------
async def test_search_shows_only_published(on):
    r = on.repos
    pub = song(r, "p", "شبِ من", "علیرضا")
    song(r, "d", "شب پنهان", status="draft")
    song(r, "r", "شب آماده", status="ready")
    c = make_context(on)
    u = await say(c, "شب")
    assert cbs(u) >= {f"u:v:{pub}"} and sum(x.startswith("u:v:") for x in cbs(u)) == 1
    assert "1 مورد" in txt(u)
    u = await say(c, "عليرضا")       # املای عربی
    assert f"u:v:{pub}" in cbs(u)
    u = await say(c, "هیچی")
    assert "موردی پیدا نشد" in txt(u) and "u:q" in cbs(u)


async def test_song_card_links_to_channel_and_hides_unpublished(on):
    r = on.repos
    pub = song(r, "p", "شب")
    hidden = song(r, "h", "پنهان", status="ready")
    c = make_context(on)
    u = await click(c, f"u:v:{pub}", U1)
    url_btn = [b for b in btns(u) if b.url]
    assert url_btn and url_btn[0].url == f"https://t.me/bia2music1395/{pub}"
    for sid in (hidden, 999):
        assert "پیدا نشد" in txt(await click(c, f"u:v:{sid}", U1))


async def test_category_browse_published_only(on):
    r = on.repos
    a = song(r, "a", "A", mood=1)
    song(r, "b", "B", mood=1, status="ready")
    c = make_context(on)
    u = await click(c, "u:cm", U1)
    assert "u:l:m.1:0" in cbs(u)
    u = await click(c, "u:l:m.1:0", U1)
    assert [x for x in cbs(u) if x.startswith("u:v:")] == [f"u:v:{a}"]
    u = await click(c, "u:cl", U1)
    assert "u:l:l.fa:0" in cbs(u)
    assert "نامعتبر" in txt(await click(c, "u:l:bogus:0", U1))


async def test_pagination(on):
    for i in range(11):
        song(on.repos, f"s{i}", f"آهنگ {i}")
    c = make_context(on)
    await say(c, "آهنگ")
    u = await click(c, "u:l:q:1", U1)
    assert "صفحه 2 از 2" in txt(u) and sum(x.startswith("u:v:") for x in cbs(u)) == 3
    u = await click(c, "u:l:q:0", U1)
    assert "u:l:q:1" in cbs(u)


# ---------- رضایت، پسند، علایق ----------
async def test_like_requires_consent_and_stores_nothing_before(on):
    sid = song(on.repos, "p", "شب")
    c = make_context(on)
    u = await click(c, f"u:lk:{sid}", U1)
    assert "رضایت" in txt(u) and f"u:cy:{sid}" in cbs(u)
    assert on.repos.userdata.like_count(sid) == 0 and not on.repos.userdata.has_consent(U1)
    u = await click(c, f"u:cy:{sid}", U1)
    assert on.repos.userdata.has_consent(U1) and on.repos.userdata.is_liked(U1, sid)
    assert "1 پسند" in txt(u)
    await click(c, f"u:lk:{sid}", U1)                       # برداشتن
    assert not on.repos.userdata.is_liked(U1, sid)


async def test_interest_toggle_needs_consent(on):
    r = on.repos
    with pytest.raises(ValueError):
        r.userdata.toggle_interest(U1, "genre", "1")
    with pytest.raises(ValueError):
        r.userdata.toggle_like(U1, 1)
    c = make_context(on)
    await click(c, "u:home", U1)
    assert "رضایت" in txt(await click(c, "u:i", U1))
    assert "رضایت" in txt(await click(c, "u:ip:g", U1))
    await click(c, "u:it:g:1", U1)                         # بدون رضایت: رد می‌شود
    assert r.userdata.interests(U1) == set()
    await click(c, "u:cy:0", U1)
    u = await click(c, "u:ip:g", U1)
    assert any("⬜" in b.text for b in btns(u))
    u = await click(c, "u:it:g:1", U1)
    assert any(b.text.startswith("✅") for b in btns(u)) and r.userdata.interests(U1) == {("genre", "1")}
    await click(c, "u:it:g:1", U1)
    assert r.userdata.interests(U1) == set()
    for bad in ("u:it:g:999", "u:it:x:1", "u:it:l:zz"):
        assert "نامعتبر" in txt(await click(c, bad, U1))


async def test_my_likes_list(on):
    sid = song(on.repos, "p", "شب")
    c = make_context(on)
    await click(c, "u:home", U1)
    assert "رضایت" in txt(await click(c, "u:l:likes:0", U1))
    await click(c, f"u:cy:{sid}", U1)
    u = await click(c, "u:l:likes:0", U1)
    assert f"u:v:{sid}" in cbs(u)
    assert on.repos.userdata.liked_count(U2) == 0


async def test_delete_all_personal_data(on):
    r = on.repos
    sid = song(r, "p", "شب")
    c = make_context(on)
    await click(c, "u:home", U1)
    await click(c, f"u:cy:{sid}", U1)
    r.userdata.toggle_interest(U1, "mood", "1")
    r.userdata.add_request(U1, "x")
    assert "حذف شود" in txt(await click(c, "u:dx", U1))
    assert r.userdata.is_liked(U1, sid)                    # هنوز تأیید نشده
    await click(c, "u:dy", U1)
    assert not r.userdata.is_liked(U1, sid) and r.userdata.interests(U1) == set() and not r.userdata.has_consent(U1)
    assert r.userdata.new_requests() == []
    u = r.users.get(U1)
    assert u["username"] is None and u["first_name"] is None


async def test_privacy_screen(on):
    assert "رضایت صریح" in txt(await click(make_context(on), "u:pv", U1))


# ---------- پیشنهاد ----------
def test_scoring_and_suggestion(on):
    r = on.repos
    a = song(r, "a", "A", genre=1, mood=1)
    b = song(r, "b", "B", genre=2, mood=2, lang="en")
    cc = song(r, "c", "C", genre=1, mood=3)
    s = {x["id"]: x for x in r.songs.all_published()}
    assert score_song(s[a], [("genre", "1"), ("mood", "1"), ("language", "fa")]) == 5
    assert score_song(s[b], [("genre", "1")]) == 0
    # بدون رضایت، علایق خوانده نمی‌شود
    r.db.execute("INSERT INTO user_interests(telegram_user_id,kind,ref) VALUES (?,?,?)", (U1, "genre", "2"))
    picks = suggest_for_user(r, U1, 3, rng=random.Random(1))
    assert {p["id"] for p in picks} == {a, b, cc}
    # با رضایت، آهنگ مطابق علایق اول می‌آید
    r.users.touch(U1, "u", "U", "fa")
    r.userdata.give_consent(U1)
    assert suggest_for_user(r, U1, 1, rng=random.Random(1))[0]["id"] == b
    assert suggest_for_user(r, U1, 3, exclude=[b], rng=random.Random(1))[0]["id"] != b
    assert suggest_for_user(r, U1, 3, exclude=[a, b, cc]) == []


async def test_suggest_flow_and_cycling(on):
    r = on.repos
    ids = [song(r, f"s{i}", f"T{i}") for i in range(4)]
    c = make_context(on)
    u = await click(c, "u:r", U1)
    first = {x for x in cbs(u) if x.startswith("u:v:")}
    assert len(first) == 3 and "علایق" in txt(u)
    u = await click(c, "u:r", U1)
    second = {x for x in cbs(u) if x.startswith("u:v:")}
    assert len(second) == 1 and second.isdisjoint(first)   # فقط یک آهنگ دیده‌نشده مانده
    u = await click(c, "u:r", U1)                          # فهرست تمام شد ← چرخه از نو
    assert len({x for x in cbs(u) if x.startswith("u:v:")}) == 3


async def test_suggest_empty(on):
    assert "منتشر نشده" in txt(await click(make_context(on), "u:r", U1))


# ---------- پلی‌لیست ----------
async def test_playlist_admin_and_user_views(on):
    r = on.repos
    pub = song(r, "p", "منتشر")
    rdy = song(r, "r", "آماده", status="ready")
    c = make_context(on)
    u = await click(c, "y:n")
    assert c.user_data["awaiting"] == "plnew"
    u = await say(c, "رانندگی شبانه", ADMIN)
    pid = r.playlists.list()[0]["id"]
    assert "ساخته شد" in txt(u)
    await click(c, f"y:ad:{pid}:{pub}:0")
    u = await click(c, f"y:ad:{pid}:{rdy}:0")
    assert r.playlists.get(pid)["total"] == 2 and r.playlists.get(pid)["public"] == 1
    assert sum(b.text.startswith("✅") for b in btns(u)) == 2
    # کاربر فقط آهنگ منتشرشده را می‌بیند
    u = await click(c, "u:p", U1)
    assert f"u:pl:{pid}:0" in cbs(u) and "(1)" in "".join(b.text for b in btns(u))
    u = await click(c, f"u:pl:{pid}:0", U1)
    assert {x for x in cbs(u) if x.startswith("u:v:")} == {f"u:v:{pub}"}
    # حذف آهنگ و تغییر نام
    await click(c, f"y:rm:{pid}:{rdy}")
    assert r.playlists.get(pid)["total"] == 1
    await click(c, f"y:rn:{pid}")
    await say(c, "جدید", ADMIN)
    assert r.playlists.get(pid)["name"] == "جدید"
    # حذف با تأیید؛ آهنگ‌ها می‌مانند
    assert "حذف شود" in txt(await click(c, f"y:d:{pid}")) and r.playlists.get(pid)
    await click(c, f"y:dy:{pid}")
    assert r.playlists.get(pid) is None and r.songs.get(pub)


async def test_empty_playlist_hidden_from_users_and_toggle_from_card(on):
    r = on.repos
    pid = r.playlists.create("خالی")
    sid = song(r, "p", "شب")
    c = make_context(on)
    assert "هنوز پلی‌لیستی" in txt(await click(c, "u:p", U1))
    assert "پیدا نشد" in txt(await click(c, f"u:pl:{pid}:0", U1))
    u = await click(c, f"y:sp:{sid}")
    assert f"y:t:{sid}:{pid}" in cbs(u)
    await click(c, f"y:t:{sid}:{pid}")
    assert r.playlists.has_song(pid, sid)
    await click(c, f"y:t:{sid}:{pid}")
    assert not r.playlists.has_song(pid, sid)


async def test_playlist_limits_and_validation(on):
    r = on.repos
    for i in range(r.playlists.MAX_PLAYLISTS):
        r.playlists.create(f"p{i}")
    c = make_context(on)
    await click(c, "y:n")
    assert "حداکثر" in txt(await say(c, "یکی بیشتر", ADMIN))
    c.user_data["awaiting"] = "plnew"
    assert "معتبر" in txt(await say(c, "@only", ADMIN))
    for bad in ("y:v:999", "y:ad:999:1:0", "y:t:1:2", "y:zzz", "y:v:abc"):
        t = txt(await click(c, bad))
        assert "پیدا نشد" in t or "نامعتبر" in t


async def test_stranger_cannot_manage_playlists(on):
    c = make_context(on)
    u = await click(c, "y:n", U1)
    u.callback_query.edit_message_text.assert_not_called()
    assert on.repos.playlists.list() == []


# ---------- درخواست آهنگ ----------
async def test_song_request_flow_and_limit(on):
    c = make_context(on)
    await click(c, "u:q", U1)
    assert c.user_data["awaiting"] == "urequest"
    u = await say(c, "Sevmishdim از Damla")
    assert "ارسال شد" in txt(u)
    note = c.bot.send_message.call_args
    assert note.args[0] == ADMIN and "Sevmishdim" in note.args[1]
    for _ in range(2):
        await click(c, "u:q", U1)
        await say(c, "یکی دیگر")
    await click(c, "u:q", U1)
    assert "حداکثر" in txt(await say(c, "چهارمی"))
    assert len(on.repos.userdata.new_requests()) == 3
    # کاربر دیگر محدودیت جدا دارد
    c2 = make_context(on)
    await click(c2, "u:q", U2)
    assert "ارسال شد" in txt(await say(c2, "x", U2))


async def test_request_survives_notify_failure(on):
    c = make_context(on)
    c.bot.send_message.side_effect = RuntimeError("down")
    await click(c, "u:q", U1)
    assert "ارسال شد" in txt(await say(c, "آهنگ"))
    assert len(on.repos.userdata.new_requests()) == 1


# ---------- مدیریت کاربران برای مدیر ----------
async def test_admin_users_panel_and_block(on):
    r = on.repos
    c = make_context(on)
    await click(c, "u:home", U1)
    await click(c, "u:cy:0", U1)
    r.userdata.add_request(U1, "درخواست")
    u = await click(c, "m:users")
    t = txt(u)
    assert "کل کاربران: 1" in t and "رضایت ثبت علایق: 1" in t and "درخواست‌های جدید: 1" in t
    u = await click(c, "a:ul")
    assert f"a:uv:{U1}" in cbs(u)
    u = await click(c, f"a:uv:{U1}")
    assert f"a:ub:{U1}" in cbs(u)
    await click(c, f"a:ub:{U1}")
    assert r.users.is_blocked(U1)
    await click(c, f"a:ub:{U1}")
    assert not r.users.is_blocked(U1)
    await click(c, f"a:ub:{ADMIN}")
    assert not r.users.is_blocked(ADMIN)
    assert "کاربر پیدا نشد" in txt(await click(c, "a:uv:424242"))


async def test_admin_cannot_be_listed_or_blocked(on):
    on.repos.users.touch(ADMIN, "adm", "Admin", "fa")
    c = make_context(on)
    assert "هنوز کاربری" in txt(await click(c, "a:ul"))
    await click(c, f"a:ub:{ADMIN}")
    assert not on.repos.users.is_blocked(ADMIN)


async def test_admin_requests_management(on):
    r = on.repos
    r.users.touch(U1, "ali", "علی", "fa")
    a = r.userdata.add_request(U1, "اولی")
    b = r.userdata.add_request(U1, "دومی")
    c = make_context(on)
    u = await click(c, "a:rq")
    assert "اولی" in txt(u) and "@ali" in txt(u)
    await click(c, f"a:rd:{a}")
    u = await click(c, f"a:rx:{b}")
    assert "درخواست جدیدی نیست" in txt(u)
    assert "نامعتبر" in txt(await click(c, "a:rd:abc"))


async def test_admin_interest_stats_are_aggregate_only(on):
    r = on.repos
    for uid in (U1, U2):
        r.users.touch(uid, f"user{uid}", "N", "fa")
        r.userdata.give_consent(uid)
    r.userdata.toggle_interest(U1, "genre", "1")
    r.userdata.toggle_interest(U2, "genre", "1")
    r.userdata.toggle_interest(U2, "mood", "3")
    t = txt(await click(make_context(on), "a:int"))
    assert "پاپ (2)" in t and "شاد (1)" in t
    assert "user2001" not in t and str(U1) not in t


async def test_admin_interest_stats_empty(on):
    assert "هنوز کسی" in txt(await click(make_context(on), "a:int"))


async def test_admin_suggest_ranks_ready_songs_by_audience(on):
    r = on.repos
    pop = song(r, "pop", "پاپی", status="ready", genre=1)
    rap = song(r, "rap", "رپی", status="ready", genre=2)
    r.users.touch(U1, "u", "U", "fa")
    r.userdata.give_consent(U1)
    r.userdata.toggle_interest(U1, "genre", "2")
    ranked = audience_rank(r, r.songs.all_with_status("ready"))
    assert ranked[0][0]["id"] == rap and ranked[0][1] > ranked[1][1] == 0
    u = await click(make_context(on), "m:suggest")
    assert "رپی" in txt(u) and f"g:v:{rap}" in cbs(u)


async def test_admin_suggest_empty(on):
    assert "آهنگ آماده‌ای ندارید" in txt(await click(make_context(on), "m:suggest"))


async def test_admin_can_use_user_view_even_when_disabled(app_ctx):
    c = make_context(app_ctx)
    u = await click(c, "u:home", ADMIN)
    assert "خوش آمدید" in txt(u)
    u = make_update(text="شب")
    await menu.text_router(u, c)  # مدیر: متن آزاد ← منو (نه جست‌وجو)
    assert "منوی زیر" in txt(u)


async def test_admin_in_user_search_awaiting(app_ctx):
    song(app_ctx.repos, "p", "شب")
    c = make_context(app_ctx)
    await click(c, "u:s", ADMIN)
    u = make_update(text="شب")
    await menu.text_router(u, c)
    assert "1 مورد" in txt(u)


async def test_group_chat_ignored(on):
    u = make_update(user_id=U1, text="شب", chat_type="supergroup")
    await menu.text_router(u, make_context(on))
    u.effective_message.reply_text.assert_not_called()
