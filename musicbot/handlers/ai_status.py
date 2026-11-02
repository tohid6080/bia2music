"""وضعیت و کنترل هوش مصنوعی: آزمایش اتصال، سقف روزانه، دسته‌بندی دسته‌ای آرشیو (z:)."""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from musicbot.ai import get_ai_status
from musicbot.ai.claude import BATCH_SIZE, AIUnavailable
from musicbot.ai.pricing import DEFAULT_CLAUDE_MODEL, PRICES, estimate_cost
from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.songs.textutils import ascii_digits
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b

log = logging.getLogger(__name__)
JOB_KEY = "ai_job"
PACE = 0.5
MAX_BATCHES = 120                      # سقف یک اجرا (حدود ۳۰۰۰ آهنگ)
EST_IN, EST_OUT = 1500, 3000           # تخمین توکن هر دسته برای نمایش هزینه (تفکر مدل را هم دربر می‌گیرد)
MAX_ERRORS_IN_ROW = 3


def render_ai_status(status) -> str:
    real = "✅ فعال" if status.real_ai_active else "⛔ غیرفعال"
    rec = "✅ فعال" if status.recognizer_active else "⛔ غیرفعال (در آینده با سرویس تخصصی)"
    provider = status.requested_provider if status.requested_provider not in ("", "none") else "تنظیم نشده"
    lines = [
        "🤖 <b>وضعیت هوش مصنوعی</b>\n",
        f"• هوش مصنوعی واقعی: {real}",
        f"• ارائه‌دهنده: <code>{esc(provider)}</code>" + (f" · مدل: <code>{esc(status.model)}</code>" if status.model else ""),
        f"• روش تولید کپشن/هشتگ: {esc(status.content_mode_fa)}",
        f"• شناسایی آهنگ از روی فایل: {rec}",
        f"\nℹ️ {esc(status.reason_fa)}",
    ]
    if not status.real_ai_active:
        lines.append("\nبدون API پولی هم همه بخش‌ها کار می‌کنند. برای فعال‌سازی Claude، در فایل <code>.env</code> بنویسید:\n"
                     "<code>AI_PROVIDER=claude</code>\n<code>ANTHROPIC_API_KEY=کلید_شما</code>\n"
                     "(اختیاری: <code>AI_MODEL=claude-haiku-5-5</code> برای هزینه‌ی خیلی کمتر) و ربات را دوباره اجرا کنید.")
    return "\n".join(lines)


def render_usage(ctx, status) -> str:
    m = ctx.repos.metrics
    t1, t30 = m.totals(1), m.totals(30)
    model = status.model
    cost1 = estimate_cost(model, t1.get("ai_in", 0), t1.get("ai_out", 0)) if model else None
    cost30 = estimate_cost(model, t30.get("ai_in", 0), t30.get("ai_out", 0)) if model else None
    price = PRICES.get(model or "")
    lines = [
        "\n📊 <b>مصرف</b>",
        f"• امروز: {t1.get('ai_calls', 0)} تماس از سقف {ctx.ai_daily_limit()} (فقط برای کپشن) · {t1.get('ai_in', 0) + t1.get('ai_out', 0):,} توکن"
        + (f" · ≈ ${cost1:.4f}" if cost1 is not None else ""),
        f"• ۳۰ روز: {t30.get('ai_calls', 0)} تماس · {t30.get('ai_in', 0) + t30.get('ai_out', 0):,} توکن"
        + (f" · ≈ ${cost30:.3f}" if cost30 is not None else ""),
    ]
    if price:
        lines.append(f"• نرخ مدل: ${price[0]}/${price[1]} به ازای هر میلیون توکن (ورودی/خروجی)")
    else:
        lines.append("• نرخ این مدل در ربات ثبت نیست؛ هزینه را از Console سرویس ببینید.")
    last = getattr(ctx.ai_provider, "last_error", None)
    if last:
        lines.append(f"⚠️ آخرین خطا: {esc(last)}")
    lines.append("\nℹ️ هزینه‌ها تخمینی است؛ مرجع، صورتحساب سرویس است. اگر خطا یا سقف باشد، کپشن خودکار با قالب ساخته می‌شود.")
    return "\n".join(lines)


async def show_ai_status(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    ctx = ctx_of(context)
    status = get_ai_status(ctx.settings)
    text = render_ai_status(status) + (render_usage(ctx, status) if status.real_ai_active else "") + (f"\n\n{note}" if note else "")
    rows = []
    if status.real_ai_active:
        rows.append([_b("🧪 آزمایش اتصال", "z:t"), _b("🏷 دسته‌بندی با AI", "z:c")])
        rows.append([_b(f"📊 سقف روزانه ({ctx.ai_daily_limit()})", "z:l")])
    rows.append([_b(T.BTN_BACK, "m:main")])
    await show(update, text, InlineKeyboardMarkup(rows))


@dataclass
class AIJob:
    batches: int = 0
    songs_seen: int = 0
    songs_updated: int = 0
    fields_filled: int = 0
    unsure: int = 0
    errors: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None
    running: bool = True
    error: Optional[str] = None


def _job_text(job: AIJob, model: Optional[str]) -> str:
    cost = estimate_cost(model, job.tokens_in, job.tokens_out) if model else None
    return (f"🔎 بررسی‌شده: {job.songs_seen} آهنگ ({job.batches} دسته)\n✅ آهنگ تکمیل‌شده: {job.songs_updated} ({job.fields_filled} فیلد)\n"
            f"🤔 نامطمئن (رها شد): {job.unsure}\n⚠️ خطا: {job.errors}\n🧮 توکن: {job.tokens_in + job.tokens_out:,}"
            + (f" · ≈ ${cost:.3f}" if cost is not None else ""))


def _categories(ctx) -> dict:
    c = ctx.repos.categories
    return {"languages": [{"key": i["key"], "name": i["name_fa"]} for i in c.list("languages")],
            "genres": [{"key": i["key"], "name": i["name_fa"]} for i in c.list("genres")],
            "moods": [{"key": i["key"], "name": i["name_fa"]} for i in c.list("moods")]}


async def classify_run(ctx, job: AIJob, on_progress=None, pace: float = 0.0) -> None:
    """دسته‌بندی دسته‌ای: فقط فیلدهای خالی و فقط با اطمینان بالا پر می‌شود؛ بقیه رها (و علامت‌گذاری) می‌شوند."""
    provider = ctx.ai_provider
    cats = _categories(ctx)
    base_in, base_out = getattr(provider, "tokens_in", 0), getattr(provider, "tokens_out", 0)
    errors_in_row = 0
    while not job.stop.is_set() and job.batches < MAX_BATCHES:
        songs = ctx.repos.songs.ai_candidates(BATCH_SIZE)
        if not songs:
            break
        try:
            results = await provider.classify_songs(songs, cats)
            errors_in_row = 0
        except AIUnavailable as exc:
            job.errors += 1
            errors_in_row += 1
            job.error = exc.reason_fa
            if errors_in_row >= MAX_ERRORS_IN_ROW:
                break
            await asyncio.sleep(pace * 4)
            continue
        job.error = None
        job.batches += 1
        for s in songs:
            r = results.get(s["id"])
            job.songs_seen += 1
            if r and r["confident"]:
                n = ctx.repos.songs.apply_ai_guess(s["id"], r["language"], r["genre"], r["mood"])
                if n:
                    job.songs_updated += 1
                    job.fields_filled += n
            else:
                ctx.repos.songs.apply_ai_guess(s["id"], None, None, None)      # فقط علامت «بررسی شد»
                job.unsure += 1
        job.tokens_in = getattr(provider, "tokens_in", 0) - base_in
        job.tokens_out = getattr(provider, "tokens_out", 0) - base_out
        if on_progress:
            await on_progress(job)
        if pace:
            await asyncio.sleep(pace)
    job.tokens_in = getattr(provider, "tokens_in", 0) - base_in
    job.tokens_out = getattr(provider, "tokens_out", 0) - base_out


@admin_only
async def ai_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    action = update.callback_query.data.split(":")[1]
    context.user_data.pop("awaiting", None)
    status = get_ai_status(ctx.settings)
    job: Optional[AIJob] = context.application.bot_data.get(JOB_KEY)
    running = bool(job and job.running)
    back = InlineKeyboardMarkup([[_b(T.BTN_BACK, "m:ai")]])
    if action == "x":
        if running:
            job.stop.set()
        await show_ai_status(update, context, "⏹ در حال توقف..." if running else "")
        return
    if not status.real_ai_active:
        await show(update, "🤖 هوش مصنوعی واقعی فعال نیست.", back)
        return
    if running:
        await show(update, f"⏳ <b>دسته‌بندی در حال اجراست</b>\n{_job_text(job, status.model)}",
                   InlineKeyboardMarkup([[_b("⏹ توقف", "z:x"), _b("🔄 به‌روزرسانی", "z:r")], [_b(T.BTN_BACK, "m:ai")]]))
        return
    if action == "t":
        ok, msg, secs = await ctx.ai_provider.ping()
        ctx.repos.logs.add("ai_test", update.effective_user.id, f"ok={ok}")
        await show_ai_status(update, context, f"{'✅' if ok else '❌'} {esc(msg)} ({secs:.1f} ثانیه)")
    elif action == "l":
        context.user_data["awaiting"] = "ailimit"
        await show(update, "📊 سقف تعداد تماس روزانه برای تولید کپشن را بنویسید (۰ تا ۱۰۰۰۰). با رسیدن به سقف، کپشن‌ها با قالب ساخته می‌شوند.", back)
    elif action in ("c", "r"):
        n = ctx.repos.songs.ai_candidates_count()
        if n == 0:
            await show(update, "✅ آهنگ منتشرشده‌ی بی‌دسته‌ای باقی نمانده که AI بررسی نکرده باشد.\n"
                               "(برای بررسی دوباره‌ی آهنگ‌هایی که قبلاً نامطمئن ماندند، «↺ بررسی مجدد» را بزنید؛ هزینه دارد.)",
                       InlineKeyboardMarkup([[_b("↺ بررسی مجدد همه", "z:rs")], [_b(T.BTN_BACK, "m:ai")]]))
            return
        batches = min(MAX_BATCHES, math.ceil(n / BATCH_SIZE))
        cost = estimate_cost(status.model or "", batches * EST_IN, batches * EST_OUT)
        cost_txt = f"≈ ${cost:.2f}" if cost is not None else "نامشخص (نرخ مدل ثبت نیست)"
        await show(update, f"🏷 <b>دسته‌بندی با AI</b>\n\n{n} آهنگ منتشرشده بی‌زبان/سبک/حال‌وهوا → {batches} دسته ({BATCH_SIZE} آهنگ در هر درخواست)\n"
                           f"💰 هزینه‌ی تقریبی با مدل <code>{esc(status.model or '')}</code>: <b>{cost_txt}</b> (تخمین؛ مرجع صورتحساب سرویس)\n\n"
                           "• فقط فیلدهای <b>خالی</b> پر می‌شود و چیزی بازنویسی نمی‌شود.\n• فقط با اطمینان بالا؛ بقیه رها می‌شود.\n"
                           "• هر زمان می‌توانید توقف کنید.\n• دقت AI کامل نیست؛ بعداً از کارت آهنگ قابل اصلاح است.",
                   InlineKeyboardMarkup([[_b("▶️ شروع (هزینه را پذیرفتم)", "z:go"), _b(T.BTN_CANCEL, "m:ai")]]))
    elif action == "rs":
        ctx.repos.songs.reset_ai_checked()
        await show_ai_status(update, context, "↺ همه‌ی آهنگ‌ها دوباره قابل بررسی شدند.")
    elif action == "go":
        await _start_job(update, context)
    else:
        await show_ai_status(update, context)


async def _start_job(update, context) -> None:
    ctx = ctx_of(context)
    bd = context.application.bot_data
    job = AIJob()
    bd[JOB_KEY] = job
    chat_id = update.effective_chat.id
    msg = await context.bot.send_message(chat_id, "⏳ دسته‌بندی با AI شروع شد...",
                                         reply_markup=InlineKeyboardMarkup([[_b("⏹ توقف", "z:x")]]))
    ctx.repos.logs.add("ai_classify_started", update.effective_user.id)
    job.task = asyncio.create_task(_run(context.application, ctx, job, chat_id, msg.message_id))


async def _edit(bot, chat_id, message_id, text, markup=None) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception:  # noqa: BLE001
        pass


async def _run(app, ctx, job: AIJob, chat_id: int, message_id: int) -> None:
    model = get_ai_status(ctx.settings).model
    stop_kb = InlineKeyboardMarkup([[_b("⏹ توقف", "z:x")]])

    async def progress(j: AIJob) -> None:
        await _edit(app.bot, chat_id, message_id, f"⏳ <b>در حال دسته‌بندی با AI</b>\n{_job_text(j, model)}", stop_kb)

    try:
        await classify_run(ctx, job, progress, PACE)
    except asyncio.CancelledError:
        job.running = False
        raise
    except Exception:  # noqa: BLE001
        log.exception("ai classify failed")
        job.error = "خطای غیرمنتظره"
    job.running = False
    ctx.repos.logs.add("ai_classify_finished", ctx.settings.admin_user_id, f"updated={job.songs_updated} errors={job.errors}")
    left = ctx.repos.songs.ai_candidates_count()
    head = f"❌ {esc(job.error)}" if job.error and job.errors >= MAX_ERRORS_IN_ROW else ("⏹ متوقف شد؛ می‌توانید ادامه دهید." if job.stop.is_set() else "✅ <b>پایان</b>")
    rows = []
    if left:
        rows.append([_b(f"▶️ ادامه ({left} مانده)", "z:c")])
    rows.append([_b("🏷 بدون زبان", "g:l:nolang:0"), _b("🤖 وضعیت AI", "m:ai")])
    await _edit(app.bot, chat_id, message_id, f"{head}\n{_job_text(job, model)}", InlineKeyboardMarkup(rows))


async def receive_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    digits = ascii_digits((update.effective_message.text or "").strip())
    back = InlineKeyboardMarkup([[_b(T.BTN_BACK, "m:ai")]])
    if not digits.isdigit() or int(digits) > 10000:
        await show(update, "❌ عددی بین ۰ تا ۱۰۰۰۰ بنویسید یا برگردید.", back)
        return
    context.user_data.pop("awaiting", None)
    ctx.repos.settings.set("ai_daily_limit", str(int(digits)))
    ctx.repos.logs.add("ai_limit_changed", update.effective_user.id, digits)
    await show_ai_status(update, context, "✅ سقف روزانه ذخیره شد.")
