"""مدیریت کاربران، آمار علایق (تجمیعی)، درخواست‌ها و پیشنهاد انتشار برای مدیر (a:)."""
from __future__ import annotations

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, esc, show
from musicbot.recommend import audience_rank
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b, song_label


def _name(u: dict) -> str:
    base = u.get("first_name") or "بدون نام"
    return esc(base) + (f" @{esc(u['username'])}" if u.get("username") else "")


async def show_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    st = ctx.repos.users.stats(exclude=ctx.settings.admin_user_id)
    ud = ctx.repos.userdata
    enabled = ctx.repos.settings.user_features_enabled()
    new_req = ud.count_new_requests()
    text = (
        "👥 <b>مدیریت کاربران</b>\n\n"
        f"امکانات کاربران: {'✅ فعال' if enabled else '⛔ غیرفعال (از ⚙️ تنظیمات روشن کنید)'}\n"
        f"👤 کل کاربران: {st['total']}\n"
        f"🟢 فعال در ۷ روز اخیر: {st['active_7d']}\n"
        f"🔒 دارای رضایت ثبت علایق: {st['consented']}\n"
        f"🚫 مسدود: {st['blocked']}\n"
        f"❤️ مجموع پسندها: {ud.total_likes()}\n"
        f"📨 درخواست‌های جدید: {new_req}"
    )
    kb = InlineKeyboardMarkup([
        [_b("👥 کاربران اخیر", "a:ul"), _b("📊 علایق مخاطبان", "a:int")],
        [_b(f"📨 درخواست‌ها ({new_req})", "a:rq")],
        [_b("👤 نمای کاربر (آزمایش)", "u:home")],
        [_b(T.BTN_BACK, "m:main")],
    ])
    await show(update, text, kb)


async def show_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیشنهاد برای مدیر: کدام آهنگ آماده را منتشر کنم؟ (بر اساس علایق تجمیعی)"""
    ctx = ctx_of(context)
    ready = ctx.repos.songs.all_with_status("ready", 200)
    ranked = audience_rank(ctx.repos, ready)[:5]
    top = ctx.repos.userdata.top_liked(3)
    lines = ["💡 <b>پیشنهاد انتشار</b>\n"]
    if ranked:
        lines.append("آهنگ‌های آماده، به ترتیب تطابق با سلیقه مخاطبان:")
        for s, sc in ranked:
            lines.append(f"• {esc(song_label(s, 30))} — امتیاز {sc:g}")
        if all(sc == 0 for _, sc in ranked):
            lines.append("\nℹ️ هنوز علایقی ثبت نشده؛ ترتیب فقط براساس تازگی است.")
    else:
        lines.append("آهنگ آماده‌ای ندارید. ابتدا آهنگ را در آرشیو ثبت کنید.")
    if top:
        lines.append("\n❤️ محبوب‌ترین‌ها:")
        lines += [f"• {esc((t['artist'] or '') + ' - ' + (t['title'] or ''))} ({t['c']})" for t in top]
    rows = [[_b(song_label(s, 34), f"g:v:{s['id']}")] for s, _ in ranked]
    rows.append([_b(T.BTN_BACK, "m:main")])
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))


@admin_only
async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    parts = update.callback_query.data.split(":")
    action = parts[1]
    uid = update.effective_user.id
    context.user_data.pop("awaiting", None)
    try:
        if action == "ul":
            users = ctx.repos.users.recent(10, exclude=ctx.settings.admin_user_id)
            if not users:
                await show(update, "هنوز کاربری ثبت نشده است.", InlineKeyboardMarkup([[_b(T.BTN_BACK, "m:users")]]))
                return
            rows = [[_b(("🚫 " if u["is_blocked"] else "👤 ") + (u.get("first_name") or "بدون نام")[:20]
                        + (f" @{u['username']}" if u.get("username") else ""), f"a:uv:{u['telegram_user_id']}")] for u in users]
            rows.append([_b(T.BTN_BACK, "m:users")])
            await show(update, "👥 <b>کاربران اخیر</b>", InlineKeyboardMarkup(rows))
        elif action == "uv":
            await _user_panel(update, context, int(parts[2]))
        elif action == "ub":
            target = int(parts[2])
            if target == ctx.settings.admin_user_id or not ctx.repos.users.get(target):
                raise ValueError("target")
            blocked = not ctx.repos.users.is_blocked(target)
            ctx.repos.users.set_blocked(target, blocked)
            ctx.repos.logs.add("user_blocked" if blocked else "user_unblocked", uid, f"id={target}")
            await _user_panel(update, context, target)
        elif action in ("gp", "rp"):
            target = int(parts[2])
            if target == ctx.settings.admin_user_id or not ctx.repos.users.get(target):
                raise ValueError("target")
            if action == "gp":
                ctx.repos.payments.grant(target, 30)
            else:
                ctx.repos.payments.revoke(target)
            ctx.repos.logs.add("premium_gift" if action == "gp" else "premium_revoked", uid, f"id={target}")
            await _user_panel(update, context, target)
        elif action == "int":
            await _interests_stats(update, context)
        elif action == "rq":
            await _requests(update, context)
        elif action in ("rd", "rx"):
            ctx.repos.userdata.set_request_status(int(parts[2]), "done" if action == "rd" else "dismissed")
            await _requests(update, context)
        else:
            raise ValueError(action)
    except (ValueError, IndexError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def _user_panel(update, context, target: int) -> None:
    ctx = ctx_of(context)
    u = ctx.repos.users.get(target)
    if not u or target == ctx.settings.admin_user_id:
        await show(update, "❌ کاربر پیدا نشد.", K.back_to_menu())
        return
    text = (f"👤 <b>{_name(u)}</b>\n🆔 <code>{target}</code>\n"
            f"اولین ورود: {esc(u['first_seen_at'][:10])}\nآخرین فعالیت: {esc(u['last_seen_at'][:16].replace('T', ' '))} (UTC)\n"
            f"رضایت ثبت علایق: {'✅' if u['consent_at'] else '—'}\n"
            f"اشتراک ویژه: {('✅ تا ' + esc(u['premium_until'][:10])) if ctx.repos.payments.is_premium(target) else '—'}\nوضعیت: {'🚫 مسدود' if u['is_blocked'] else '🟢 عادی'}")
    kb = InlineKeyboardMarkup([
        [_b("✅ رفع مسدودی" if u["is_blocked"] else "🚫 مسدود کردن", f"a:ub:{target}")],
        [_b("🎁 ۳۰ روز اشتراک رایگان", f"a:gp:{target}"), _b("⛔ لغو اشتراک", f"a:rp:{target}")],
        [_b(T.BTN_BACK, "a:ul")],
    ])
    await show(update, text, kb)


async def _interests_stats(update, context) -> None:
    ctx = ctx_of(context)
    agg = ctx.repos.userdata.aggregate()
    titles = {"genre": ("🎸 سبک‌ها", "genres"), "mood": ("🎭 حال‌وهواها", "moods"), "language": ("🌐 زبان‌ها", "languages")}
    lines = ["📊 <b>علایق مخاطبان</b> (فقط آمار تجمیعی، بدون هویت)\n"]
    any_data = False
    for kind, (title, table) in titles.items():
        names = {str(i["key"]): i["name_fa"] for i in ctx.repos.categories.list(table)}
        items = sorted(agg[kind].items(), key=lambda x: -x[1])[:5]
        if items:
            any_data = True
            lines.append(f"{title}: " + "، ".join(f"{esc(names.get(r, r))} ({c})" for r, c in items))
    if not any_data:
        lines.append("هنوز کسی علایقی ثبت نکرده است.")
    await show(update, "\n".join(lines), InlineKeyboardMarkup([[_b(T.BTN_BACK, "m:users")]]))


async def _requests(update, context) -> None:
    ctx = ctx_of(context)
    reqs = ctx.repos.userdata.new_requests(10)
    if not reqs:
        await show(update, "📨 درخواست جدیدی نیست.", InlineKeyboardMarkup([[_b(T.BTN_BACK, "m:users")]]))
        return
    lines = ["📨 <b>درخواست‌های آهنگ</b>\n"]
    rows = []
    for r in reqs:
        lines.append(f"#{r['id']} — {_name(r)}\n{esc(r['text'])}\n")
        rows.append([_b(f"✔️ انجام شد #{r['id']}", f"a:rd:{r['id']}"), _b(f"🗑 #{r['id']}", f"a:rx:{r['id']}")])
    rows.append([_b(T.BTN_BACK, "m:users")])
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))
