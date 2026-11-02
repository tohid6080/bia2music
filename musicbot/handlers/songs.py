"""دریافت آهنگ، کارت آهنگ، ویرایش اطلاعات، ثبت در آرشیو و حذف. هیچ انتشاری در کانال انجام نمی‌شود."""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from musicbot.handlers import archive
from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.songs.service import extract_meta, ingest_audio
from musicbot.songs.textutils import clean_text
from musicbot.ui import keyboards as K
from musicbot.ui import song_ui as U
from musicbot.ui import texts as T

log = logging.getLogger(__name__)
NOT_FOUND = "❌ این آهنگ پیدا نشد (ممکن است حذف شده باشد)."


async def show_songs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    await show(update, U.songs_menu_text(ctx.repos.songs.counts_by_status()), U.songs_menu_keyboard())


async def show_card(update: Update, context: ContextTypes.DEFAULT_TYPE, song_id: int, note: Optional[str] = None) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(song_id)
    if not song:
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    repo = ctx.repos.songs
    similar = repo.find_similar(song)
    extras = {
        "aa_l": repo.same_artist_unset(song, "language_code") if song.get("language_code") else 0,
        "aa_g": repo.same_artist_unset(song, "genre_id") if song.get("genre_id") else 0,
        "next": song["status"] == "published" and repo.next_unclassified(song_id) is not None,
    }
    await show(update, U.song_card_text(song, similar, note), U.song_card_keyboard(song, similar, extras))


@admin_only
async def receive_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    context.user_data.pop("awaiting", None)
    message = update.effective_message
    meta = extract_meta(message)
    if meta is None:
        await show(update, "⚠️ فقط فایل صوتی (MP3، M4A، FLAC و ...) پذیرفته می‌شود.", K.back_to_menu())
        return

    async def downloader() -> Optional[bytes]:
        tg_file = await context.bot.get_file(meta.file_id)
        return bytes(await tg_file.download_as_bytearray())

    result = await ingest_audio(ctx.repos, meta, update.effective_user.id, downloader)
    if result.duplicate:
        ctx.repos.logs.add("song_duplicate", update.effective_user.id, f"id={result.song['id']} by={result.reason}")
        await show(update, U.duplicate_text(result.song, result.reason), U.duplicate_keyboard(result.song))
        return
    note = ("📎 فایل به آهنگ آماده‌شده از رادار وصل شد. اطلاعات را کامل کنید." if result.attached
            else "✅ پیش‌نویس ساخته شد. اطلاعات را کامل کنید و در آرشیو ثبت کنید.")
    await show_card(update, context, result.song["id"], note)


@admin_only
async def songs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    parts = update.callback_query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    user_id = update.effective_user.id
    context.user_data.pop("awaiting", None)  # هر دکمه‌ای حالت انتظار متن را لغو می‌کند

    try:
        if action == "add":
            await show(update, U.ADD_HELP, U.add_help_keyboard())
        elif action == "l":
            await archive.show_list(update, context, parts[2], int(parts[3]))
        elif action == "cd":
            await archive.show_dim_menu(update, context, parts[2])
        elif action == "q":
            await archive.ask_search(update, context)
        elif action == "v":
            await show_card(update, context, int(parts[2]))
        elif action == "e":
            await _edit_prompt(update, context, int(parts[2]), parts[3])
        elif action == "s":
            await _set_category(update, context, int(parts[2]), parts[3], parts[4], user_id)
        elif action in ("r", "u"):
            await _change_status(update, context, int(parts[2]), action, user_id)
        elif action == "nx":
            nxt = ctx.repos.songs.next_unclassified(int(parts[2]))
            if nxt is None:
                await show(update, "✅ همه‌ی آهنگ‌های منتشرشده زبان دارند.", K.back_to_menu())
            else:
                await show_card(update, context, nxt)
        elif action == "aa":
            sid, dim = int(parts[2]), parts[3]
            column = {"l": "language_code", "g": "genre_id"}[dim]
            song = ctx.repos.songs.get(sid)
            if not song:
                raise ValueError("song")
            n = ctx.repos.songs.apply_to_same_artist(song, column)
            ctx.repos.logs.add("song_bulk_category", user_id, f"id={sid} {column} n={n}")
            await show_card(update, context, sid, f"✅ برای {n} آهنگ دیگر این خواننده اعمال شد.")
        elif action == "d":
            await _delete_confirm(update, context, int(parts[2]))
        elif action == "dy":
            await _delete(update, context, int(parts[2]), user_id)
        else:
            await show(update, "❌ دکمه نامعتبر است.", K.back_to_menu())
    except (IndexError, ValueError, KeyError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def _edit_prompt(update, context, song_id: int, field: str) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(song_id)
    if not song:
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    if field in ("t", "a"):
        context.user_data["awaiting"] = f"song_{field}:{song_id}"
        label = U.FIELD_LABEL[field]
        await show(update, f"✏️ {label} را بفرستید (حداکثر ۱۲۰ حرف):", U.cancel_to_card(song_id))
    elif field in U.DIM_TABLE:
        items = ctx.repos.categories.list(U.DIM_TABLE[field])
        await show(update, f"{U.DIM_TITLE[field]} را انتخاب کنید:", U.picker_keyboard(song_id, field, items))
    else:
        raise ValueError("field")


async def _set_category(update, context, song_id: int, dim: str, val: str, user_id: int) -> None:
    ctx = ctx_of(context)
    if dim not in U.DIM_TABLE or not ctx.repos.songs.get(song_id):
        raise ValueError("bad")
    column = {"l": "language_code", "g": "genre_id", "m": "mood_id"}[dim]
    if val == "0":
        value = None
    else:
        key = val if dim == "l" else int(val)
        if not ctx.repos.categories.exists(U.DIM_TABLE[dim], key):
            raise ValueError("bad category")
        value = key
    ctx.repos.songs.update(song_id, **{column: value})
    ctx.repos.logs.add("song_updated", user_id, f"id={song_id} {column}")
    await show_card(update, context, song_id, "✅ ذخیره شد.")


async def _change_status(update, context, song_id: int, action: str, user_id: int) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(song_id)
    if not song:
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    if action == "r":
        missing = U.missing_fields(song)
        if missing:
            await show_card(update, context, song_id, "⚠️ برای ثبت در آرشیو این موارد باید کامل شود: " + "، ".join(missing))
            return
        ctx.repos.songs.update(song_id, status="ready")
        ctx.repos.logs.add("song_registered", user_id, f"id={song_id}")
        await show_card(update, context, song_id, "✅ در آرشیو ثبت شد. (انتشار در مرحله سوم فعال می‌شود.)")
    elif song["status"] == "ready":
        ctx.repos.songs.update(song_id, status="draft")
        ctx.repos.logs.add("song_unregistered", user_id, f"id={song_id}")
        await show_card(update, context, song_id, "↩️ به پیش‌نویس برگشت.")
    elif song["status"] == "publishing" and not song.get("channel_message_id"):
        # مدیر کانال را بررسی کرده و می‌داند پست نرفته است
        ctx.repos.songs.update(song_id, status="ready")
        ctx.repos.logs.add("song_publish_reset", user_id, f"id={song_id}")
        await show_card(update, context, song_id, "↩️ به وضعیت «آماده» برگشت.")
    else:
        await show_card(update, context, song_id)


async def _delete_confirm(update, context, song_id: int) -> None:
    song = ctx_of(context).repos.songs.get(song_id)
    if not song:
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    if song["status"] in ("scheduled", "published"):
        await show_card(update, context, song_id, "⛔ آهنگ زمان‌بندی‌شده یا منتشرشده حذف نمی‌شود.")
        return
    await show(update, f"🗑 این آهنگ حذف شود؟\n\n{U.song_card_text(song)}\n\nاین کار قابل بازگشت نیست.",
               U.delete_confirm_keyboard(song_id))


async def _delete(update, context, song_id: int, user_id: int) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(song_id)
    if not song or song["status"] in ("scheduled", "published"):
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    ctx.repos.songs.delete(song_id)
    ctx.repos.logs.add("song_deleted", user_id, f"id={song_id}")
    await show(update, "🗑 آهنگ حذف شد.", U.songs_menu_keyboard())


async def receive_song_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    ctx = ctx_of(context)
    kind, _, sid = awaiting.partition(":")
    song_id = int(sid)
    value = clean_text(update.effective_message.text)
    if not value:
        await show(update, "❌ متن معتبر بفرستید یا لغو کنید.", U.cancel_to_card(song_id))
        return
    if not ctx.repos.songs.get(song_id):
        context.user_data.pop("awaiting", None)
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    column = "title" if kind == "song_t" else "artist"
    ctx.repos.songs.update(song_id, **{column: value})
    ctx.repos.logs.add("song_updated", update.effective_user.id, f"id={song_id} {column}")
    context.user_data.pop("awaiting", None)
    await show_card(update, context, song_id, "✅ ذخیره شد.")
