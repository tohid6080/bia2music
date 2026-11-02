from __future__ import annotations

import os
import platform
import shutil
import tempfile
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from musicbot.channel import InvalidChannelRef, normalize_channel_ref
from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T

_ACTION_FA = {
    "bot_started": "راه‌اندازی ربات",
    "admin_start": "ورود مدیر",
    "unauthorized_start": "تلاش کاربر غیرمجاز",
    "unauthorized_access": "دسترسی غیرمجاز",
    "channel_checked": "بررسی اتصال کانال",
    "channel_changed": "تغییر کانال مقصد",
    "error": "خطای سیستمی",
    "user_features_on": "روشن‌شدن امکانات کاربران",
    "user_features_off": "خاموش‌شدن امکانات کاربران",
    "song_published": "انتشار آهنگ",
    "song_scheduled": "زمان‌بندی آهنگ",
}


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    ref = ctx.effective_channel_ref()
    channel_line = f"<code>{esc(ref)}</code>" if ref else "تنظیم نشده"
    text = (
        f"{T.SETTINGS_TITLE}\n\n"
        f"📡 کانال مقصد: {channel_line}\n"
        f"🕒 منطقه زمانی: <code>{esc(ctx.settings.timezone)}</code>\n"
        f"📝 سطح گزارش: <code>{esc(ctx.settings.log_level)}</code>"
    )
    st = ctx.repos.settings
    await show(update, text, K.settings_menu(st.user_features_enabled(), st.get("promo_button", "1") == "1", st.get("promo_footer", "0") == "1"))


def _status_lines(status) -> str:
    yes, no = "✅", "❌"
    lines = []
    if status.title:
        lines.append(f"📣 عنوان: {esc(status.title)}")
    if status.username:
        lines.append(f"🔗 @{esc(status.username)}")
    if status.member_count is not None:
        lines.append(f"👥 تعداد اعضا: {status.member_count}")
    lines.append(f"{yes if status.bot_is_admin else no} ربات ادمین کانال است")
    lines.append(f"{yes if status.can_post else no} ربات اجازه ارسال پست دارد")
    if status.error_fa:
        lines.append(f"⚠️ {esc(status.error_fa)}")
    if not (status.bot_is_admin and status.can_post):
        lines.append("\nℹ️ ربات را در کانال ادمین کنید و دسترسی «Post messages» بدهید (راهنما در README).")
    return "\n".join(lines)


@admin_only
async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    action = update.callback_query.data.split(":", 1)[1]
    user_id = update.effective_user.id

    if action == "cancel":
        context.user_data.pop("awaiting", None)
        context.user_data.pop("pending_channel", None)
        await show(update, T.CANCELLED + "\n\n" + T.SETTINGS_TITLE, K.settings_menu())

    elif action == "channel":
        ref = ctx.effective_channel_ref()
        if not ref:
            await show(update, T.CHANNEL_NOT_SET, K.back_to_settings())
            return
        await show(update, "⏳ در حال بررسی اتصال به کانال...")
        status = await ctx.channel.check(ref)
        ctx.repos.channel.mark_checked()
        ctx.repos.logs.add("channel_checked", user_id, f"ok={status.ok} admin={status.bot_is_admin} post={status.can_post}")
        if status.ok:
            text = f"📡 <b>وضعیت کانال</b>\n<code>{esc(ref)}</code>\n\n{_status_lines(status)}"
        else:
            text = f"📡 <b>وضعیت کانال</b>\n<code>{esc(ref)}</code>\n\n❌ {esc(status.error_fa or '')}"
        await show(update, text, K.back_to_settings())

    elif action == "channel_change":
        context.user_data["awaiting"] = "channel"
        await show(update, T.CHANNEL_ASK, K.cancel_to_settings())

    elif action == "users":
        await show(update, "👥 <b>روشن کردن امکانات کاربران</b>\n\nهمه‌ی اعضای کانال می‌توانند با ربات چت کنند: جست‌وجو، پیشنهاد، پلی‌لیست، "
                           "پسند و درخواست آهنگ (فقط آهنگ‌های منتشرشده‌ی کانال دیده می‌شود).\nعلایق فقط با رضایت خودشان ذخیره می‌شود.\n\n"
                           "روشن شود؟", K.confirm_users_on())
    elif action in ("users_yes", "users_off"):
        enabled = action == "users_yes"
        ctx.repos.settings.set_user_features(enabled)
        ctx.repos.logs.add("user_features_on" if enabled else "user_features_off", user_id)
        await show_settings(update, context)
    elif action == "backup":
        await _backup(update, context, ctx, user_id)
    elif action == "health":
        await _health(update, context, ctx)
    elif action in ("promo_btn", "promo_ft"):
        key = "promo_button" if action == "promo_btn" else "promo_footer"
        default = "1" if key == "promo_button" else "0"
        new = "0" if ctx.repos.settings.get(key, default) == "1" else "1"
        ctx.repos.settings.set(key, new)
        ctx.repos.logs.add("promo_toggled", user_id, f"{key}={new}")
        await show_settings(update, context)
    elif action == "logs":
        await _show_logs(update, ctx)


async def _show_logs(update: Update, ctx) -> None:
    rows = ctx.repos.logs.recent(10)
    if not rows:
        await show(update, "📋 هنوز فعالیتی ثبت نشده است.", K.back_to_settings())
        return
    lines = ["📋 <b>۱۰ فعالیت اخیر</b>\n"]
    for r in rows:
        try:
            dt = datetime.strptime(r["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            when = dt.astimezone(ctx.settings.tz).strftime("%m/%d %H:%M")
        except ValueError:
            when = r["created_at"]
        label = _ACTION_FA.get(r["action"], r["action"])
        details = f" — {esc(r['details'][:40])}" if r.get("details") else ""
        lines.append(f"• {when} | {esc(label)}{details}")
    await show(update, "\n".join(lines), K.back_to_settings())


async def receive_channel_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    raw = update.effective_message.text or ""
    try:
        ref = normalize_channel_ref(raw)
    except InvalidChannelRef:
        await show(update, T.CHANNEL_INVALID, K.cancel_to_settings())
        return
    status = await ctx.channel.check(ref)
    if not status.ok:
        await show(update, f"❌ {esc(status.error_fa or '')}\n\nدوباره بفرستید یا لغو کنید.", K.cancel_to_settings())
        return
    context.user_data["pending_channel"] = (ref, status.title)
    context.user_data.pop("awaiting", None)
    text = f"❓ کانال مقصد به این مورد تغییر کند؟\n\n<code>{esc(ref)}</code>\n\n{_status_lines(status)}"
    await show(update, text, K.confirm_channel())


@admin_only
async def channel_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    pending = context.user_data.pop("pending_channel", None)
    if not pending:
        await show(update, "⌛ این درخواست منقضی شده است. دوباره تلاش کنید.", K.back_to_settings())
        return
    ref, title = pending
    ctx.repos.channel.set_active(ref, title)
    ctx.repos.logs.add("channel_changed", update.effective_user.id, ref)
    await show(update, f"{T.CHANNEL_SAVED}\n<code>{esc(ref)}</code>", K.back_to_settings())


async def _backup(update, context, ctx, user_id: int) -> None:
    """نسخه‌ی پشتیبان دیتابیس را فقط به چت خود مدیر می‌فرستد (توکن در دیتابیس نیست)."""
    tmp = tempfile.mkdtemp(prefix="musicbot-backup-")
    try:
        name = f"musicbot-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M}.sqlite3"
        path = os.path.join(tmp, name)
        ctx.repos.db.backup(path)
        with open(path, "rb") as fh:
            await context.bot.send_document(chat_id=ctx.settings.admin_user_id, document=fh, filename=name,
                                            caption="💾 پشتیبان دیتابیس Bia2Music. این فایل را جایی امن نگه دارید (شامل شناسه‌ی کاربران است).")
        ctx.repos.logs.add("backup_sent", user_id)
        await show(update, "✅ فایل پشتیبان برای شما ارسال شد.\n\nبرای بازیابی: ربات را متوقف کنید، فایل را به‌جای "
                           "<code>data/musicbot.sqlite3</code> بگذارید و دوباره اجرا کنید.", K.back_to_settings())
    except Exception:  # noqa: BLE001
        ctx.repos.logs.add("backup_failed", user_id, level="error")
        await show(update, "❌ ساخت یا ارسال پشتیبان ناموفق بود.", K.back_to_settings())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _health(update, context, ctx) -> None:
    from musicbot import __version__
    from musicbot.publishing.timeutil import utc_now

    bd = context.application.bot_data
    started = bd.get("started_at")
    uptime = "—"
    if started:
        secs = int((utc_now() - started).total_seconds())
        uptime = f"{secs // 3600} ساعت و {secs % 3600 // 60} دقیقه"
    task = bd.get("scheduler_task")
    sched = "✅ فعال" if task and not task.done() else "❌ متوقف"
    try:
        size = os.path.getsize(ctx.settings.database_path) / 1024 / 1024 if str(ctx.settings.database_path) != ":memory:" else 0
    except OSError:
        size = 0
    errors = [l for l in ctx.repos.logs.recent(50) if l["level"] == "error"][:3]
    job = bd.get("import_job")
    lines = [
        "🩺 <b>وضعیت سیستم</b>\n",
        f"نسخه: {__version__} · Python {platform.python_version()}",
        f"⏱ مدت اجرا: {uptime}",
        f"🗓 زمان‌بند: {sched}",
        f"💾 دیتابیس: {size:.2f} MB · آهنگ‌ها {ctx.repos.songs.count()} · کاربران {ctx.repos.users.count()}",
        f"📡 کانال: {esc(ctx.effective_channel_ref() or 'تنظیم نشده')}",
        f"📥 درون‌ریزی: {'در حال اجرا' if job and job.running else 'بیکار'}",
        f"🤖 هوش مصنوعی واقعی: {'فعال' if ctx.ai_provider.is_real_ai else 'غیرفعال'}",
    ]
    if errors:
        lines.append("\n⚠️ آخرین خطاها:")
        lines += [f"• {esc(e['created_at'][:16].replace('T', ' '))} — {esc(e['action'])} {esc(e['details'] or '')}" for e in errors]
    await show(update, "\n".join(lines), K.back_to_settings())
