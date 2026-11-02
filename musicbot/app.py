from __future__ import annotations

import asyncio
import logging
import sys

from telegram import BotCommand, Update
from telegram.ext import (Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, MessageHandler, MessageReactionHandler,
                          PreCheckoutQueryHandler, filters)

from musicbot.ai import create_provider, create_recognizer, get_ai_status
from musicbot.channel import ChannelService
from musicbot.config import ConfigError, Settings, load_settings
from musicbot.context import KEY, AppContext
from musicbot.db import Database, Repositories
from musicbot.handlers import backfill as backfill_h, radar as radar_h, ai_status as ai_h, growth as growth_h, growth_content as growth_content_h, admin_users as admin_users_h, campaigns as campaigns_h, importing as importing_h, premium as premium_h, stats as stats_h, captions as captions_h, menu, playlists as playlists_h, users as users_h, publish as publish_h, settings as settings_h, songs as songs_h
from musicbot.handlers.errors import error_handler
from musicbot.logging_setup import setup_logging
from musicbot.publishing.scheduler import run_scheduler

log = logging.getLogger(__name__)


def register_handlers(app: Application) -> None:
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", menu.start, filters=private))
    app.add_handler(CommandHandler("menu", menu.menu_command, filters=private))
    app.add_handler(CommandHandler("cancel", menu.cancel_command, filters=private))
    app.add_handler(CallbackQueryHandler(menu.menu_callback, pattern=r"^m:"))
    app.add_handler(CallbackQueryHandler(settings_h.settings_callback, pattern=r"^s:"))
    app.add_handler(CallbackQueryHandler(songs_h.songs_callback, pattern=r"^g:"))
    app.add_handler(CallbackQueryHandler(captions_h.captions_callback, pattern=r"^k:"))
    app.add_handler(CallbackQueryHandler(publish_h.publish_callback, pattern=r"^p:"))
    app.add_handler(CallbackQueryHandler(admin_users_h.admin_users_callback, pattern=r"^a:"))
    app.add_handler(CallbackQueryHandler(playlists_h.playlists_callback, pattern=r"^y:"))
    app.add_handler(CallbackQueryHandler(users_h.user_callback, pattern=r"^u:"))
    app.add_handler(CallbackQueryHandler(importing_h.import_callback, pattern=r"^i:"))
    app.add_handler(CallbackQueryHandler(stats_h.stats_callback, pattern=r"^t:"))
    app.add_handler(CallbackQueryHandler(ai_h.ai_callback, pattern=r"^z:"))
    app.add_handler(CallbackQueryHandler(growth_h.growth_callback, pattern=r"^r:"))
    app.add_handler(CallbackQueryHandler(radar_h.radar_callback, pattern=r"^x:"))
    app.add_handler(CallbackQueryHandler(backfill_h.backfill_callback, pattern=r"^b:"))
    app.add_handler(CallbackQueryHandler(growth_content_h.content_callback, pattern=r"^w:"))
    app.add_handler(ChatMemberHandler(growth_h.chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(campaigns_h.campaigns_callback, pattern=r"^d:"))
    app.add_handler(CallbackQueryHandler(premium_h.premium_callback, pattern=r"^v:"))
    app.add_handler(CommandHandler("terms", premium_h.terms_command, filters=private))
    app.add_handler(CommandHandler("paysupport", premium_h.paysupport_command, filters=private))
    app.add_handler(PreCheckoutQueryHandler(premium_h.precheckout))
    app.add_handler(MessageHandler(private & filters.SUCCESSFUL_PAYMENT, premium_h.successful_payment))
    app.add_handler(MessageReactionHandler(stats_h.reaction_count,
                                           message_reaction_types=MessageReactionHandler.MESSAGE_REACTION_COUNT_UPDATED))
    app.add_handler(CallbackQueryHandler(settings_h.channel_confirm_callback, pattern=r"^c:confirm$"))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, menu.text_router))
    app.add_handler(
        MessageHandler(private & (filters.AUDIO | filters.Document.ALL | filters.VOICE | filters.VIDEO), songs_h.receive_audio)
    )
    app.add_error_handler(error_handler)


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(
        [BotCommand("start", "منوی اصلی"), BotCommand("menu", "منوی اصلی"), BotCommand("cancel", "لغو عملیات جاری"), BotCommand("terms", "شرایط اشتراک ویژه"),
         BotCommand("paysupport", "پشتیبانی پرداخت")]
    )
    me = await app.bot.get_me()
    log.info("Bot started as @%s", me.username)
    ctx: AppContext = app.bot_data[KEY]
    ctx.bot_username = me.username
    from musicbot.publishing.timeutil import utc_now

    app.bot_data["started_at"] = utc_now()
    ctx.repos.logs.add("bot_started", None, f"@{me.username}")
    if not ctx.effective_channel_ref():
        log.warning("CHANNEL_ID تنظیم نشده است؛ از منوی تنظیمات کانال را مشخص کنید.")
    # زمان‌بند فقط یادآوری می‌فرستد؛ هیچ‌چیز را منتشر نمی‌کند.
    app.bot_data["scheduler_task"] = asyncio.create_task(run_scheduler(ctx, app.bot))


async def _post_shutdown(app: Application) -> None:
    tasks = [app.bot_data.get("scheduler_task")]
    if app.bot_data.get("app_ctx") and app.bot_data["app_ctx"].radar is not None:
        await app.bot_data["app_ctx"].radar.aclose()
    for key in ("import_job", "ai_job", "promo_job"):
        job = app.bot_data.get(key)
        if job and job.task:
            tasks.append(job.task)
    for task in tasks:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def build_application(settings: Settings, db: Database | None = None) -> Application:
    db = db or Database(settings.database_path)
    db.migrate()
    repos = Repositories(db)
    repos.admins.ensure_owner(settings.admin_user_id)
    repos.ai.set("provider", settings.ai_provider)
    repos.ai.set("model", settings.ai_model)

    app = Application.builder().token(settings.bot_token).post_init(_post_init).post_shutdown(_post_shutdown).build()
    ctx = AppContext(
        settings=settings,
        repos=repos,
        ai_provider=create_provider(settings),
        recognizer=create_recognizer(settings),
        channel=ChannelService(app.bot),
    )
    if ctx.ai_provider.is_real_ai:
        ctx.ai_provider.usage_hook = ctx.record_ai_usage      # شمارش توکن‌ها برای نمایش هزینه
    app.bot_data[KEY] = ctx
    register_handlers(app)
    return app


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"❌ خطای تنظیمات: {exc}", file=sys.stderr)
        raise SystemExit(1)
    setup_logging(settings.log_level)
    status = get_ai_status(settings)
    log.info("AI real active=%s provider=%s", status.real_ai_active, status.active_provider)
    app = build_application(settings)
    app.run_polling(allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY, Update.PRE_CHECKOUT_QUERY, Update.MESSAGE_REACTION_COUNT,
                         Update.CHAT_MEMBER], drop_pending_updates=True)
