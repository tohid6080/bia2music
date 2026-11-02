"""ربات تلگرام Bia2Music (مرحله‌ی ۱): /start و /app مینی‌اپ را با دکمه‌ی web_app باز می‌کنند؛ /admin فقط برای مدیر و فقط آمار واقعی."""
from __future__ import annotations

import html
import logging

from sqlalchemy import func, select, text
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Update, WebAppInfo
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from b2m.bot.texts import t
from b2m.core.config import Settings, load_settings
from b2m.db import models as M
from b2m.db.session import make_engine, make_session_factory

log = logging.getLogger("b2m.bot")


def webapp_markup(settings: Settings, lang: str | None):
    if not settings.webapp_url:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "open"), web_app=WebAppInfo(settings.webapp_url))]])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st: Settings = context.application.bot_data["settings"]
    lang = update.effective_user.language_code if update.effective_user else None
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.effective_message.reply_text(t(lang, "private_only"))
        return
    markup = webapp_markup(st, lang)
    if markup is None:
        await update.effective_message.reply_text(t(lang, "no_url"))
        return
    await update.effective_message.reply_text(t(lang, "start"), parse_mode=ParseMode.HTML, reply_markup=markup)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(t(update.effective_user.language_code, "help"))


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text(t(update.effective_user.language_code, "unknown"))


def admin_stats_text(settings: Settings, sf) -> str:
    with sf() as db:
        users = db.scalar(select(func.count()).select_from(M.User)) or 0
        songs = db.scalar(select(func.count()).select_from(M.Song).where(M.Song.status == "published")) or 0
        db.execute(text("SELECT 1"))
    return (f"📊 <b>آمار Bia2Music</b>\nکاربران وارد‌شده به مینی‌اپ: {users}\nآهنگ‌های منتشرشده در آرشیو: {songs}\n"
            f"آدرس مینی‌اپ: {html.escape(settings.webapp_url) if settings.webapp_url else 'تنظیم نشده'}\n\n"
            "ℹ️ مدیریت آهنگ‌ها، مسابقه‌ها و انتشار در مراحل بعدی ساخته می‌شود؛ تا آن زمان ربات مدیریت قبلی (musicbot) برای آرشیو و انتشار کانال قابل استفاده است.")


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st: Settings = context.application.bot_data["settings"]
    u = update.effective_user
    if st.admin_user_id is None or u.id != st.admin_user_id:                # فقط ADMIN_USER_ID
        await update.effective_message.reply_text(t(u.language_code, "denied"))
        return
    await update.effective_message.reply_text(admin_stats_text(st, context.application.bot_data["sf"]), parse_mode=ParseMode.HTML)


async def post_init(app: Application) -> None:
    st: Settings = app.bot_data["settings"]
    await app.bot.set_my_commands([BotCommand("start", "شروع / Start"), BotCommand("app", "باز کردن برنامه / Open app"), BotCommand("help", "راهنما / Help")])
    if st.webapp_url:
        await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Bia2Music", web_app=WebAppInfo(st.webapp_url)))
        log.info("دکمه‌ی منوی مینی‌اپ تنظیم شد.")
    else:
        log.warning("WEBAPP_URL تنظیم نشده؛ دکمه‌ی مینی‌اپ ساخته نشد.")


def build_application(settings: Settings) -> Application:
    app = Application.builder().token(settings.bot_token).post_init(post_init).build()
    app.bot_data["settings"] = settings
    app.bot_data["sf"] = make_session_factory(make_engine(settings.database_url))
    app.add_handler(CommandHandler(["start", "app"], start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))
    return app
