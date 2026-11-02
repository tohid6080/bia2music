"""مدیریت پلی‌لیست‌های موضوعی توسط مدیر (y:). کاربران فقط آهنگ‌های منتشرشده‌ی آن‌ها را می‌بینند."""
from __future__ import annotations

import math

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.songs.textutils import clean_text
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import PAGE_SIZE, _b, song_label

NOT_FOUND = "❌ پلی‌لیست پیدا نشد."


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    lists = ctx.repos.playlists.list()
    rows = [[_b(f"{'⭐' if p['is_premium'] else '🎧'} {p['name']} ({p['public']}/{p['total']})", f"y:v:{p['id']}")] for p in lists]
    rows.append([_b("➕ پلی‌لیست جدید", "y:n")])
    rows.append([_b(T.BTN_BACK, "m:main")])
    text = ("🎧 <b>پلی‌لیست‌ها</b>\n(منتشرشده/کل آهنگ‌ها)\n\n"
            + ("برای ساخت پلی‌لیست موضوعی (مثلاً «رانندگی شبانه») دکمه‌ی زیر را بزنید." if not lists else
               "کاربران فقط آهنگ‌های منتشرشده‌ی هر پلی‌لیست را می‌بینند."))
    await show(update, text, InlineKeyboardMarkup(rows))


async def _panel(update, context, pid: int, note: str = "") -> None:
    ctx = ctx_of(context)
    pl = ctx.repos.playlists.get(pid)
    if not pl:
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    songs = ctx.repos.playlists.songs(pid, False, 15, 0)
    body = "\n".join(f"• {esc(song_label(s, 34))}" for s in songs) or "هنوز آهنگی ندارد."
    text = f"🎧 <b>{esc(pl['name'])}</b>\n{pl['public']} منتشرشده از {pl['total']}\n\n{body}" + (f"\n\n{note}" if note else "")
    kb = InlineKeyboardMarkup([
        [_b("➕ افزودن آهنگ", f"y:a:{pid}:0"), _b("➖ حذف آهنگ", f"y:r:{pid}")],
        [_b(f"⭐ ویژه: {'✅' if pl['is_premium'] else '⛔'}", f"y:pm:{pid}")],
        [_b("✏️ تغییر نام", f"y:rn:{pid}"), _b("🗑 حذف پلی‌لیست", f"y:d:{pid}")],
        [_b(T.BTN_BACK, "m:playlists")],
    ])
    await show(update, text, kb)


def _addable(ctx) -> list[dict]:
    songs = ctx.repos.songs.all_published() + ctx.repos.songs.all_with_status("ready", 500) + ctx.repos.songs.all_with_status("scheduled", 500)
    return sorted(songs, key=lambda s: -s["id"])


async def _add_picker(update, context, pid: int, page: int) -> None:
    ctx = ctx_of(context)
    if not ctx.repos.playlists.get(pid):
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    songs = _addable(ctx)
    pages = max(1, math.ceil(len(songs) / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    chunk = songs[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = [[_b(("✅ " if ctx.repos.playlists.has_song(pid, s["id"]) else "⬜ ") + song_label(s, 34)[2:], f"y:ad:{pid}:{s['id']}:{page}")]
            for s in chunk]
    nav = []
    if page > 0:
        nav.append(_b("◀️ قبلی", f"y:a:{pid}:{page - 1}"))
    if page + 1 < pages:
        nav.append(_b("بعدی ▶️", f"y:a:{pid}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_b(T.BTN_BACK, f"y:v:{pid}")])
    text = "➕ آهنگ را بزنید تا اضافه/برداشته شود." if songs else "آهنگ ثبت‌شده‌ای نیست؛ ابتدا آهنگ را در آرشیو ثبت کنید."
    await show(update, text, InlineKeyboardMarkup(rows))


async def show_song_playlists(update, context, song_id: int) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(song_id)
    if not song:
        await show(update, "❌ آهنگ پیدا نشد.", K.back_to_menu())
        return
    lists = ctx.repos.playlists.list()
    rows = [[_b(("✅ " if ctx.repos.playlists.has_song(p["id"], song_id) else "⬜ ") + p["name"], f"y:t:{song_id}:{p['id']}")] for p in lists]
    rows.append([_b("➕ پلی‌لیست جدید", "y:n")])
    rows.append([_b(T.BTN_BACK, f"g:v:{song_id}")])
    await show(update, f"🎧 پلی‌لیست‌های «{esc(song.get('title') or '؟')}»\nبزنید تا اضافه/برداشته شود:", InlineKeyboardMarkup(rows))


@admin_only
async def playlists_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    parts = update.callback_query.data.split(":")
    action = parts[1]
    uid = update.effective_user.id
    context.user_data.pop("awaiting", None)
    try:
        if action == "n":
            context.user_data["awaiting"] = "plnew"
            await show(update, "✏️ نام پلی‌لیست جدید را بنویسید (حداکثر ۴۰ حرف):",
                       InlineKeyboardMarkup([[_b(T.BTN_CANCEL, "m:playlists")]]))
        elif action == "v":
            await _panel(update, context, int(parts[2]))
        elif action == "a":
            await _add_picker(update, context, int(parts[2]), int(parts[3]))
        elif action == "ad":
            pid, sid, page = int(parts[2]), int(parts[3]), int(parts[4])
            if not (ctx.repos.playlists.get(pid) and ctx.repos.songs.get(sid)):
                raise ValueError("missing")
            if ctx.repos.playlists.has_song(pid, sid):
                ctx.repos.playlists.remove_song(pid, sid)
            else:
                ctx.repos.playlists.add_song(pid, sid)
            ctx.repos.logs.add("playlist_song_toggled", uid, f"p={pid} s={sid}")
            await _add_picker(update, context, pid, page)
        elif action == "r":
            pid = int(parts[2])
            songs = ctx.repos.playlists.songs(pid, False, 30, 0)
            rows = [[_b("❌ " + song_label(s, 34)[2:], f"y:rm:{pid}:{s['id']}")] for s in songs]
            rows.append([_b(T.BTN_BACK, f"y:v:{pid}")])
            await show(update, "آهنگی را که می‌خواهید از پلی‌لیست حذف شود بزنید:" if songs else "پلی‌لیست خالی است.", InlineKeyboardMarkup(rows))
        elif action == "pm":
            pl = ctx.repos.playlists.get(int(parts[2]))
            if not pl:
                raise ValueError("missing")
            ctx.repos.playlists.set_premium(pl["id"], not pl["is_premium"])
            await _panel(update, context, pl["id"], "⭐ فقط مشترکین ویژه می‌بینند." if not pl["is_premium"] else "🔓 برای همه باز شد.")
        elif action == "rm":
            ctx.repos.playlists.remove_song(int(parts[2]), int(parts[3]))
            await _panel(update, context, int(parts[2]), "➖ حذف شد.")
        elif action == "rn":
            pid = int(parts[2])
            if not ctx.repos.playlists.get(pid):
                raise ValueError("missing")
            context.user_data["awaiting"] = f"plrename:{pid}"
            await show(update, "✏️ نام جدید را بنویسید:", InlineKeyboardMarkup([[_b(T.BTN_CANCEL, f"y:v:{pid}")]]))
        elif action == "d":
            pid = int(parts[2])
            pl = ctx.repos.playlists.get(pid)
            if not pl:
                raise ValueError("missing")
            await show(update, f"🗑 پلی‌لیست «{esc(pl['name'])}» حذف شود؟ (خود آهنگ‌ها حذف نمی‌شوند)",
                       InlineKeyboardMarkup([[_b("🗑 بله، حذف شود", f"y:dy:{pid}"), _b(T.BTN_CANCEL, f"y:v:{pid}")]]))
        elif action == "dy":
            ctx.repos.playlists.delete(int(parts[2]))
            ctx.repos.logs.add("playlist_deleted", uid, f"p={parts[2]}")
            await show_menu(update, context)
        elif action == "sp":
            await show_song_playlists(update, context, int(parts[2]))
        elif action == "t":
            sid, pid = int(parts[2]), int(parts[3])
            if not (ctx.repos.playlists.get(pid) and ctx.repos.songs.get(sid)):
                raise ValueError("missing")
            if ctx.repos.playlists.has_song(pid, sid):
                ctx.repos.playlists.remove_song(pid, sid)
            else:
                ctx.repos.playlists.add_song(pid, sid)
            await show_song_playlists(update, context, sid)
        else:
            raise ValueError(action)
    except (ValueError, IndexError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    ctx = ctx_of(context)
    name = clean_text(update.effective_message.text, 40)
    kind, _, pid = awaiting.partition(":")
    cancel = InlineKeyboardMarkup([[_b(T.BTN_CANCEL, "m:playlists")]])
    if not name:
        await show(update, "❌ نام معتبر بنویسید یا لغو کنید.", cancel)
        return
    context.user_data.pop("awaiting", None)
    if kind == "plnew":
        try:
            new_id = ctx.repos.playlists.create(name)
        except ValueError:
            await show(update, f"❌ حداکثر {ctx.repos.playlists.MAX_PLAYLISTS} پلی‌لیست مجاز است.", cancel)
            return
        ctx.repos.logs.add("playlist_created", update.effective_user.id, f"p={new_id}")
        await _panel(update, context, new_id, "✅ ساخته شد. آهنگ‌ها را اضافه کنید.")
    else:
        if not ctx.repos.playlists.get(int(pid)):
            await show(update, NOT_FOUND, K.back_to_menu())
            return
        ctx.repos.playlists.rename(int(pid), name)
        await _panel(update, context, int(pid), "✅ نام تغییر کرد.")
