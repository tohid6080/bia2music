"""🔁 اعمال دکمه‌ی ربات روی پست‌های قبلی کانال (b:). فقط با دکمه‌ی مدیر، با آزمایش روی ۱ پست و تأیید دوم؛ قابل توقف و برگشت."""
from __future__ import annotations

import asyncio
import html
import logging
import math

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, show
from musicbot.promo_backfill import BackfillJob, BackfillStats, PromoBackfill
from musicbot.publishing.captions import post_markup
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b

log = logging.getLogger(__name__)
esc = html.escape
JOB_KEY = "promo_job"
PACE = 1.5
SECONDS_PER_POST = 1.8


def _stats_text(st: BackfillStats) -> str:
    return (f"🔎 بررسی‌شده: {st.scanned}\n✅ انجام‌شده: {st.done}\n♻️ از قبل همان دکمه بود: {st.already}\n"
            f"🗑 پست پاک‌شده/غیرقابل‌ویرایش (رد شد): {st.skipped}\n⚠️ خطا (بعداً دوباره): {st.errors}")


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    ctx = ctx_of(context)
    c = ctx.repos.songs.promo_counts()
    opts = ctx.post_options()
    job = context.application.bot_data.get(JOB_KEY)
    lines = [
        "🔁 <b>اعمال دکمه‌ی ربات روی پست‌های قبلی کانال</b>\n",
        f"🔗 دکمه‌ی ربات زیر پست (⚙️ تنظیمات): {'✅ روشن' if opts.button_url else '⛔ خاموش یا نام ربات نامشخص'}",
        f"📤 پست‌های منتشرشده/واردشده‌ی دارای پست در کانال: <b>{c['eligible']}</b>",
        f"✅ دکمه اعمال شده: {c['applied']} · رد‌شده: {c['skipped']}",
        "\n• فقط <b>دکمه‌ی لینک</b> اضافه می‌شود؛ متن، کپشن و فایل هیچ پستی تغییر نمی‌کند.",
        "• «خط ربات در انتهای کپشن» روی پست‌های قبلی <b>اعمال نمی‌شود</b>: Bot API برای آن باید کل کپشن را دوباره بنویسد و قالب‌بندی/لینک‌های داخل پست‌های قدیمی از بین می‌رود.",
        "• اگر پستی از قبل دکمه‌ی دیگری داشته باشد، جایگزین می‌شود (Bot API امکان خواندنش را نمی‌دهد).",
        "• ربات باید در کانال ادمین با حق «Edit messages of others» باشد.",
        "• هر زمان می‌توانید دکمه را از همه برداشت.",
    ]
    if job and job.running:
        lines.append(f"\n⏳ <b>در حال اجرا</b> ({'اعمال' if job.mode == 'apply' else 'برداشتن'})\n{_stats_text(job.stats)}")
        rows = [[_b("⏹ توقف", "b:x"), _b("🔄 به‌روزرسانی", "b:menu")], [_b(T.BTN_BACK, "m:settings")]]
    else:
        rows = [[_b("🧪 آزمایش روی ۱ پست (جدیدترین)", "b:t")],
                [_b("▶️ اعمال روی همه‌ی پست‌های قبلی", "b:a")],
                [_b("↩️ برداشتن دکمه از پست‌های اعمال‌شده", "b:rm")],
                [_b("↺ دوباره امتحان رد‌شده‌ها", "b:rs")] if c["skipped"] else [],
                [_b(T.BTN_BACK, "m:settings")]]
        rows = [r for r in rows if r]
    if note:
        lines.append(f"\n{note}")
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))


@admin_only
async def backfill_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    action = update.callback_query.data.split(":")[1]
    job = context.application.bot_data.get(JOB_KEY)
    running = bool(job and job.running)
    if action == "x":
        if running:
            job.stop.set()
        await show_menu(update, context, "⏹ در حال توقف..." if running else "")
        return
    if action == "menu":
        await show_menu(update, context)
        return
    if running:
        await show_menu(update, context, "⏳ یک عملیات در حال اجراست.")
        return
    if action == "rs":
        ctx.repos.songs.promo_reset_skipped()
        await show_menu(update, context, "↺ پست‌های رد‌شده دوباره قابل امتحان شدند.")
    elif action in ("t", "a", "rm"):
        mode = "remove" if action == "rm" else "apply"
        problem = await _precheck(ctx, mode)
        if problem:
            await show(update, f"❌ {esc(problem)}", InlineKeyboardMarkup([[_b(T.BTN_BACK, "b:menu")]]))
            return
        if action == "t":
            await _start(update, context, "apply", 1)
            return
        n = len(ctx.repos.songs.promo_targets(mode, 5000))
        if n == 0:
            await show_menu(update, context, "✅ پستی برای این کار نمانده است.")
            return
        minutes = math.ceil(n * SECONDS_PER_POST / 60)
        what = "برداشتن دکمه از" if mode == "remove" else "اضافه‌کردن دکمه‌ی ربات به"
        await show(update, f"{'↩️' if mode == 'remove' else '▶️'} <b>{what} {n} پست کانال</b>\n⏱ حدود {minutes} دقیقه\n\n"
                           "• فقط دکمه‌ی لینک ویرایش می‌شود؛ متن و فایل دست نمی‌خورد.\n• اگر هنوز «🧪 آزمایش روی ۱ پست» را نزده‌اید، اول آن را امتحان کنید و کانال را ببینید.\n"
                           "• Termux باید باز بماند؛ هر زمان می‌توانید توقف و بعداً ادامه دهید.\n\nادامه می‌دهید؟",
                   InlineKeyboardMarkup([[_b("✅ بله، انجام شود", f"b:go{'r' if mode == 'remove' else 'a'}"), _b(T.BTN_CANCEL, "b:menu")]]))
    elif action in ("goa", "gor"):
        mode = "remove" if action == "gor" else "apply"
        problem = await _precheck(ctx, mode)
        if problem:
            await show(update, f"❌ {esc(problem)}", InlineKeyboardMarkup([[_b(T.BTN_BACK, "b:menu")]]))
            return
        await _start(update, context, mode, None)
    else:
        await show_menu(update, context)


async def _precheck(ctx, mode: str):
    ref = ctx.effective_channel_ref()
    if not ref:
        return T.CHANNEL_NOT_SET
    if mode == "apply" and not ctx.post_options().button_url:
        return "دکمه‌ی ربات زیر پست خاموش است (⚙️ تنظیمات ← 🔗 دکمه‌ی ربات) یا نام کاربری ربات هنوز مشخص نیست."
    status = await ctx.channel.check(ref)
    if not status.ok or not status.bot_is_admin:
        return "ربات باید در کانال ادمین باشد (⚙️ تنظیمات ← 📡 وضعیت اتصال)."
    return None


async def _start(update, context, mode: str, limit) -> None:
    ctx = ctx_of(context)
    bd = context.application.bot_data
    job = BackfillJob(mode=mode, limit=limit)
    bd[JOB_KEY] = job
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id, "⏳ شروع شد...", reply_markup=InlineKeyboardMarkup([[_b("⏹ توقف", "b:x")]]))
    ctx.repos.logs.add("promo_backfill_started", update.effective_user.id, f"{mode} limit={limit}")
    job.task = asyncio.create_task(_run(context.application, ctx, job, chat_id, msg.message_id))


async def _edit(bot, chat_id: int, message_id: int, text: str, markup=None) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception:  # noqa: BLE001
        pass


async def _run(app, ctx, job: BackfillJob, chat_id: int, message_id: int) -> None:
    opts = ctx.post_options()
    runner = PromoBackfill(app.bot, ctx.repos, ctx.effective_channel_ref(), post_markup(opts), pace=PACE)
    stop_kb = InlineKeyboardMarkup([[_b("⏹ توقف", "b:x")]])

    async def progress(st: BackfillStats) -> None:
        await _edit(app.bot, chat_id, message_id, f"⏳ <b>در حال انجام</b>\n{_stats_text(st)}", stop_kb)

    try:
        job.error = await runner.run(job.mode, job.limit, job.stats, job.stop, progress)
    except asyncio.CancelledError:
        job.running = False
        raise
    except Exception:  # noqa: BLE001
        log.exception("promo backfill failed")
        job.error = "خطای غیرمنتظره؛ می‌توانید دوباره ادامه دهید."
    job.running = False
    ctx.repos.logs.add("promo_backfill_finished", ctx.settings.admin_user_id, f"{job.mode} done={job.stats.done} err={job.stats.errors}")
    head = f"❌ {esc(job.error)}" if job.error else ("⏹ متوقف شد؛ می‌توانید ادامه دهید." if job.stop.is_set() else "✅ <b>پایان</b>")
    hint = "\n\n👀 حالا کانال را باز کنید و پست جدیدترین آهنگ را ببینید؛ اگر درست بود «اعمال روی همه» را بزنید." if job.limit == 1 and not job.error and job.stats.done else ""
    await _edit(app.bot, chat_id, message_id, f"{head}\n{_stats_text(job.stats)}{hint}",
                InlineKeyboardMarkup([[_b("🔁 منوی پست‌های قبلی", "b:menu"), _b(T.BTN_MAIN_MENU, "m:main")]]))
