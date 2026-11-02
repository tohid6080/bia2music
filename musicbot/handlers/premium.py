"""اشتراک ویژه با Telegram Stars (XTR): تنظیمات مدیر (v:)، پرداخت، بازپرداخت و /terms /paysupport.
پرداخت داخل خود تلگرام است؛ نیازی به درگاه بیرونی یا توکن پرداخت نیست."""
from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, show
from musicbot.publishing.timeutil import format_local
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b

log = logging.getLogger(__name__)
esc = html.escape
CURRENCY = "XTR"
DEFAULT_STARS, DEFAULT_DAYS = 100, 30
BENEFITS = ("📥 دریافت فایل آهنگ‌ها داخل ربات\n⭐ پلی‌لیست‌های ویژه\n🎤 درخواست آهنگ بیشتر (۱۰ در روز)")
TERMS = ("📜 <b>شرایط اشتراک ویژه</b>\n\n• اشتراک ویژه دسترسی زمان‌دار به مزایای ربات است (دریافت فایل، پلی‌لیست‌های ویژه، درخواست بیشتر).\n"
         "• پرداخت با Telegram Stars انجام می‌شود و اشتراک بلافاصله فعال می‌شود.\n• فایل‌ها فقط برای استفاده‌ی شخصی است و قابل بازنشر نیست.\n"
         "• برای مشکل پرداخت یا درخواست بازپرداخت: /paysupport")


def premium_settings(ctx) -> dict:
    st = ctx.repos.settings
    return {
        "enabled": st.get("premium_enabled", "0") == "1",
        "stars": int(st.get("premium_stars", str(DEFAULT_STARS))),
        "days": int(st.get("premium_days", str(DEFAULT_DAYS))),
        "support": st.get("support_text") or "",
    }


def payload_for(uid: int, days: int, stars: int) -> str:
    return f"prem:{uid}:{days}:{stars}"


def parse_payload(payload: str):
    try:
        tag, uid, days, stars = payload.split(":")
        if tag != "prem":
            return None
        return int(uid), int(days), int(stars)
    except (ValueError, AttributeError):
        return None


def is_premium(ctx, uid: int) -> bool:
    from musicbot.auth import is_admin

    return is_admin(ctx.settings, ctx.repos, uid) or ctx.repos.payments.is_premium(uid)


# ---------- مدیر ----------
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    ctx = ctx_of(context)
    s = premium_settings(ctx)
    rev = ctx.repos.payments.revenue()
    text = (f"⭐ <b>اشتراک ویژه</b>\n\nوضعیت: {'✅ فعال (کاربران می‌توانند بخرند)' if s['enabled'] else '⛔ خاموش'}\n"
            f"💰 قیمت: {s['stars']} استارز برای {s['days']} روز\n📞 پشتیبانی: {esc(s['support']) or 'تنظیم نشده'}\n\n"
            f"👤 مشترک فعال: {rev['active']}\n⭐ درآمد کل: {rev['stars']} استارز ({rev['count']} پرداخت) · ۳۰ روز: {rev['stars_30d']}\n\n"
            f"<b>مزایا:</b>\n{BENEFITS}\n\nℹ️ برداشت استارز از طریق خود تلگرام (Fragment) انجام می‌شود."
            + (f"\n\n{note}" if note else ""))
    kb = InlineKeyboardMarkup([
        [_b("⛔ خاموش‌کردن" if s["enabled"] else "✅ روشن‌کردن", "v:t")],
        [_b("💰 قیمت", "v:p"), _b("📅 مدت (روز)", "v:d")],
        [_b("📞 پشتیبانی", "v:s"), _b("📜 پرداخت‌های اخیر", "v:l")],
        [_b(T.BTN_BACK, "m:ads")],
    ])
    await show(update, text, kb)


@admin_only
async def premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    parts = update.callback_query.data.split(":")
    action = parts[1]
    uid = update.effective_user.id
    context.user_data.pop("awaiting", None)
    back = InlineKeyboardMarkup([[_b(T.BTN_BACK, "v:menu")]])
    try:
        if action == "menu":
            await show_menu(update, context)
        elif action == "t":
            if premium_settings(ctx)["enabled"]:
                ctx.repos.settings.set("premium_enabled", "0")
                ctx.repos.logs.add("premium_off", uid)
                await show_menu(update, context, "⛔ خاموش شد.")
            else:
                s = premium_settings(ctx)
                await show(update, f"⭐ <b>روشن‌کردن اشتراک ویژه</b>\n\nقیمت: {s['stars']} استارز برای {s['days']} روز.\n"
                                   "دکمه‌ی خرید برای همه‌ی کاربران ظاهر می‌شود. پیش‌تر قیمت و پشتیبانی را بررسی کنید.\nروشن شود؟",
                           InlineKeyboardMarkup([[_b("✅ بله، روشن شود", "v:ty"), _b(T.BTN_CANCEL, "v:menu")]]))
        elif action == "ty":
            ctx.repos.settings.set("premium_enabled", "1")
            ctx.repos.logs.add("premium_on", uid)
            await show_menu(update, context, "✅ روشن شد.")
        elif action in ("p", "d", "s"):
            context.user_data["awaiting"] = f"prem:{action}"
            prompt = {"p": "💰 قیمت را به استارز و فقط با عدد بنویسید (۱ تا ۱۰۰۰۰):", "d": "📅 مدت اشتراک را به روز بنویسید (۱ تا ۳۶۵):",
                      "s": "📞 متن/آیدی پشتیبانی پرداخت را بنویسید (مثلاً @username)؛ در /paysupport نمایش داده می‌شود:"}[action]
            await show(update, prompt, back)
        elif action == "l":
            pays = ctx.repos.payments.recent(10)
            if not pays:
                await show(update, "هنوز پرداختی ثبت نشده.", back)
                return
            rows = [[_b(f"{'💳' if p['status'] == 'paid' else '↩️'} {p['stars']}⭐ {(p['first_name'] or str(p['telegram_user_id']))[:16]}", f"v:pv:{p['id']}")] for p in pays]
            rows.append([_b(T.BTN_BACK, "v:menu")])
            await show(update, "📜 <b>پرداخت‌های اخیر</b>", InlineKeyboardMarkup(rows))
        elif action == "pv":
            await _payment_panel(update, context, int(parts[2]))
        elif action == "rf":
            p = ctx.repos.payments.get(int(parts[2]))
            if not p or p["status"] != "paid":
                raise ValueError("payment")
            await show(update, f"↩️ <b>بازپرداخت</b> {p['stars']} استارز به کاربر؟\nاشتراک او هم به همان اندازه کم می‌شود. این کار قابل بازگشت نیست.",
                       InlineKeyboardMarkup([[_b("↩️ بله، بازپرداخت", f"v:rfy:{p['id']}"), _b(T.BTN_CANCEL, f"v:pv:{p['id']}")]]))
        elif action == "rfy":
            await _refund(update, context, int(parts[2]))
        else:
            raise ValueError(action)
    except (ValueError, IndexError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def _payment_panel(update, context, pid: int) -> None:
    ctx = ctx_of(context)
    p = ctx.repos.payments.get(pid)
    if not p:
        await show(update, "❌ پرداخت پیدا نشد.", K.back_to_menu())
        return
    who = esc(p["first_name"] or "") + (f" @{esc(p['username'])}" if p["username"] else "")
    text = (f"💳 <b>پرداخت #{p['id']}</b>\n{who}\n🆔 <code>{p['telegram_user_id']}</code>\n⭐ {p['stars']} استارز · {p['days']} روز\n"
            f"📅 {format_local(p['created_at'], ctx.settings.tz)}\nوضعیت: {'✅ پرداخت‌شده' if p['status'] == 'paid' else '↩️ بازپرداخت‌شده'}")
    rows = [[_b("↩️ بازپرداخت", f"v:rf:{pid}")]] if p["status"] == "paid" else []
    rows.append([_b(T.BTN_BACK, "v:l")])
    await show(update, text, InlineKeyboardMarkup(rows))


async def _refund(update, context, pid: int) -> None:
    ctx = ctx_of(context)
    p = ctx.repos.payments.get(pid)
    if not p or p["status"] != "paid":
        await show(update, "⚠️ این پرداخت قابل بازپرداخت نیست.", InlineKeyboardMarkup([[_b(T.BTN_BACK, "v:l")]]))
        return
    try:
        await context.bot.refund_star_payment(user_id=p["telegram_user_id"], telegram_payment_charge_id=p["charge_id"])
    except TelegramError:
        ctx.repos.logs.add("refund_failed", update.effective_user.id, f"id={pid}", level="error")
        await show(update, "❌ تلگرام بازپرداخت را نپذیرفت (ممکن است قبلاً بازپرداخت شده یا مدت مجاز گذشته باشد).",
                   InlineKeyboardMarkup([[_b(T.BTN_BACK, f"v:pv:{pid}")]]))
        return
    ctx.repos.payments.mark_refunded(pid)
    ctx.repos.logs.add("payment_refunded", update.effective_user.id, f"id={pid}")
    await _payment_panel(update, context, pid)


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    ctx = ctx_of(context)
    field = awaiting.split(":")[1]
    raw = (update.effective_message.text or "").strip()
    back = InlineKeyboardMarkup([[_b(T.BTN_BACK, "v:menu")]])
    from musicbot.songs.textutils import ascii_digits

    if field in ("p", "d"):
        digits = ascii_digits(raw)
        lo, hi = (1, 10000) if field == "p" else (1, 365)
        if not digits.isdigit() or not lo <= int(digits) <= hi:
            await show(update, f"❌ عددی بین {lo} تا {hi} بنویسید یا برگردید.", back)
            return
        ctx.repos.settings.set("premium_stars" if field == "p" else "premium_days", str(int(digits)))
    else:
        val = " ".join(raw.split())[:200]     # @آیدی پشتیبانی نباید حذف شود
        if len(val) < 3:
            await show(update, "❌ متن معتبر بنویسید یا برگردید.", back)
            return
        ctx.repos.settings.set("support_text", val)
    context.user_data.pop("awaiting", None)
    ctx.repos.logs.add("premium_settings_changed", update.effective_user.id, field)
    await show_menu(update, context, "✅ ذخیره شد.")


# ---------- پرداخت (کاربر) ----------
async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    q = update.pre_checkout_query
    s = premium_settings(ctx)
    parsed = parse_payload(q.invoice_payload)
    ok = (s["enabled"] and parsed is not None and q.currency == CURRENCY and parsed[0] == q.from_user.id
          and parsed[1] == s["days"] and parsed[2] == s["stars"] and q.total_amount == s["stars"])
    if ok:
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message="این پیشنهاد دیگر معتبر نیست (قیمت یا شرایط تغییر کرده). دوباره از ربات خرید را شروع کنید.")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    msg = update.effective_message
    user = update.effective_user
    sp = msg.successful_payment
    if sp is None or user is None:
        return
    ctx.repos.users.touch(user.id, user.username, user.first_name, user.language_code)
    parsed = parse_payload(sp.invoice_payload)
    days = parsed[1] if parsed and parsed[0] == user.id else premium_settings(ctx)["days"]
    if not parsed or parsed[0] != user.id or sp.currency != CURRENCY:
        ctx.repos.logs.add("payment_unexpected_payload", user.id, f"charge={sp.telegram_payment_charge_id}", level="error")
    until = ctx.repos.payments.record(user.id, sp.total_amount, days, sp.telegram_payment_charge_id, sp.invoice_payload)
    if until is None:        # همان پرداخت دوباره گزارش شده
        return
    ctx.repos.metrics.incr("purchase")
    ctx.repos.logs.add("payment_received", user.id, f"{sp.total_amount} stars")
    await msg.reply_text(f"✅ پرداخت انجام شد. اشتراک ویژه شما تا {format_local(until, ctx.settings.tz)} فعال است. ممنون! ⭐")
    try:
        await context.bot.send_message(ctx.settings.admin_user_id,
                                       f"💰 پرداخت جدید: {sp.total_amount}⭐ از {esc(user.first_name or '')} ({user.id})")
    except Exception:  # noqa: BLE001
        pass


async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from telegram.constants import ParseMode

    await update.effective_message.reply_text(TERMS, parse_mode=ParseMode.HTML)


async def paysupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    s = premium_settings(ctx)["support"]
    await update.effective_message.reply_text("📞 برای مشکل پرداخت یا درخواست بازپرداخت با پشتیبانی تماس بگیرید:\n" + (s or "پیام شما به مدیر ارسال نمی‌شود؛ از طریق کانال با مدیر در تماس باشید."))
