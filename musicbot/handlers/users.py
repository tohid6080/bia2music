"""بخش کاربران عادی (u:): جست‌وجو، پیشنهاد، پلی‌لیست، پسند/علایق با رضایت، درخواست آهنگ.
فقط آهنگ‌های منتشرشده نمایش داده می‌شود؛ فایل ارسال نمی‌شود (لینک پست کانال)."""
from __future__ import annotations

import logging
import math

from telegram import LabeledPrice, Update
from telegram.error import TelegramError
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

from musicbot.auth import is_admin
from musicbot.handlers.common import ctx_of, esc, show
from musicbot.handlers.premium import BENEFITS, CURRENCY, is_premium, payload_for, premium_settings
from musicbot.publishing.service import send_song_to_user
from musicbot.publishing.timeutil import format_local
from musicbot.recommend import suggest_for_user
from musicbot.songs.textutils import clean_text, normalize
from musicbot.ui import user_ui as UU

log = logging.getLogger(__name__)
DIMS = {"l": ("languages", "language", "🌐 زبان"), "g": ("genres", "genre", "🎸 سبک"), "m": ("moods", "mood", "🎭 حال‌وهوا")}
MAX_REQUESTS_PER_DAY = 3
MAX_REQUESTS_PREMIUM = 10
DISABLED_TEXT = "🚧 این بخش فعلاً فعال نیست."
NOT_FOUND = "❌ این آهنگ پیدا نشد."


def _channel_info(ctx) -> tuple[str, str | None]:
    ref = ctx.effective_channel_ref()
    active = ctx.repos.channel.get_active()
    title = (active.title if active and active.title else "Bia2Music")
    url = f"https://t.me/{ref[1:]}" if ref and ref.startswith("@") else None
    return title, url


async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    context.user_data.pop("awaiting", None)
    title, url = _channel_info(ctx)
    await show(update, UU.home_text(title), UU.home_keyboard(url, premium_settings(ctx)["enabled"]))


def _allowed(ctx, user_id: int) -> str | None:
    """None = مجاز؛ وگرنه پیام رد."""
    if is_admin(ctx.settings, ctx.repos, user_id):
        return None
    if not ctx.repos.settings.user_features_enabled():
        return DISABLED_TEXT
    if ctx.repos.users.is_blocked(user_id):
        return "⛔ دسترسی شما محدود شده است."
    return None


def _touch(ctx, user) -> None:
    ctx.repos.users.touch(user.id, user.username, user.first_name, user.language_code)


async def user_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """/start برای کاربر غیرمدیر. True اگر منوی کاربر نشان داده شد."""
    ctx = ctx_of(context)
    user = update.effective_user
    _touch(ctx, user)
    reason = _allowed(ctx, user.id)
    if reason:
        return False
    ctx.repos.metrics.incr("start")
    await show_home(update, context)
    return True


async def user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    user, chat, query = update.effective_user, update.effective_chat, update.callback_query
    if user is None or chat is None or chat.type != ChatType.PRIVATE:
        await query.answer()
        return
    reason = _allowed(ctx, user.id)
    if reason:
        await query.answer(reason, show_alert=True)
        return
    if not is_admin(ctx.settings, ctx.repos, user.id) and not ctx.limiter.allow(user.id):
        await query.answer("⏳ کمی آهسته‌تر لطفاً.")
        return
    await query.answer()
    _touch(ctx, user)
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action != "q":
        context.user_data.pop("awaiting", None)
    try:
        await _dispatch(update, context, ctx, user.id, action, parts)
    except (ValueError, IndexError, KeyError):
        await show(update, "❌ درخواست نامعتبر بود.", UU.back_home())


async def _dispatch(update, context, ctx, uid: int, action: str, parts: list[str]) -> None:
    if action == "home":
        await show_home(update, context)
    elif action == "s":
        context.user_data["awaiting"] = "usearch"
        await show(update, "🔍 نام آهنگ یا خواننده را بنویسید:", UU.cancel_home())
    elif action == "l":
        await _list(update, context, parts[2], int(parts[3]))
    elif action == "v":
        await _song(update, context, int(parts[2]))
    elif action == "r":
        await _suggest(update, context)
    elif action in ("cm", "cl", "cg"):
        dim = action[1]
        items = ctx.repos.categories.list(DIMS[dim][0])
        await show(update, f"{DIMS[dim][2]} را انتخاب کنید:", UU.pick_keyboard(items, f"u:l:{dim}.", ":0"))
    elif action == "p":
        await _playlists(update, context)
    elif action == "pl":
        await _playlist(update, context, int(parts[2]), int(parts[3]))
    elif action == "lk":
        await _like(update, context, uid, int(parts[2]))
    elif action == "cy":
        ctx.repos.userdata.give_consent(uid)
        ctx.repos.logs.add("user_consent", uid)
        after = int(parts[2])
        if after > 0:
            await _like(update, context, uid, after)
        else:
            await _interests(update, context, uid)
    elif action == "i":
        await _interests(update, context, uid)
    elif action == "ip":
        await _interest_picker(update, context, uid, parts[2])
    elif action == "it":
        dim, ref = parts[2], parts[3]
        _, kind, _ = DIMS[dim]
        if not ctx.repos.categories.exists(DIMS[dim][0], ref if dim == "l" else int(ref)):
            raise ValueError("ref")
        ctx.repos.userdata.toggle_interest(uid, kind, ref)
        await _interest_picker(update, context, uid, dim)
    elif action == "ac":
        on = ctx.repos.userdata.has_activity_consent(uid)
        await show(update, UU.ACTIVITY_INFO + f"\n\nوضعیت فعلی: {'✅ روشن' if on else '⛔ خاموش'}", UU.activity_keyboard(on))
    elif action in ("acy", "acn"):
        if action == "acy" and not ctx.repos.userdata.has_consent(uid):
            await show(update, UU.CONSENT, UU.consent_keyboard(0))        # ابتدا رضایت پایه‌ی ثبت اطلاعات
            return
        ctx.repos.userdata.set_activity_consent(uid, action == "acy")
        ctx.repos.logs.add("activity_consent_on" if action == "acy" else "activity_consent_off", uid)
        await show(update, UU.ACTIVITY_INFO + f"\n\nوضعیت فعلی: {'✅ روشن' if action == 'acy' else '⛔ خاموش (سابقه پاک شد)'}",
                   UU.activity_keyboard(action == "acy"))
    elif action == "dx":
        await show(update, "🗑 همه‌ی علایق، پسندها و درخواست‌های شما حذف شود؟ این کار قابل بازگشت نیست.", UU.delete_confirm())
    elif action == "dy":
        ctx.repos.userdata.delete_all(uid)
        ctx.repos.logs.add("user_data_deleted", uid)
        await show(update, "✅ همه‌ی اطلاعات شما حذف شد.", UU.back_home())
    elif action == "q":
        context.user_data["awaiting"] = "urequest"
        await show(update, "🎤 نام آهنگ و خواننده‌ای را که می‌خواهید بنویسید (حداکثر ۲۰۰ حرف):", UU.cancel_home())
    elif action == "pv":
        await show(update, UU.PRIVACY, UU.back_home())
    elif action == "pr":
        await _premium_screen(update, context, uid)
    elif action == "buy":
        await _buy(update, context, uid)
    elif action == "dl":
        await _download(update, context, uid, int(parts[2]))
    else:
        raise ValueError(action)


# ---------- فهرست‌ها ----------
async def _list(update, context, flt: str, page: int) -> None:
    ctx = ctx_of(context)
    uid = update.effective_user.id
    pub = True
    if flt == "likes":
        if not ctx.repos.userdata.has_consent(uid):
            await show(update, UU.CONSENT, UU.consent_keyboard(0))
            return
        total = ctx.repos.userdata.liked_count(uid)
        title = "❤️ پسندهای من"
    else:
        q = context.user_data.get("u_q")
        q_norm = normalize(q) if flt == "q" else None
        if flt == "q" and not q_norm:
            await show(update, "⌛ جست‌وجو منقضی شده. دوباره بنویسید.", UU.back_home())
            return
        total = ctx.repos.songs.count(flt, q_norm, published_only=pub)
        title = _title(ctx, flt, q)
    pages = max(1, math.ceil(total / UU.PAGE))
    page = min(max(page, 0), pages - 1)
    if flt == "likes":
        songs = ctx.repos.userdata.liked_songs(uid, UU.PAGE, page * UU.PAGE)
    else:
        songs = ctx.repos.songs.list(flt, q_norm, UU.PAGE, page * UU.PAGE, published_only=pub)
    if total == 0:
        await show(update, f"📋 <b>{esc(title)}</b>\n\nموردی پیدا نشد.", UU.empty_keyboard())
        return
    await show(update, f"📋 <b>{esc(title)}</b>\n{total} مورد · صفحه {page + 1} از {pages}", UU.list_keyboard(songs, flt, page, pages))


def _title(ctx, flt: str, q) -> str:
    if flt == "q":
        return f"نتایج «{q}»"
    dim, _, val = flt.partition(".")
    for it in ctx.repos.categories.list(DIMS[dim][0]):
        if str(it["key"]) == val:
            return f"{DIMS[dim][2]}: {it['name_fa']}"
    raise ValueError("filter")


async def _song(update, context, song_id: int, note: str = "") -> None:
    ctx = ctx_of(context)
    song = ctx.repos.songs.get_published(song_id)
    if not song:
        await show(update, NOT_FOUND, UU.back_home())
        return
    ud = ctx.repos.userdata
    ctx.repos.metrics.incr("song_view")
    ud.record_event(update.effective_user.id, song_id, "view")
    download = premium_settings(ctx)["enabled"] and bool(song.get("telegram_file_id"))
    await show(update, UU.song_text(song, ud.like_count(song_id)) + (f"\n\n{note}" if note else ""),
               UU.song_keyboard(song, ud.is_liked(update.effective_user.id, song_id), download))


async def _like(update, context, uid: int, song_id: int) -> None:
    ctx = ctx_of(context)
    if not ctx.repos.songs.get_published(song_id):
        await show(update, NOT_FOUND, UU.back_home())
        return
    if not ctx.repos.userdata.has_consent(uid):
        await show(update, UU.CONSENT, UU.consent_keyboard(song_id))
        return
    if ctx.repos.userdata.toggle_like(uid, song_id):
        ctx.repos.metrics.incr("like")
        ctx.repos.userdata.record_event(uid, song_id, "like")
    await _song(update, context, song_id)


async def _suggest(update, context) -> None:
    ctx = ctx_of(context)
    uid = update.effective_user.id
    seen = context.user_data.setdefault("u_seen", [])
    picks = suggest_for_user(ctx.repos, uid, 3, seen)
    if not picks and seen:
        seen.clear()
        picks = suggest_for_user(ctx.repos, uid, 3, seen)
    if not picks:
        await show(update, "هنوز آهنگی منتشر نشده است.", UU.back_home())
        return
    ctx.repos.metrics.incr("suggest")
    seen.extend(s["id"] for s in picks)
    del seen[:-60]
    hint = ""
    if not (ctx.repos.userdata.has_consent(uid) and ctx.repos.userdata.interests(uid)):
        hint = "\n\n💡 برای پیشنهاد دقیق‌تر، از «⚙️ علایق من» سلیقه‌تان را انتخاب کنید."
    await show(update, "💡 <b>پیشنهادهای من برای شما</b>" + hint, UU.suggest_keyboard(picks))


async def _playlists(update, context) -> None:
    ctx = ctx_of(context)
    lists = ctx.repos.playlists.list(public_only=True)
    if not lists:
        await show(update, "🎧 هنوز پلی‌لیستی وجود ندارد.", UU.back_home())
        return
    from musicbot.ui.song_ui import _b
    from telegram import InlineKeyboardMarkup

    rows = [[_b(f"{'⭐' if p['is_premium'] else '🎧'} {p['name']} ({p['public']})", f"u:pl:{p['id']}:0")] for p in lists]
    rows.append([_b("🔙 بازگشت", UU.HOME)])
    await show(update, "🎧 <b>پلی‌لیست‌ها</b>", InlineKeyboardMarkup(rows))


async def _playlist(update, context, pid: int, page: int) -> None:
    ctx = ctx_of(context)
    pl = ctx.repos.playlists.get(pid)
    if not pl or pl["public"] == 0:
        await show(update, "❌ پلی‌لیست پیدا نشد.", UU.back_home())
        return
    if pl["is_premium"] and not is_premium(ctx, update.effective_user.id):
        await _premium_screen(update, context, update.effective_user.id, "🔒 این پلی‌لیست ویژه‌ی مشترکین است.")
        return
    pages = max(1, math.ceil(pl["public"] / UU.PAGE))
    page = min(max(page, 0), pages - 1)
    songs = ctx.repos.playlists.songs(pid, True, UU.PAGE, page * UU.PAGE)
    await show(update, f"🎧 <b>{esc(pl['name'])}</b>\n{pl['public']} آهنگ · صفحه {page + 1} از {pages}",
               UU.playlist_song_keyboard(songs, pid, page, pages))


# ---------- علایق ----------
async def _interests(update, context, uid: int) -> None:
    ctx = ctx_of(context)
    if not ctx.repos.userdata.has_consent(uid):
        await show(update, UU.CONSENT, UU.consent_keyboard(0))
        return
    names = {}
    for dim, (table, kind, _) in DIMS.items():
        names[kind] = {str(i["key"]): i["name_fa"] for i in ctx.repos.categories.list(table)}
    chosen = ctx.repos.userdata.interests(uid)
    lines = [names[k].get(r, r) for k, r in sorted(chosen)]
    body = "، ".join(esc(x) for x in lines) or "هنوز چیزی انتخاب نکرده‌اید."
    await show(update, f"⚙️ <b>علایق من</b>\n\n{body}\n\nبر اساس این انتخاب‌ها پیشنهاد می‌گیرید.", UU.interests_keyboard())


async def _interest_picker(update, context, uid: int, dim: str) -> None:
    ctx = ctx_of(context)
    if dim not in DIMS:
        raise ValueError("dim")
    if not ctx.repos.userdata.has_consent(uid):
        await show(update, UU.CONSENT, UU.consent_keyboard(0))
        return
    table, kind, title = DIMS[dim]
    chosen = {r for k, r in ctx.repos.userdata.interests(uid) if k == kind}
    await show(update, f"{title}‌هایی که دوست دارید را انتخاب کنید (دوباره بزنید تا برداشته شود):",
               UU.interest_picker(ctx.repos.categories.list(table), dim, chosen))


# ---------- متن آزاد ----------
async def user_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    user = update.effective_user
    reason = _allowed(ctx, user.id)
    if reason:
        if reason != DISABLED_TEXT:
            await update.effective_message.reply_text(reason)
        return
    if not is_admin(ctx.settings, ctx.repos, user.id) and not ctx.limiter.allow(user.id):
        return
    _touch(ctx, user)
    text = (update.effective_message.text or "").strip()
    if context.user_data.get("awaiting") == "urequest":
        await _receive_request(update, context, text)
        return
    context.user_data.pop("awaiting", None)
    q = clean_text(text, 40)
    if not q or not normalize(q):
        await show(update, "🔍 نام آهنگ یا خواننده را بنویسید.", UU.back_home())
        return
    context.user_data["u_q"] = q
    ctx.repos.metrics.incr("search")
    await _list(update, context, "q", 0)


async def _receive_request(update, context, text: str) -> None:
    ctx = ctx_of(context)
    user = update.effective_user
    cleaned = clean_text(text, 200)
    if not cleaned:
        await show(update, "❌ متن معتبر بنویسید یا لغو کنید.", UU.cancel_home())
        return
    context.user_data.pop("awaiting", None)
    limit = MAX_REQUESTS_PREMIUM if is_premium(ctx, user.id) else MAX_REQUESTS_PER_DAY
    if ctx.repos.userdata.requests_last_day(user.id) >= limit:
        await show(update, f"⏳ حداکثر {limit} درخواست در روز مجاز است. فردا دوباره امتحان کنید.", UU.back_home())
        return
    ctx.repos.metrics.incr("request")
    rid = ctx.repos.userdata.add_request(user.id, cleaned)
    ctx.repos.logs.add("song_request", user.id, f"id={rid}")
    who = esc(user.first_name or "کاربر") + (f" (@{esc(user.username)})" if user.username else "")
    try:
        await context.bot.send_message(ctx.settings.admin_user_id, f"📨 <b>درخواست آهنگ جدید</b> #{rid}\n{who}\n\n{esc(cleaned)}",
                                       parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001 - درخواست ذخیره شده و در «درخواست‌ها» دیده می‌شود
        log.warning("request notify failed")
    await show(update, "✅ درخواست شما برای مدیر ارسال شد. ممنون!", UU.back_home())


# ---------- اشتراک ویژه ----------
async def _premium_screen(update, context, uid: int, note: str = "") -> None:
    ctx = ctx_of(context)
    s = premium_settings(ctx)
    if not s["enabled"]:
        await show(update, "🚧 اشتراک ویژه فعلاً فعال نیست.", UU.back_home())
        return
    ctx.repos.metrics.incr("premium_view")
    until = ctx.repos.payments.premium_until(uid)
    active = ctx.repos.payments.is_premium(uid)
    text = UU.premium_text(BENEFITS, s["stars"], s["days"], format_local(until, ctx.settings.tz) if active else None)
    await show(update, (f"{note}\n\n" if note else "") + text, UU.premium_keyboard(active))


async def _buy(update, context, uid: int) -> None:
    ctx = ctx_of(context)
    s = premium_settings(ctx)
    if not s["enabled"]:
        await show(update, "🚧 اشتراک ویژه فعلاً فعال نیست.", UU.back_home())
        return
    try:
        await context.bot.send_invoice(
            chat_id=uid, title="اشتراک ویژه Bia2Music", description=f"{s['days']} روز دسترسی به مزایای ویژه ربات",
            payload=payload_for(uid, s["days"], s["stars"]), currency=CURRENCY, prices=[LabeledPrice("اشتراک ویژه", s["stars"])])
    except TelegramError:
        await show(update, "⚠️ ساخت صورت‌حساب ممکن نشد. کمی بعد دوباره تلاش کنید.", UU.back_home())


async def _download(update, context, uid: int, song_id: int) -> None:
    """دریافت فایل: فقط برای مشترک ویژه (و مدیر)، فقط به چت خود کاربر."""
    ctx = ctx_of(context)
    song = ctx.repos.songs.get_published(song_id)
    if not song:
        await show(update, NOT_FOUND, UU.back_home())
        return
    if not premium_settings(ctx)["enabled"]:
        await show(update, "🚧 این قابلیت فعلاً فعال نیست.", UU.back_home())
        return
    if not is_premium(ctx, uid):
        await _premium_screen(update, context, uid, "📥 دریافت فایل مخصوص مشترکین ویژه است.")
        return
    ok = await send_song_to_user(context.bot, uid, song)
    if ok:
        ctx.repos.metrics.incr("download")
        ctx.repos.userdata.record_event(uid, song_id, "download")
    await _song(update, context, song_id, "📥 فایل ارسال شد." if ok else "⚠️ ارسال فایل ممکن نشد؛ کمی بعد دوباره تلاش کنید.")
