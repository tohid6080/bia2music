"""تبلیغات (پست تبلیغی با تأیید) و همکاری با کانال‌ها (d:).

مسیر انتشار پست تبلیغی مثل آهنگ: پیش‌نمایش ← تأیید ← تأیید نهایی. `publish_ad_now` فقط در `_go` صدا زده می‌شود."""
from __future__ import annotations

import html
import re
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, show
from musicbot.publishing.service import (MAX_AD_TEXT, PublishError, ad_fingerprint, ad_problems, publish_ad_now,
                                         send_ad_preview)
from musicbot.publishing.timeutil import format_local, from_iso, parse_user_datetime, to_iso, utc_now
from musicbot.songs.textutils import ascii_digits
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b

esc = html.escape
KIND_FA = {"ad": "تبلیغ", "collab": "همکاری"}
KIND_ICON = {"ad": "📢", "collab": "🤝"}
ST_FA = {"draft": "پیش‌نویس", "publishing": "در حال انتشار", "active": "فعال", "done": "تمام‌شده", "cancelled": "لغوشده"}
ST_ICON = {"draft": "📝", "publishing": "⏳", "active": "🟢", "done": "✅", "cancelled": "🚫"}
FIELD_PROMPT = {
    "t": "✏️ عنوان/نام شریک را بنویسید:",
    "k": "🔗 لینک کانال/شریک را بنویسید (برای حذف: -):",
    "o": "📝 یادداشت را بنویسید (برای حذف: -):",
    "c": "💰 مبلغ را فقط با عدد بنویسید (مثلاً 500000؛ برای حذف: -):",
    "p": f"💬 متن پست تبلیغی را بنویسید (حداکثر {MAX_AD_TEXT} حرف):",
    "b": "🔘 دکمه‌ی زیر پست را به شکل «متن | لینک» بنویسید. مثال:\nعضویت در کانال | https://t.me/example\n(برای حذف: -)",
    "s": "📅 زمان شروع را بنویسید (مثل 21:30 یا 1405/08/20 21:30؛ برای حذف: -):",
    "n": "🏁 زمان پایان را بنویسید (مثل 21:30 یا 1405/08/20 21:30؛ برای حذف: -). در آن زمان یادآوری می‌گیرید:",
}
NOT_FOUND = "❌ پیدا نشد."


def _back(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_BACK, target)]])


async def show_hub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    r = ctx.repos
    inc = r.campaigns.income()
    rev = r.payments.revenue()
    active = len([c for k in ("ad", "collab") for c in r.campaigns.list(k, 100) if c["status"] == "active"])
    prem = "✅ فعال" if r.settings.get("premium_enabled", "0") == "1" else "⛔ خاموش"
    text = (f"📢 <b>تبلیغات و درآمدزایی</b>\n\n🟢 کمپین فعال: {active}\n💰 درآمد تبلیغ‌ها: {inc['total']:,} (۳۰ روز: {inc['last_30d']:,})\n"
            f"⭐ اشتراک ویژه: {prem} · مشترک فعال {rev['active']} · درآمد {rev['stars']} استارز")
    kb = InlineKeyboardMarkup([
        [_b("📢 تبلیغ‌ها", "d:l:ad"), _b("🤝 همکاری با کانال‌ها", "d:l:collab")],
        [_b("⭐ اشتراک ویژه", "v:menu"), _b("💰 گزارش درآمد", "d:inc")],
        [_b(T.BTN_BACK, "m:main")],
    ])
    await show(update, text, kb)


def _live_gain(c: dict, live) -> str:
    if c["members_start"] is None:
        return ""
    end = c["members_end"] if c["members_end"] is not None else live
    if end is None:
        return f"👥 اعضا هنگام شروع: {c['members_start']}"
    label = "نتیجه" if c["members_end"] is not None else "تا اکنون"
    return f"👥 اعضا: {c['members_start']} ← {end}  ({label}: {end - c['members_start']:+d})"


async def _card(update, context, cid: int, note: str = "") -> None:
    ctx = ctx_of(context)
    c = ctx.repos.campaigns.get(cid)
    if not c:
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    tz = ctx.settings.tz
    live = await ctx.channel.member_count(ctx.effective_channel_ref()) if c["status"] == "active" else None
    lines = [f"{KIND_ICON[c['kind']]} <b>{esc(c['title'])}</b>", f"وضعیت: {ST_ICON[c['status']]} {ST_FA[c['status']]}"]
    if c["partner_link"]:
        lines.append(f"🔗 {esc(c['partner_link'])}")
    if c["price"] is not None:
        lines.append(f"💰 مبلغ: {c['price']:,}")
    if c["starts_at"]:
        lines.append(f"📅 شروع: {format_local(c['starts_at'], tz)}")
    if c["ends_at"]:
        lines.append(f"🏁 پایان: {format_local(c['ends_at'], tz)}")
    gain = _live_gain(c, live)
    if gain:
        lines.append(gain)
    if c["kind"] == "ad":
        lines.append("💬 متن: " + (esc(c["post_text"][:200]) + ("…" if len(c["post_text"]) > 200 else "") if c["post_text"] else "—"))
        if c["button_label"]:
            lines.append(f"🔘 دکمه: {esc(c['button_label'])} ← {esc(c['button_url'])}")
    if c["notes"]:
        lines.append(f"📝 {esc(c['notes'])}")
    if note:
        lines.append(f"\n{note}")
    i = c["id"]
    rows = []
    if c["status"] == "draft":
        rows.append([_b("✏️ عنوان", f"d:e:{i}:t"), _b("🔗 لینک", f"d:e:{i}:k")])
        if c["kind"] == "ad":
            rows.append([_b("💬 متن پست", f"d:e:{i}:p"), _b("🔘 دکمه", f"d:e:{i}:b")])
        rows.append([_b("💰 مبلغ", f"d:e:{i}:c"), _b("📝 یادداشت", f"d:e:{i}:o")])
        rows.append([_b("📅 شروع", f"d:e:{i}:s"), _b("🏁 پایان", f"d:e:{i}:n")])
        rows.append([_b("👁 پیش‌نمایش و انتشار", f"d:pv:{i}")] if c["kind"] == "ad" else [_b("▶️ شروع همکاری (ثبت اعضا)", f"d:st:{i}")])
    elif c["status"] == "active":
        rows.append([_b("🏁 تنظیم زمان پایان", f"d:e:{i}:n"), _b("💰 مبلغ", f"d:e:{i}:c")])
        rows.append([_b("✅ پایان و ثبت نتیجه", f"d:fin:{i}")])
    if c["status"] in ("draft", "active"):
        rows.append([_b("🚫 لغو", f"d:can:{i}")])
    if c["status"] in ("draft", "done", "cancelled"):
        rows.append([_b("🗑 حذف", f"d:del:{i}")])
    rows.append([_b(T.BTN_BACK, f"d:l:{c['kind']}"), _b(T.BTN_MAIN_MENU, "m:main")])
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _list(update, context, kind: str) -> None:
    ctx = ctx_of(context)
    items = ctx.repos.campaigns.list(kind)
    rows = [[_b(f"{ST_ICON[c['status']]} {c['title'][:30]}", f"d:v:{c['id']}")] for c in items]
    rows.append([_b("➕ جدید", f"d:n:{kind}")])
    rows.append([_b(T.BTN_BACK, "m:ads")])
    hint = ("پست تبلیغی را بسازید، پیش‌نمایش ببینید و با تأیید خودتان منتشر کنید." if kind == "ad" else
            "قرارداد تبادل/معرفی با کانال‌های دیگر را ثبت کنید؛ ربات اعضا را قبل و بعد می‌سنجد.")
    await show(update, f"{KIND_ICON[kind]} <b>{'تبلیغ‌ها' if kind == 'ad' else 'همکاری‌ها'}</b>\n{hint}", InlineKeyboardMarkup(rows))


# ---------- مسیر انتشار تبلیغ ----------
def _preview_kb(c: dict, fp: str) -> InlineKeyboardMarkup:
    i = c["id"]
    rows = [[_b("✅ تأیید و انتشار", f"d:ok:{i}:{fp}")], [_b("✏️ ویرایش", f"d:v:{i}"), _b("❌ لغو", f"d:cx:{i}")]]
    if c["button_label"] and c["button_url"]:
        rows.append([InlineKeyboardButton(c["button_label"], url=c["button_url"])])   # همان دکمه‌ی پست
    return InlineKeyboardMarkup(rows)


async def _preview(update, context, cid: int) -> None:
    ctx = ctx_of(context)
    c = ctx.repos.campaigns.get(cid)
    if not c or c["kind"] != "ad":
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    if c["status"] != "draft":
        await show(update, "⚠️ فقط تبلیغ در حالت «پیش‌نویس» قابل انتشار است.", _back(f"d:v:{cid}"))
        return
    ref = ctx.effective_channel_ref()
    if not ref:
        await show(update, T.CHANNEL_NOT_SET, _back(f"d:v:{cid}"))
        return
    problems = ad_problems(c)
    if problems:
        await show(update, "⚠️ پیش‌نمایش ممکن نیست:\n• " + "\n• ".join(esc(p) for p in problems), _back(f"d:v:{cid}"))
        return
    await show(update, f"👁 <b>پیش‌نمایش تبلیغ</b>\n📡 مقصد: <code>{esc(ref)}</code>\n\n"
                       "پیام زیر دقیقاً همان چیزی است که منتشر می‌شود. <b>هنوز چیزی منتشر نشده.</b>", _back(f"d:v:{cid}"))
    await send_ad_preview(context.bot, update.effective_chat.id, c, _preview_kb(c, ad_fingerprint(c)))


async def _go(update: Update, context: ContextTypes.DEFAULT_TYPE, cid: int, fp: str) -> None:
    """تنها نقطه‌ای که publish_ad_now صدا زده می‌شود: پس از دو تأیید صریح مدیر."""
    ctx = ctx_of(context)
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    try:
        res = await publish_ad_now(context.bot, ctx.repos, ctx.effective_channel_ref(), cid, update.effective_user.id, fp)
    except PublishError as exc:
        await show(update, f"❌ {esc(exc.message_fa)}", _back(f"d:v:{cid}"))
        return
    link = [[InlineKeyboardButton("🔗 مشاهده پست", url=res.post_url)]] if res.post_url else []
    await show(update, "✅ <b>تبلیغ در کانال منتشر شد.</b>\nپایان را تنظیم کنید تا یادآوری بگیرید و نتیجه ثبت شود.",
               InlineKeyboardMarkup(link + [[_b("📋 کارت تبلیغ", f"d:v:{cid}")]]))


# ---------- کالبک اصلی ----------
@admin_only
async def campaigns_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    parts = update.callback_query.data.split(":")
    action = parts[1]
    uid = update.effective_user.id
    context.user_data.pop("awaiting", None)
    try:
        if action == "l":
            if parts[2] not in KIND_FA:
                raise ValueError("kind")
            await _list(update, context, parts[2])
        elif action == "n":
            if parts[2] not in KIND_FA:
                raise ValueError("kind")
            context.user_data["awaiting"] = f"cmpnew:{parts[2]}"
            await show(update, f"{KIND_ICON[parts[2]]} عنوان یا نام شریک را بنویسید:", _back(f"d:l:{parts[2]}"))
        elif action == "v":
            await _card(update, context, int(parts[2]))
        elif action == "e":
            cid, f = int(parts[2]), parts[3]
            c = ctx.repos.campaigns.get(cid)
            if not c or f not in FIELD_PROMPT or (f in ("p", "b") and c["kind"] != "ad"):
                raise ValueError("edit")
            if c["status"] not in ("draft", "active") or (c["status"] == "active" and f not in ("n", "c")):
                await _card(update, context, cid, "⚠️ این مورد در این وضعیت قابل ویرایش نیست.")
                return
            context.user_data["awaiting"] = f"cmp:{f}:{cid}"
            await show(update, FIELD_PROMPT[f], _back(f"d:v:{cid}"))
        elif action == "pv":
            await _preview(update, context, int(parts[2]))
        elif action == "ok":
            cid, fp = int(parts[2]), parts[3]
            c = ctx.repos.campaigns.get(cid)
            if not c or c["status"] != "draft" or ad_fingerprint(c) != fp:
                await update.callback_query.edit_message_reply_markup(reply_markup=None)
                await show(update, "⚠️ این پیش‌نمایش قدیمی شده است. دوباره پیش‌نمایش بگیرید.", _back(f"d:v:{cid}"))
                return
            await update.callback_query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
                [_b("✅ بله، همین حالا منتشر شود", f"d:go:{cid}:{fp}")], [_b("↩️ برگشت", f"d:bk:{cid}:{fp}")]]))
        elif action == "bk":
            c = ctx.repos.campaigns.get(int(parts[2]))
            if not c:
                raise ValueError("missing")
            await update.callback_query.edit_message_reply_markup(reply_markup=_preview_kb(c, parts[3]))
        elif action == "go":
            await _go(update, context, int(parts[2]), parts[3])
        elif action == "cx":
            try:
                await update.callback_query.edit_message_reply_markup(reply_markup=None)
            except Exception:  # noqa: BLE001
                pass
            await show(update, "❎ لغو شد. چیزی منتشر نشد.", _back(f"d:v:{int(parts[2])}"))
        elif action == "st":
            cid = int(parts[2])
            members = await ctx.channel.member_count(ctx.effective_channel_ref())
            ok = ctx.repos.campaigns.start(cid, members)
            ctx.repos.logs.add("campaign_started", uid, f"id={cid}")
            await _card(update, context, cid, "▶️ شروع شد." if ok else "⚠️ این مورد قابل شروع نیست.")
        elif action == "fin":
            cid = int(parts[2])
            members = await ctx.channel.member_count(ctx.effective_channel_ref())
            ok = ctx.repos.campaigns.finish(cid, members)
            ctx.repos.logs.add("campaign_finished", uid, f"id={cid}")
            await _card(update, context, cid, "✅ پایان یافت و نتیجه ثبت شد." if ok else "⚠️ این مورد فعال نیست.")
        elif action == "sn":
            cid = int(parts[2])
            ctx.repos.campaigns.snooze_end(cid, to_iso(utc_now() + timedelta(hours=1)))
            await _card(update, context, cid, "⏭ یادآوری بعدی ۱ ساعت دیگر.")
        elif action == "can":
            cid = int(parts[2])
            ok = ctx.repos.campaigns.cancel(cid)
            ctx.repos.logs.add("campaign_cancelled", uid, f"id={cid}")
            await _card(update, context, cid, "🚫 لغو شد." if ok else "⚠️ قابل لغو نیست.")
        elif action == "del":
            cid = int(parts[2])
            c = ctx.repos.campaigns.get(cid)
            if not c:
                raise ValueError("missing")
            await show(update, f"🗑 «{esc(c['title'])}» حذف شود؟ این کار قابل بازگشت نیست.",
                       InlineKeyboardMarkup([[_b("🗑 بله، حذف شود", f"d:dy:{cid}"), _b(T.BTN_CANCEL, f"d:v:{cid}")]]))
        elif action == "dy":
            cid = int(parts[2])
            c = ctx.repos.campaigns.get(cid)
            if c and ctx.repos.campaigns.delete(cid):
                ctx.repos.logs.add("campaign_deleted", uid, f"id={cid}")
                await _list(update, context, c["kind"])
            else:
                await show(update, "⚠️ حذف ممکن نیست (کمپین فعال را اول لغو یا تمام کنید).", K.back_to_menu())
        elif action == "inc":
            await _income(update, context)
        else:
            raise ValueError(action)
    except (ValueError, IndexError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def _income(update, context) -> None:
    ctx = ctx_of(context)
    inc = ctx.repos.campaigns.income()
    rev = ctx.repos.payments.revenue()
    text = (f"💰 <b>گزارش درآمد</b>\n\n📢 تبلیغ‌ها: {inc['total']:,} ({inc['count']} تبلیغ؛ ۳۰ روز اخیر {inc['last_30d']:,})\n"
            f"⭐ اشتراک ویژه: {rev['stars']} استارز ({rev['count']} پرداخت؛ ۳۰ روز اخیر {rev['stars_30d']})\n"
            f"👤 مشترک فعال: {rev['active']}\n\nℹ️ مبلغ تبلیغ‌ها همان عددی است که خودتان وارد کرده‌اید.")
    await show(update, text, _back("m:ads"))


# ---------- ورودی متن ----------
def _plain(text: str, limit: int):
    """فقط فاصله‌ها را مرتب می‌کند (برخلاف clean_text، @آیدی و لینک را حذف نمی‌کند)."""
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:limit] or None


def _parse_button(text: str):
    label, sep, url = text.partition("|")
    label, url = label.strip(), url.strip()
    if not sep or not label or len(label) > 40:
        raise ValueError("قالب: متن | لینک (متن حداکثر ۴۰ حرف)")
    if re.match(r"^(t\.me|telegram\.me)/", url, re.I):
        url = "https://" + url
    if not re.match(r"^https?://\S+$", url, re.I):
        raise ValueError("لینک باید با https:// یا t.me/ شروع شود")
    return label, url


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    ctx = ctx_of(context)
    raw = (update.effective_message.text or "").strip()
    parts = awaiting.split(":")
    if parts[0] == "cmpnew":
        kind = parts[1]
        title = _plain(raw, 60)    # آیدی/لینک مجاز است (نام شریک مثل @channel)
        if not title:
            await show(update, "❌ عنوان معتبر بنویسید یا لغو کنید.", _back(f"d:l:{kind}"))
            return
        context.user_data.pop("awaiting", None)
        cid = ctx.repos.campaigns.create(kind, title)
        ctx.repos.logs.add("campaign_created", update.effective_user.id, f"id={cid} {kind}")
        await _card(update, context, cid, "✅ ساخته شد. اطلاعات را کامل کنید.")
        return
    f, cid = parts[1], int(parts[2])
    c = ctx.repos.campaigns.get(cid)
    if not c or c["status"] not in ("draft", "active"):
        context.user_data.pop("awaiting", None)
        await show(update, NOT_FOUND, K.back_to_menu())
        return
    cancel = _back(f"d:v:{cid}")
    clear = raw == "-"
    try:
        if f == "t":
            val = _plain(raw, 60)
            if not val:
                raise ValueError("عنوان خالی است")
            fields = {"title": val}
        elif f == "k":
            fields = {"partner_link": None if clear else _plain(raw, 200)}
        elif f == "o":
            fields = {"notes": None if clear else raw[:500]}
        elif f == "c":
            if clear:
                fields = {"price": None}
            else:
                digits = ascii_digits(raw).replace(",", "").replace("٬", "").strip()
                if not digits.isdigit() or int(digits) > 10**11:
                    raise ValueError("فقط عدد بنویسید")
                fields = {"price": int(digits)}
        elif f == "p":
            if not raw or len(raw) > MAX_AD_TEXT:
                raise ValueError(f"متن باید ۱ تا {MAX_AD_TEXT} حرف باشد")
            fields = {"post_text": raw}
        elif f == "b":
            fields = {"button_label": None, "button_url": None} if clear else dict(zip(("button_label", "button_url"), _parse_button(raw)))
        elif f in ("s", "n"):
            col = "starts_at" if f == "s" else "ends_at"
            fields = {col: None} if clear else {col: to_iso(parse_user_datetime(raw, utc_now(), ctx.settings.tz))}
            if f == "n" and not clear:
                ctx.repos.campaigns.update(cid, **fields)
                ctx.repos.db.execute("UPDATE campaigns SET reminder_sent=0 WHERE id=?", (cid,))
                fields = {}
        else:
            raise ValueError("field")
    except ValueError as exc:
        await show(update, f"❌ {esc(str(exc))}", cancel)
        return
    if fields:
        ctx.repos.campaigns.update(cid, **fields)
    context.user_data.pop("awaiting", None)
    await _card(update, context, cid, "✅ ذخیره شد.")
