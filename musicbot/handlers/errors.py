from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from musicbot.context import get_ctx
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T

log = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # لاگ فایل از طریق RedactingFilter پاکسازی می‌شود؛ در دیتابیس فقط نوع خطا ذخیره می‌شود.
    log.error("Unhandled error", exc_info=context.error)
    try:
        get_ctx(context.application).repos.logs.add("error", None, type(context.error).__name__, level="error")
    except Exception:  # noqa: BLE001
        pass
    if isinstance(update, Update) and update.effective_chat is not None:
        try:
            await context.bot.send_message(update.effective_chat.id, T.GENERIC_ERROR, reply_markup=K.back_to_menu())
        except Exception:  # noqa: BLE001
            pass
