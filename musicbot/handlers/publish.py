"""پیش‌نمایش، تأیید، انتشار و زمان‌بندی.

تنها مسیر انتشار: p:pv (پیش‌نمایش) ← p:ok (تأیید) ← p:go (تأیید نهایی، تابع `_go`).
تابع `publish_now` فقط در `_go` صدا زده می‌شود (تست ساختاری این را تضمین می‌کند)."""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from musicbot.handlers import captions as captions_h
from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.publishing.captions import ensure_caption, fingerprint, final_caption
from musicbot.publishing.service import PublishError, publish_now, readiness_problems, send_preview
from musicbot.publishing.timeutil import (format_local, parse_user_datetime, quick_time, to_iso, utc_now)
from musicbot.ui import keyboards as K
from musicbot.ui import publish_ui as PU
from musicbot.ui import song_ui as U
from musicbot.ui import texts as T

log = logging.getLogger(__name__)
NOT_FOUND = "❌ این آهنگ پیدا نشد."


def _card_button(sid: int):
    from telegram import InlineKeyboardMarkup

    return InlineKeyboardMarkup([[U._b("🎵 کارت آهنگ", f"g:v:{sid}"), U._b(T.BTN_MAIN_MENU, "m:main")]])


async def _strip_keyboard(update: Update) -> None:
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - پیام قدیمی/تغییرنکرده؛ مهم نیست
        pass


# ---------- منوها ----------
async def show_publish_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    c = ctx.repos.songs.counts_by_status()
    ref = ctx.effective_channel_ref()
    text = (
        "📤 <b>مدیریت انتشار</b>\n\n"
        f"📡 کانال مقصد: {('<code>' + esc(ref) + '</code>') if ref else 'تنظیم نشده'}\n"
        f"✅ آماده انتشار: {c.get('ready', 0)}\n"
        f"📅 زمان‌بندی‌شده: {c.get('scheduled', 0)}\n"
        f"📤 منتشرشده: {c.get('published', 0)}\n\n"
        "🔒 هیچ پستی بدون تأیید صریح شما منتشر نمی‌شود."
    )
    await show(update, text, PU.publish_menu_keyboard())


async def show_captions_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = ("📝 <b>تولید کپشن و هشتگ</b>\n\nآهنگ را از فهرست انتخاب کنید و «📝 کپشن و هشتگ» را بزنید.\n"
            "کپشن‌ها فعلاً با قالب و قوانین ساخته می‌شوند (هوش مصنوعی واقعی نیست) و قابل ویرایش‌اند.")
    await show(update, text, PU.captions_menu_keyboard())


async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    items = ctx.repos.queue.list_active()
    if not items:
        await show(update, "📅 <b>زمان‌بندی انتشار</b>\n\nآهنگ زمان‌بندی‌شده‌ای نیست.\n"
                           "از کارت آهنگ آماده ← «📤 پیش‌نمایش و انتشار» ← «📅 زمان‌بندی».", PU.schedule_list_keyboard([], {}))
        return
    labels = {i["song_id"]: f"{'⏰' if i['status'] == 'due' else '🕒'} {format_local(i['scheduled_at'], ctx.settings.tz)} — "
                            f"{(i['title'] or '؟')[:20]}" for i in items}
    await show(update, f"📅 <b>زمان‌بندی‌شده‌ها</b> ({len(items)})\n⏰ = زمانش رسیده و منتظر تأیید شماست.",
               PU.schedule_list_keyboard(items, labels))


# ---------- مسیر اصلی ----------
@admin_only
async def publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parts = update.callback_query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    context.user_data.pop("awaiting", None)
    try:
        if action == "q":
            await show_queue(update, context)
            return
        sid = int(parts[2])
        if action == "pv":
            await _preview(update, context, sid)
        elif action == "ok":
            await _ask_confirm(update, context, sid, parts[3])
        elif action == "bk":
            await _restore_preview_keyboard(update, context, sid, parts[3])
        elif action == "go":
            await _go(update, context, sid, parts[3])
        elif action == "dr":
            await _to_draft(update, context, sid)
        elif action == "cx":
            await _strip_keyboard(update)
            await show(update, "❎ لغو شد. چیزی منتشر نشد.", _card_button(sid))
        elif action == "sc":
            await _schedule_menu(update, context, sid)
        elif action == "st":
            await _schedule_quick(update, context, sid, parts[3])
        elif action == "sx":
            context.user_data["awaiting"] = f"sched:{sid}"
            await show(update, "🕒 زمان را بفرستید:\n• <code>21:30</code> (امروز یا فردا)\n"
                               "• <code>1405/08/20 21:30</code> (شمسی)\n• <code>2026-11-10 21:30</code> (میلادی)",
                       PU.custom_time_keyboard(sid))
        elif action == "i":
            await _queue_item(update, context, sid)
        elif action == "qc":
            await _cancel_schedule(update, context, sid)
        elif action == "sn":
            await _snooze(update, context, sid)
        else:
            raise ValueError(action)
    except (ValueError, IndexError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def _preview(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(sid)
    if not song:
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    if song["status"] not in ("ready", "scheduled"):
        await show(update, "⚠️ فقط آهنگ «ثبت‌شده در آرشیو» پیش‌نمایش انتشار دارد. ابتدا آن را در آرشیو ثبت کنید.", _card_button(sid))
        return
    ref = ctx.effective_channel_ref()
    if not ref:
        await show(update, T.CHANNEL_NOT_SET, _card_button(sid))
        return
    await ensure_caption(ctx, sid)
    song = ctx.repos.songs.get(sid)
    opts = ctx.post_options()
    problems = readiness_problems(song, opts)
    if problems:
        await show(update, "⚠️ پیش‌نمایش ممکن نیست:\n• " + "\n• ".join(esc(p) for p in problems), PU.caption_panel_keyboard(sid, False))
        return
    extras = ("\n🔗 دکمه‌ی ربات زیر پست: ✅" if opts.button_url else "") + ("\n🤖 خط ربات در انتهای کپشن: ✅" if opts.footer else "")
    await show(update, f"👁 <b>پیش‌نمایش پست</b>\n📡 مقصد: <code>{esc(ref)}</code>{extras}\n\n"
                       "پیام زیر دقیقاً همان چیزی است که منتشر می‌شود. <b>هنوز چیزی منتشر نشده.</b>", _card_button(sid))
    await send_preview(context.bot, update.effective_chat.id, song,
                       PU.preview_keyboard(sid, fingerprint(song, opts), opts.button_url, opts.button_label), opts)


async def _ask_confirm(update, context, sid: int, fp: str) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(sid)
    if not song or fingerprint(song, ctx.post_options()) != fp:
        await _stale(update, sid)
        return
    await update.callback_query.edit_message_reply_markup(reply_markup=PU.confirm_keyboard(sid, fp))


async def _restore_preview_keyboard(update, context, sid: int, fp: str) -> None:
    opts = ctx_of(context).post_options()
    await update.callback_query.edit_message_reply_markup(reply_markup=PU.preview_keyboard(sid, fp, opts.button_url, opts.button_label))


async def _stale(update, sid: int) -> None:
    await _strip_keyboard(update)
    from telegram import InlineKeyboardMarkup

    await show(update, "⚠️ این پیش‌نمایش قدیمی شده است (محتوا تغییر کرده). دوباره پیش‌نمایش بگیرید.",
               InlineKeyboardMarkup([[U._b("👁 پیش‌نمایش جدید", f"p:pv:{sid}")], [U._b(T.BTN_MAIN_MENU, "m:main")]]))


async def _go(update: Update, context: ContextTypes.DEFAULT_TYPE, sid: int, fp: str) -> None:
    """تنها نقطه‌ای که publish_now صدا زده می‌شود: پس از دو تأیید صریح مدیر."""
    ctx = ctx_of(context)
    await _strip_keyboard(update)  # جلوگیری از ضربه دوم
    try:
        result = await publish_now(context.bot, ctx.repos, ctx.effective_channel_ref(), sid, update.effective_user.id, fp,
                                   ctx.post_options())
    except PublishError as exc:
        await show(update, f"❌ {esc(exc.message_fa)}", _card_button(sid))
        return
    await show(update, "✅ <b>پست در کانال منتشر شد.</b>", PU.after_publish_keyboard(result.post_url))


async def _to_draft(update, context, sid: int) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(sid)
    await _strip_keyboard(update)
    if not song or song["status"] not in ("ready", "scheduled"):
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    ctx.repos.queue.cancel_for_song(sid, restore_song=False)
    ctx.repos.songs.update(sid, status="draft")
    ctx.repos.logs.add("song_to_draft", update.effective_user.id, f"id={sid}")
    await show(update, "💾 در پیش‌نویس ذخیره شد. چیزی منتشر نشد.", _card_button(sid))


# ---------- زمان‌بندی ----------
async def _schedule_menu(update, context, sid: int) -> None:
    song = ctx_of(context).repos.songs.get(sid)
    if not song or song["status"] not in ("ready", "scheduled"):
        await show(update, "⚠️ فقط آهنگ ثبت‌شده در آرشیو قابل زمان‌بندی است.", K.back_to_menu())
        return
    await show(update, "📅 <b>زمان‌بندی انتشار</b>\n\nدر زمان مقرر فقط <b>یادآوری</b> می‌گیرید؛ "
                       "انتشار خودکار نیست و باید دوباره تأیید کنید.", PU.schedule_keyboard(sid))


async def _do_schedule(update, context, sid: int, when) -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get(sid)
    ref = ctx.effective_channel_ref()
    if not song or song["status"] not in ("ready", "scheduled"):
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    if not ref:
        await show(update, T.CHANNEL_NOT_SET, _card_button(sid))
        return
    problems = readiness_problems(song, ctx.post_options()) if song.get("caption") else ["کپشن خالی است"]
    if problems:
        await show(update, "⚠️ ابتدا این موارد را کامل کنید:\n• " + "\n• ".join(esc(p) for p in problems),
                   PU.caption_panel_keyboard(sid, False))
        return
    iso = to_iso(when)
    ctx.repos.queue.schedule(sid, ref, iso)
    ctx.repos.logs.add("song_scheduled", update.effective_user.id, f"id={sid} at={iso}")
    await show(update, f"📅 زمان‌بندی شد: <b>{format_local(iso, ctx.settings.tz)}</b>\n"
                       "در آن زمان یادآوری می‌گیرید و با تأیید شما منتشر می‌شود.", _card_button(sid))


async def _schedule_quick(update, context, sid: int, code: str) -> None:
    when = quick_time(code, utc_now(), ctx_of(context).settings.tz)
    await _do_schedule(update, context, sid, when)


async def receive_sched_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    sid = int(awaiting.partition(":")[2])
    try:
        when = parse_user_datetime(update.effective_message.text or "", utc_now(), ctx_of(context).settings.tz)
    except ValueError as exc:
        await show(update, f"❌ {esc(str(exc))}", PU.custom_time_keyboard(sid))
        return
    context.user_data.pop("awaiting", None)
    await _do_schedule(update, context, sid, when)


async def _queue_item(update, context, sid: int) -> None:
    ctx = ctx_of(context)
    item = ctx.repos.queue.active_for_song(sid)
    song = ctx.repos.songs.get(sid)
    if not item or not song:
        await show(update, "این آهنگ زمان‌بندی فعالی ندارد.", _card_button(sid))
        return
    state = "⏰ زمانش رسیده و منتظر تأیید شماست" if item["status"] == "due" else "🕒 منتظر زمان مقرر"
    await show(update, f"📅 <b>زمان‌بندی</b>\n{format_local(item['scheduled_at'], ctx.settings.tz)} — {state}\n\n{U.song_card_text(song)}",
               PU.queue_item_keyboard(sid))


async def _cancel_schedule(update, context, sid: int) -> None:
    ctx = ctx_of(context)
    ctx.repos.queue.cancel_for_song(sid)
    ctx.repos.logs.add("schedule_cancelled", update.effective_user.id, f"id={sid}")
    await show(update, "❎ زمان‌بندی لغو شد؛ آهنگ به «آماده انتشار» برگشت.", _card_button(sid))


async def _snooze(update, context, sid: int) -> None:
    ctx = ctx_of(context)
    when = quick_time("h1", utc_now(), ctx.settings.tz)
    ctx.repos.queue.snooze(sid, to_iso(when))
    await show(update, f"⏭ یادآوری بعدی: {format_local(to_iso(when), ctx.settings.tz)}", _card_button(sid))
