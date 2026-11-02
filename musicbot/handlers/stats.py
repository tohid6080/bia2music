"""آمار و تحلیل، ابزارهای رشد و شمارش واکنش پست‌ها (t:)."""
from __future__ import annotations

import html

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from musicbot import reports
from musicbot.handlers.common import admin_only, ctx_of, show
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b


def _kb(ctx) -> InlineKeyboardMarkup:
    weekly = ctx.repos.settings.get("weekly_report", "0") == "1"
    return InlineKeyboardMarkup([
        [_b("📈 رشد اعضا", "t:g"), _b("🚀 ابزارهای رشد", "t:gr")],
        [_b(f"🗓 گزارش هفتگی: {'✅' if weekly else '⛔'}", "t:w"), _b("🔄 به‌روزرسانی", "t:o")],
        [_b(T.BTN_BACK, "m:main")],
    ])


async def show_overview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    members = await ctx.channel.member_count(ctx.effective_channel_ref())
    if members is not None:
        ctx.repos.metrics.snapshot_members(members)
    await show(update, reports.overview(ctx, members), _kb(ctx))


@admin_only
async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    action = update.callback_query.data.split(":")[1]
    context.user_data.pop("awaiting", None)
    back = InlineKeyboardMarkup([[_b(T.BTN_BACK, "t:o")]])
    if action == "o":
        await show_overview(update, context)
    elif action == "g":
        await show(update, reports.growth_chart(ctx), back)
    elif action == "gr":
        tips = "\n".join(f"• {html.escape(t[2:]) if t[:1] == ' ' else html.escape(t)}" for t in reports.growth_tips(ctx))
        uname = ctx.bot_username
        link = f"\n\n🔗 لینک ربات: https://t.me/{uname}" if uname else ""
        rows = [[_b("📝 متن آماده‌ی پست معرفی ربات", "t:gp")], [_b("🤝 همکاری‌ها", "d:l:collab"), _b("📢 تبلیغ‌ها", "d:l:ad")],
                [_b(T.BTN_BACK, "t:o")]]
        await show(update, f"🚀 <b>ابزارهای رشد</b>\n\n{tips}{link}", InlineKeyboardMarkup(rows))
    elif action == "gp":
        if not ctx.bot_username:
            await show(update, "نام کاربری ربات هنوز مشخص نیست؛ ربات را یک بار دوباره اجرا کنید.", back)
            return
        text = html.escape(reports.promo_post_text(ctx.bot_username))
        await show(update, f"📝 این متن را کپی کنید و در کانال بگذارید و پین کنید (ربات خودکار منتشرش نمی‌کند):\n\n<code>{text}</code>", back)
    elif action == "w":
        new = "0" if ctx.repos.settings.get("weekly_report", "0") == "1" else "1"
        ctx.repos.settings.set("weekly_report", new)
        ctx.repos.logs.add("weekly_report_toggled", update.effective_user.id, new)
        await show_overview(update, context)
    else:
        await show_overview(update, context)


def _same_channel(ref, chat) -> bool:
    if not ref or chat is None:
        return False
    if ref.startswith("@"):
        return (chat.username or "").lower() == ref[1:].lower()
    return str(chat.id) == ref


async def reaction_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """واکنش‌های پست‌های کانال (تلگرام فقط به ربات ادمین می‌دهد). فقط جمع کل ذخیره می‌شود."""
    ctx = ctx_of(context)
    u = update.message_reaction_count
    if u is None or not _same_channel(ctx.effective_channel_ref(), u.chat):
        return
    ctx.repos.metrics.set_reactions(u.message_id, sum(r.total_count for r in u.reactions))
