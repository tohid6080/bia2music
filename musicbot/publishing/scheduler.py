"""زمان‌بند: فقط یادآوری برای مدیر می‌فرستد. این ماژول هرگز چیزی در کانال منتشر نمی‌کند
(به ماژول انتشار دسترسی ندارد)؛ انتشار فقط با تأیید دوباره مدیر انجام می‌شود."""
from __future__ import annotations

import asyncio
import html
import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from musicbot import growth_plan, reports
from musicbot.radar import report as radar_report
from musicbot.publishing.timeutil import format_local, to_iso, utc_now
from musicbot.ui import song_ui as U
from musicbot.ui import texts as T

log = logging.getLogger(__name__)
INTERVAL_SECONDS = 30


def due_keyboard(song_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 پیش‌نمایش و انتشار", callback_data=f"p:pv:{song_id}")],
        [InlineKeyboardButton("⏭ ۱ ساعت بعد", callback_data=f"p:sn:{song_id}"),
         InlineKeyboardButton("❌ لغو زمان‌بندی", callback_data=f"p:qc:{song_id}")],
    ])


async def notify_due(ctx, bot, now=None) -> int:
    """برای هر زمان‌بندی سررسیده یک یادآوری می‌فرستد؛ فقط پس از ارسال موفق علامت می‌زند. تعداد یادآوری‌ها."""
    now = now or utc_now()
    sent = 0
    for item in ctx.repos.queue.due_pending(to_iso(now)):
        song = ctx.repos.songs.get(item["song_id"])
        if not song or song["status"] != "scheduled":
            ctx.repos.queue.cancel_for_song(item["song_id"], restore_song=False)
            continue
        text = (
            "⏰ <b>زمان انتشار برنامه‌ریزی‌شده رسید</b>\n"
            f"🕒 {format_local(item['scheduled_at'], ctx.settings.tz)}\n\n"
            f"{U.song_card_text(song)}\n\n"
            "برای حفظ کنترل شما، انتشار خودکار انجام نمی‌شود. پیش‌نمایش را ببینید و صریحاً تأیید کنید."
        )
        try:
            await bot.send_message(ctx.settings.admin_user_id, text, parse_mode=ParseMode.HTML,
                                   reply_markup=due_keyboard(song["id"]))
        except Exception:  # noqa: BLE001 - در دور بعد دوباره تلاش می‌شود
            log.warning("due notification failed")
            continue
        ctx.repos.queue.mark_due(item["id"])
        ctx.repos.logs.add("schedule_due_notified", None, f"id={song['id']}")
        sent += 1
    return sent


async def snapshot_members_daily(ctx) -> bool:
    """روزی یک‌بار تعداد اعضا را ذخیره می‌کند (فقط‌خواندنی)."""
    if ctx.repos.metrics.has_snapshot():
        return False
    n = await ctx.channel.member_count(ctx.effective_channel_ref())
    if n is None:
        return False
    ctx.repos.metrics.snapshot_members(n)
    return True


async def weekly_report(ctx, bot, now=None) -> bool:
    """شنبه‌ها بعد از ساعت ۹ (به وقت TIMEZONE)، اگر مدیر روشن کرده باشد؛ فقط به چت مدیر."""
    st = ctx.repos.settings
    if st.get("weekly_report", "0") != "1":
        return False
    local = (now or utc_now()).astimezone(ctx.settings.tz)
    key = local.strftime("%Y-%m-%d")
    if local.weekday() != 5 or local.hour < 9 or st.get("last_weekly_report") == key:
        return False
    members = await ctx.channel.member_count(ctx.effective_channel_ref())
    try:
        await bot.send_message(ctx.settings.admin_user_id, reports.weekly(ctx, members), parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001 - دور بعد دوباره
        return False
    st.set("last_weekly_report", key)
    return True


async def weekly_plan(ctx, bot, now=None) -> bool:
    """شنبه‌ها بعد از ساعت ۹ برنامه‌ی پیشنهادی رشد را فقط به چت مدیر می‌فرستد (قابل خاموش‌کردن)."""
    st = ctx.repos.settings
    if st.get("weekly_plan", "1") != "1":
        return False
    local = (now or utc_now()).astimezone(ctx.settings.tz)
    key = growth_plan.week_key(local)
    if local.weekday() != 5 or local.hour < 9 or st.get("last_weekly_plan") == key:
        return False
    members = await ctx.channel.member_count(ctx.effective_channel_ref())
    text = growth_plan.build_plan(ctx, members, local)
    ctx.repos.gcontent.save_plan(key, text)
    try:
        for part in growth_plan.split_message(text):
            await bot.send_message(ctx.settings.admin_user_id, part, parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001 - دور بعد دوباره
        return False
    st.set("last_weekly_plan", key)
    return True


async def notify_milestones(ctx, bot) -> int:
    """وقتی تعداد اعضا به نقطه‌ی عطف می‌رسد فقط «پیام» می‌دهد؛ هیچ انتشار یا تغییر خودکاری انجام نمی‌شود.
    اولین اجرا نقطه‌های قبلاً گذشته را بی‌صدا ثبت می‌کند (پیام تبریک الکی نمی‌رود)."""
    snaps = ctx.repos.metrics.snapshots(1)
    if not snaps:
        return 0
    members = snaps[-1]["members"]
    st = ctx.repos.settings
    ms = ctx.repos.gcontent.milestones()
    reached = {m["members"]: m for m in ms if m["members"] <= members}
    raw = st.get("ms_notified")
    if raw is None:
        st.set("ms_notified", ",".join(str(k) for k in sorted(reached)))
        return 0
    done = {int(x) for x in raw.split(",") if x}
    sent = 0
    for count, m in sorted(reached.items()):
        if count in done:
            continue
        text = (f"🎉 <b>به {count} عضو رسیدید!</b>\n🏁 {html.escape(m['title'])}\n" + (f"💡 {html.escape(m['note'])}\n" if m.get("note") else "")
                + "\n🗓 برنامه‌ی هفتگی را در 📈 رشد و توسعه ببینید.\nℹ️ این فقط یک پیام است؛ هیچ انتشار خودکاری فعال نمی‌شود.")
        try:
            await bot.send_message(ctx.settings.admin_user_id, text, parse_mode=ParseMode.HTML)
        except Exception:  # noqa: BLE001
            continue
        done.add(count)
        st.set("ms_notified", ",".join(str(k) for k in sorted(done)))
        ctx.repos.logs.add("milestone_reached", None, str(count))
        sent += 1
    return sent


async def refresh_radar(ctx) -> int:
    """به‌روزرسانی دوره‌ای منابع رادار که مدیر صریحاً فعال کرده؛ با کش/TTL و جداسازی خطا. چیزی ارسال یا منتشر نمی‌کند."""
    try:
        results = await ctx.radar_service().refresh_all(force=False)
    except Exception:  # noqa: BLE001
        log.warning("radar refresh failed")
        return 0
    return sum(1 for r in results if any(x.ok for x in r.regions))


async def daily_radar_report(ctx, bot, now=None) -> bool:
    """گزارش روزانه‌ی رادار فقط به چت مدیر، در ساعت تنظیم‌شده (پیش‌فرض خاموش). فقط پس از ارسال موفق آهنگ‌ها «گزارش‌شده» علامت می‌خورند."""
    st = ctx.repos.settings
    if st.get("radar_report_on", "0") != "1":
        return False
    now_utc = now or utc_now()
    local = now_utc.astimezone(ctx.settings.tz)
    try:
        hh, mm = (int(x) for x in (st.get("radar_report_time", "09:30")).split(":"))
    except ValueError:
        hh, mm = 9, 30
    key = local.strftime("%Y-%m-%d")
    if (local.hour, local.minute) < (hh, mm) or st.get("last_radar_report") == key:
        return False
    text = radar_report.build_report(ctx, now_utc, mark=False)
    if text is None:
        st.set("last_radar_report", key)                     # چیزی برای گزارش نیست؛ امروز دوباره تلاش نشود
        return False
    try:
        for part in growth_plan.split_message(text):
            await bot.send_message(ctx.settings.admin_user_id, part, parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001 - دور بعد دوباره
        return False
    radar_report.build_report(ctx, now_utc, mark=True)       # حالا علامت‌گذاری «گزارش‌شده»
    st.set("last_radar_report", key)
    return True


async def notify_campaign_endings(ctx, bot, now=None) -> int:
    """وقتی پایان کمپین رسید فقط یادآوری می‌فرستد؛ چیزی منتشر یا حذف نمی‌شود."""
    sent = 0
    for c in ctx.repos.campaigns.due_endings(to_iso(now or utc_now())):
        text = (f"⏰ <b>پایان {'تبلیغ' if c['kind'] == 'ad' else 'همکاری'} «{html.escape(c['title'])}» رسید</b>\n\n"
                "برای ثبت نتیجه (تعداد اعضا) «پایان» را بزنید."
                + ("\nپست تبلیغ را خودتان از کانال حذف کنید (ربات حذف نمی‌کند)." if c["kind"] == "ad" else ""))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ پایان و ثبت نتیجه", callback_data=f"d:fin:{c['id']}")],
                                   [InlineKeyboardButton("⏭ ۱ ساعت بعد", callback_data=f"d:sn:{c['id']}")]])
        try:
            await bot.send_message(ctx.settings.admin_user_id, text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:  # noqa: BLE001
            continue
        ctx.repos.campaigns.mark_reminded(c["id"])
        sent += 1
    return sent


async def run_scheduler(ctx, bot, interval: int = INTERVAL_SECONDS) -> None:
    while True:
        try:
            await snapshot_members_daily(ctx)
            await weekly_report(ctx, bot)
            await notify_campaign_endings(ctx, bot)
            await notify_milestones(ctx, bot)
            await refresh_radar(ctx)
            await daily_radar_report(ctx, bot)
            await weekly_plan(ctx, bot)
            await notify_due(ctx, bot)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("scheduler tick failed")
        await asyncio.sleep(interval)
