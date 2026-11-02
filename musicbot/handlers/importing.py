"""درون‌ریزی آهنگ‌های قدیمی کانال (i:). اجرا در پس‌زمینه، قابل توقف و ادامه."""
from __future__ import annotations

import asyncio
import logging
import math

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.importer import ChannelImporter, ImportJob, ImportStats, parse_message_number
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b

log = logging.getLogger(__name__)
JOB_KEY = "import_job"
TEST_COUNT = 20
SECONDS_PER_ID = 1.2  # فوروارد + حذف + مکث
PACE = 1.0            # مکث بین پست‌ها (محدودیت نرخ تلگرام)


def _job(app_or_ctx_bot_data) -> ImportJob | None:
    return app_or_ctx_bot_data.get(JOB_KEY)


def _stats_text(st: ImportStats) -> str:
    return (f"🔎 بررسی‌شده: {st.scanned} (تا پست {st.last_id})\n✅ جدید: {st.imported}\n🔄 به‌روزشده: {st.updated}\n"
            f"♻️ تکراری: {st.duplicates}\n🗑 پست پاک‌شده/خالی: {st.missing}\n📄 غیرصوتی: {st.other}\n⚠️ خطا: {st.errors}")


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    ctx = ctx_of(context)
    st = ctx.repos.settings
    job = _job(context.application.bot_data)
    ref = ctx.effective_channel_ref()
    last = st.get("import_last_id")
    nxt = st.get("import_next_id", "1")
    published = ctx.repos.songs.count("published")
    lines = [
        "📥 <b>درون‌ریزی آهنگ‌های کانال</b>",
        f"📡 کانال: {('<code>' + esc(ref) + '</code>') if ref else 'تنظیم نشده'}",
        f"🔢 شماره‌ی آخرین پست: {esc(last) if last else 'تنظیم نشده'}",
        f"▶️ ادامه از پست: {esc(nxt)}",
        f"📚 آهنگ‌های منتشرشده‌ی ربات: {published}",
    ]
    if job and job.running:
        lines.append(f"\n⏳ <b>در حال اجرا</b> ({'آزمایشی' if job.mode == 'test' else 'کامل'})\n{_stats_text(job.stats)}")
        rows = [[_b("⏹ توقف", "i:x"), _b("🔄 به‌روزرسانی", "i:m")], [_b(T.BTN_BACK, "m:archive")]]
    else:
        lines.append("\nربات هر پست را به چت خصوصی شما فوروارد می‌کند، اطلاعات آهنگ را می‌خواند و فوراً پاکش می‌کند. "
                     "چیزی در کانال تغییر نمی‌کند.")
        rows = [
            [_b(f"🧪 آزمایش {TEST_COUNT} پست آخر", "i:t")],
            [_b("▶️ درون‌ریزی کامل (ادامه)", "i:s")],
            [_b("🔢 تنظیم شماره‌ی آخرین پست", "i:id"), _b("↺ شروع از پست ۱", "i:rs")],
            [_b(T.BTN_BACK, "m:archive")],
        ]
    if note:
        lines.append(f"\n{note}")
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))


@admin_only
async def import_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    action = update.callback_query.data.split(":")[1]
    if action != "id":
        context.user_data.pop("awaiting", None)
    job = _job(context.application.bot_data)
    running = bool(job and job.running)
    if action == "menu" or action == "m":
        await show_menu(update, context)
    elif action == "x":
        if running:
            job.stop.set()
            await show_menu(update, context, "⏹ در حال توقف... (چند ثانیه‌ی دیگر)")
        else:
            await show_menu(update, context)
    elif running:
        await show_menu(update, context, "⏳ یک درون‌ریزی در حال اجراست.")
    elif action == "id":
        context.user_data["awaiting"] = "import_last"
        await show(update, "🔢 لینک <b>آخرین پست</b> کانال را بفرستید (روی پست بزنید ← Copy Link)، یا فقط شماره‌ی آن را.\n"
                           "مثال: <code>https://t.me/bia2music1395/2450</code>",
                   InlineKeyboardMarkup([[_b(T.BTN_CANCEL, "i:menu")]]))
    elif action == "rs":
        ctx.repos.settings.set("import_next_id", "1")
        await show_menu(update, context, "↺ از پست ۱ شروع می‌شود.")
    elif action in ("t", "s"):
        await _begin(update, context, action)
    elif action == "go":
        await _start_job(update, context, "full")
    else:
        await show_menu(update, context)


async def _begin(update, context, action: str) -> None:
    ctx = ctx_of(context)
    ref = ctx.effective_channel_ref()
    if not ref:
        await show(update, T.CHANNEL_NOT_SET, InlineKeyboardMarkup([[_b(T.BTN_BACK, "i:menu")]]))
        return
    if not ctx.repos.settings.get("import_last_id"):
        context.user_data["awaiting"] = "import_last"
        context.user_data["import_after"] = action
        await show(update, "🔢 اول شماره‌ی <b>آخرین پست</b> کانال را لازم دارم. لینک آخرین پست را بفرستید "
                           "(روی پست بزنید ← Copy Link):", InlineKeyboardMarkup([[_b(T.BTN_CANCEL, "i:menu")]]))
        return
    await _after_id(update, context, action)


async def _after_id(update, context, action: str) -> None:
    ctx = ctx_of(context)
    ref = ctx.effective_channel_ref()
    status = await ctx.channel.check(ref)
    if not status.ok or not status.bot_is_admin:
        await show(update, "❌ ربات باید در کانال ادمین باشد (⚙️ تنظیمات ← 📡 وضعیت اتصال را ببینید)."
                   + (f"\n{esc(status.error_fa)}" if status.error_fa else ""), InlineKeyboardMarkup([[_b(T.BTN_BACK, "i:menu")]]))
        return
    if action == "t":
        await _start_job(update, context, "test")
        return
    last = int(ctx.repos.settings.get("import_last_id"))
    nxt = int(ctx.repos.settings.get("import_next_id", "1"))
    if nxt > last:
        await show_menu(update, context, "✅ همه‌ی پست‌ها تا آخرین شماره بررسی شده‌اند. برای شروع دوباره «↺ شروع از پست ۱» را بزنید.")
        return
    minutes = math.ceil((last - nxt + 1) * SECONDS_PER_ID / 60)
    await show(update, f"▶️ <b>درون‌ریزی کامل</b>\nپست {nxt} تا {last} ({last - nxt + 1} پست)\n⏱ حدود {minutes} دقیقه\n\n"
                       "• در این مدت ربات (Termux) باید روشن بماند.\n• پیام‌های موقت در چت شما ظاهر و پاک می‌شوند.\n"
                       "• هر زمان می‌توانید توقف و بعداً ادامه دهید.",
               InlineKeyboardMarkup([[_b("▶️ شروع", "i:go"), _b(T.BTN_CANCEL, "i:menu")]]))


async def receive_last_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    n = parse_message_number(update.effective_message.text or "")
    if n is None:
        await show(update, "❌ لینک یا شماره‌ی معتبر نیست. دوباره بفرستید یا لغو کنید.", InlineKeyboardMarkup([[_b(T.BTN_CANCEL, "i:menu")]]))
        return
    context.user_data.pop("awaiting", None)
    ctx.repos.settings.set("import_last_id", str(n))
    after = context.user_data.pop("import_after", None)
    if after:
        await _after_id(update, context, after)
    else:
        await show_menu(update, context, f"✅ شماره‌ی آخرین پست: {n}")


async def _start_job(update, context, mode: str) -> None:
    ctx = ctx_of(context)
    bot_data = context.application.bot_data
    if (_job(bot_data) and _job(bot_data).running):
        await show_menu(update, context, "⏳ یک درون‌ریزی در حال اجراست.")
        return
    last = int(ctx.repos.settings.get("import_last_id"))
    if mode == "test":
        start = max(1, last - TEST_COUNT + 1)
    else:
        start = int(ctx.repos.settings.get("import_next_id", "1"))
    job = ImportJob(mode=mode, start=start, end=last)
    bot_data[JOB_KEY] = job
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id, f"⏳ درون‌ریزی شروع شد (پست {start} تا {last})...",
                                         reply_markup=InlineKeyboardMarkup([[_b("⏹ توقف", "i:x")]]))
    ctx.repos.logs.add("import_started", update.effective_user.id, f"{mode} {start}-{last}")
    job.task = asyncio.create_task(_run(context.application, ctx, job, chat_id, msg.message_id))


async def _edit(bot, chat_id: int, message_id: int, text: str, markup=None) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception:  # noqa: BLE001 - «تغییری نکرده» و مشابه
        pass


async def _run(app, ctx, job: ImportJob, chat_id: int, message_id: int, pace: float | None = None) -> None:
    bot = app.bot
    pace = PACE if pace is None else pace
    ref = ctx.effective_channel_ref()
    importer = ChannelImporter(bot, ctx.repos, ref, ctx.settings.admin_user_id, pace=pace)
    stop_kb = InlineKeyboardMarkup([[_b("⏹ توقف", "i:x")]])

    async def progress(st: ImportStats) -> None:
        if job.mode == "full":
            ctx.repos.settings.set("import_next_id", str(st.last_id + 1))
        done = st.last_id - job.start + 1
        total = job.end - job.start + 1
        await _edit(bot, chat_id, message_id, f"⏳ <b>در حال درون‌ریزی</b> ({done}/{total})\n{_stats_text(st)}", stop_kb)

    error = None
    try:
        error = await importer.run(job.start, job.end, job.stats, job.stop, progress)
    except asyncio.CancelledError:
        job.running = False
        if job.mode == "full" and job.stats.last_id:
            ctx.repos.settings.set("import_next_id", str(job.stats.last_id + 1))
        raise
    except Exception:  # noqa: BLE001
        log.exception("import failed")
        error = "خطای غیرمنتظره رخ داد. می‌توانید دوباره ادامه دهید."
    job.running = False
    job.error = error
    st = job.stats
    if job.mode == "full" and st.last_id:
        ctx.repos.settings.set("import_next_id", str(st.last_id + 1))
    ctx.repos.logs.add("import_finished", ctx.settings.admin_user_id,
                       f"imported={st.imported} dup={st.duplicates} err={st.errors}")
    unclassified = ctx.repos.songs.count("nolang")
    head = f"❌ {esc(error)}" if error else ("⏹ متوقف شد؛ می‌توانید ادامه دهید." if job.stop.is_set() else "✅ <b>پایان</b>")
    hint = "\n\nℹ️ اگر آهنگ‌ها وارد شدند، «درون‌ریزی کامل» را بزنید." if job.mode == "test" and not error and st.imported else ""
    if not error and st.scanned >= 10 and st.imported + st.duplicates + st.other + st.updated == 0:
        hint = "\n\n⚠️ هیچ پستی خوانده نشد. شماره‌ی آخرین پست یا کانال مقصد را بررسی کنید (⚙️ تنظیمات)."
    rows = []
    if unclassified:
        rows.append([_b(f"🏷 دسته‌بندی ({unclassified} بدون زبان)", "g:l:nolang:0")])
    rows.append([_b("📥 منوی درون‌ریزی", "i:menu"), _b(T.BTN_MAIN_MENU, "m:main")])
    await _edit(bot, chat_id, message_id, f"{head}\n{_stats_text(st)}{hint}", InlineKeyboardMarkup(rows))
