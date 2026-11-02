from __future__ import annotations

import functools
import html
import logging
from typing import Awaitable, Callable, Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from musicbot.auth import is_admin
from musicbot.context import AppContext, get_ctx
from musicbot.ui import texts as T

log = logging.getLogger(__name__)
Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

esc = html.escape


def ctx_of(context: ContextTypes.DEFAULT_TYPE) -> AppContext:
    return get_ctx(context.application)


async def show(update: Update, text: str, markup: Optional[InlineKeyboardMarkup] = None) -> None:
    """اگر از دکمه آمده باشد پیام را ویرایش می‌کند (چت تمیز می‌ماند)، وگرنه پیام جدید می‌فرستد."""
    query = update.callback_query
    if query is not None and getattr(getattr(query, "message", None), "audio", None):
        # پیام فایل صوتی (پیش‌نمایش) متن قابل ویرایش ندارد؛ پیام جدید می‌فرستیم.
        await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
    if query is not None:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise
        return
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


def admin_only(fn: Handler) -> Handler:
    """هر هندلر مدیریتی باید با این دکوراتور محافظت شود."""

    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        ctx = ctx_of(context)
        user, chat = update.effective_user, update.effective_chat
        user_id = user.id if user else None
        private = chat is not None and chat.type == ChatType.PRIVATE
        if not (private and is_admin(ctx.settings, ctx.repos, user_id)):
            ctx.repos.logs.add("unauthorized_access", user_id, level="warning")
            if update.callback_query is not None:
                await update.callback_query.answer(T.NOT_ADMIN_ALERT, show_alert=True)
            elif private and update.effective_message is not None:
                await update.effective_message.reply_text(T.NOT_ADMIN)
            return
        if update.callback_query is not None:
            await update.callback_query.answer()
        await fn(update, context)

    return wrapper
