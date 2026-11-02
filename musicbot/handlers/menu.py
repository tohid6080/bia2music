from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.auth import is_admin  # noqa: F401
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.handlers import settings as settings_h
from musicbot.handlers import ai_status as ai_h
from musicbot.handlers import archive as archive_h
from musicbot.handlers import songs as songs_h
from musicbot.handlers import publish as publish_h
from musicbot.handlers import admin_users as admin_users_h
from musicbot.handlers import playlists as playlists_h
from musicbot.handlers import users as users_h
from musicbot.handlers import importing as importing_h
from musicbot.handlers import campaigns as campaigns_h
from musicbot.handlers import stats as stats_h
from musicbot.handlers import growth as growth_h
from musicbot.handlers import growth_content as growth_content_h
from musicbot.handlers import radar as radar_h
from musicbot.handlers import premium as premium_h


def clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ("awaiting", "pending_channel", "search_q", "u_q", "u_seen", "import_after"):
        context.user_data.pop(key, None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start برای همه باز است، اما فقط مدیر منو می‌بیند."""
    ctx = ctx_of(context)
    user, chat = update.effective_user, update.effective_chat
    if user is None or chat is None or chat.type != ChatType.PRIVATE:
        return
    from musicbot.auth import is_admin

    if not is_admin(ctx.settings, ctx.repos, user.id):
        if await users_h.user_start(update, context):
            return
        ctx.repos.logs.add("unauthorized_start", user.id, level="warning")
        await update.effective_message.reply_text(T.NOT_ADMIN)
        return
    await _main_menu(update, context)
    ctx.repos.logs.add("admin_start", user.id)


@admin_only
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _main_menu(update, context)


@admin_only
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_flow(context)
    await show(update, T.CANCELLED, K.back_to_menu())


async def _main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_flow(context)
    await show(update, T.MAIN_MENU, K.main_menu())


@admin_only
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    key = update.callback_query.data.split(":", 1)[1]
    if key == "main":
        await _main_menu(update, context)
        return
    clear_flow(context)
    if key == "settings":
        await settings_h.show_settings(update, context)
    elif key == "songs":
        await songs_h.show_songs_menu(update, context)
    elif key == "archive":
        await archive_h.show_archive_menu(update, context)
    elif key == "users":
        await admin_users_h.show_users_menu(update, context)
    elif key == "suggest":
        await admin_users_h.show_suggest(update, context)
    elif key == "playlists":
        await playlists_h.show_menu(update, context)
    elif key == "stats":
        await stats_h.show_overview(update, context)
    elif key == "radar":
        await radar_h.show_hub(update, context)
    elif key == "growth":
        await growth_h.show_hub(update, context)
    elif key == "ads":
        await campaigns_h.show_hub(update, context)
    elif key == "captions":
        await publish_h.show_captions_menu(update, context)
    elif key == "publish":
        await publish_h.show_publish_menu(update, context)
    elif key == "schedule":
        await publish_h.show_queue(update, context)
    elif key == "ai":
        await ai_h.show_ai_status(update, context)
    elif key == "help":
        await show(update, T.HELP_TEXT, K.back_to_menu())
    else:
        title = next((t for k, t, _ in T.MENU_ITEMS if k == key), None)
        if title is None:
            await _main_menu(update, context)
            return
        await show(update, T.SECTION_COMING.format(title=esc(title)), K.back_to_menu())


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """متن آزاد: مدیر ← منوی مدیریت؛ کاربر عادی ← جست‌وجو (اگر امکانات کاربران روشن باشد)."""
    ctx = ctx_of(context)
    user, chat = update.effective_user, update.effective_chat
    if user is None or chat is None or chat.type != ChatType.PRIVATE:
        return
    if is_admin(ctx.settings, ctx.repos, user.id):
        if (context.user_data.get("awaiting") or "") in ("usearch", "urequest"):
            await users_h.user_text(update, context)
        else:
            await text_message(update, context)
        return
    reason = users_h._allowed(ctx, user.id)
    if reason is None:
        await users_h.user_text(update, context)
    elif reason == users_h.DISABLED_TEXT:
        ctx.repos.logs.add("unauthorized_access", user.id, level="warning")
        await update.effective_message.reply_text(T.NOT_ADMIN)
    else:
        await update.effective_message.reply_text(reason)


@admin_only
async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    awaiting = context.user_data.get("awaiting") or ""
    if awaiting == "channel":
        await settings_h.receive_channel_text(update, context)
    elif awaiting == "search":
        await archive_h.receive_search_text(update, context)
    elif awaiting.startswith(("caption:", "hashtags:")):
        from musicbot.handlers import captions as captions_h

        await captions_h.receive_text(update, context, awaiting)
    elif awaiting.startswith(("xrg:", "xm", "xw", "xl:", "xt")):
        await radar_h.receive_text(update, context, awaiting)
    elif awaiting.startswith(("wtx:", "wms:")):
        await growth_content_h.receive_text(update, context, awaiting)
    elif awaiting.startswith("grnew:"):
        await growth_h.receive_text(update, context, awaiting)
    elif awaiting == "ailimit":
        await ai_h.receive_limit(update, context)
    elif awaiting.startswith("prem:"):
        await premium_h.receive_text(update, context, awaiting)
    elif awaiting.startswith(("cmp:", "cmpnew:")):
        await campaigns_h.receive_text(update, context, awaiting)
    elif awaiting == "import_last":
        await importing_h.receive_last_id(update, context)
    elif awaiting.startswith(("plnew", "plrename:")):
        await playlists_h.receive_text(update, context, awaiting)
    elif awaiting.startswith("sched:"):
        await publish_h.receive_sched_text(update, context, awaiting)
    elif awaiting.startswith("song_"):
        await songs_h.receive_song_text(update, context, awaiting)
    else:
        await show(update, T.USE_MENU, K.main_menu())
