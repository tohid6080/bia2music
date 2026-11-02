"""📈 رشد و توسعه کانال: کمپین‌های جذب مخاطب با لینک دعوت اختصاصی، QR، شمارش عضویت از رویداد تلگرام و گزارش (r:).

اصول: فقط جذب مخاطب واقعی؛ هیچ ابزاری برای عضو فیک، عضویت اجباری یا پیام انبوه وجود ندارد. کلیک لینک در دسترس نیست
و صفر/تخمینی نمایش داده نمی‌شود. هیچ هویت یا نام عضوی ذخیره نمی‌شود."""
from __future__ import annotations

import hashlib
import html
import logging
import re
import secrets
from datetime import timezone

from telegram import InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from musicbot import growth_reports as GR
from musicbot.db.repositories import GrowthRepo
from musicbot.handlers.common import admin_only, ctx_of, show
from musicbot.publishing.timeutil import format_local, to_iso, utc_now
from musicbot.qr import make_qr_png
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b

log = logging.getLogger(__name__)
esc = html.escape
IN_STATUSES = {"member", "administrator", "creator", "restricted"}
OUT_STATUSES = {"left", "kicked"}
LINK_NAME_MAX = 32       # سقف طول نام لینک در تلگرام
NAME_MAX = 40


def _back(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_BACK, target)]])


# ---------- رویداد عضویت ----------
def _hash(ctx, user_id: int) -> str:
    st = ctx.repos.settings
    salt = st.get("hash_salt")
    if not salt:
        salt = secrets.token_hex(16)
        st.set("hash_salt", salt)
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()


def _same_channel(ref, chat) -> bool:
    if not ref or chat is None:
        return False
    if ref.startswith("@"):
        return (getattr(chat, "username", None) or "").lower() == ref[1:].lower()
    return str(chat.id) == ref


async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """رویداد ورود/خروج. فقط شمارنده ذخیره می‌شود؛ ربات‌ها و تغییر نقش مدیرها نادیده گرفته می‌شود."""
    ctx = ctx_of(context)
    cm = update.chat_member
    if cm is None or not _same_channel(ctx.effective_channel_ref(), cm.chat):
        return
    st = ctx.repos.settings
    link = cm.invite_link.invite_link if getattr(cm, "invite_link", None) else None
    st.set("ce_total", str(int(st.get("ce_total", "0")) + 1))          # «رویداد دریافت شد» (برای آزمون قابلیت)
    if link:
        st.set("ce_with_link", str(int(st.get("ce_with_link", "0")) + 1))
    st.set("ce_last_at", to_iso(utc_now()))
    user = cm.new_chat_member.user
    if getattr(user, "is_bot", False):
        return
    old, new = cm.old_chat_member.status, cm.new_chat_member.status
    day = cm.date.astimezone(timezone.utc).strftime("%Y-%m-%d")
    g = ctx.repos.growth
    hashing = st.get("growth_hash", "0") == "1"
    if old in OUT_STATUSES and new in IN_STATUSES:
        camp = g.campaign_by_link(link)
        cid = camp["id"] if camp else 0
        g.record(day, cid, joins=1)
        if hashing and cid:
            g.remember_hash(_hash(ctx, user.id), cid, day)
    elif old in IN_STATUSES and new in OUT_STATUSES:
        cid = (g.pop_hash(_hash(ctx, user.id)) or 0) if hashing else 0
        g.record(day, cid, leaves=1)


# ---------- منو و گزارش‌ها ----------
async def show_hub(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    ctx = ctx_of(context)
    members = await ctx.channel.member_count(ctx.effective_channel_ref())
    if members is not None:
        ctx.repos.metrics.snapshot_members(members)
    hashing = ctx.repos.settings.get("growth_hash", "0") == "1"
    kb = InlineKeyboardMarkup([
        [_b("🎯 کمپین‌های جذب مخاطب", "r:l")],
        [_b("📝 متن‌های تبلیغ", "w:tx"), _b("🗓 برنامه‌ی هفتگی", "w:pl")],
        [_b("🏁 نقاط عطف", "w:ms")],
        [_b("📊 گزارش رشد", "r:rep"), _b("📈 نمودار", "r:ch")],
        [_b("🧪 وضعیت دریافت رویداد عضویت", "r:cap")],
        [_b(f"🔐 تفکیک خروج بر اساس کمپین: {'✅' if hashing else '⛔'}", "r:hs")],
        [_b(T.BTN_BACK, "m:main")],
    ])
    await show(update, GR.hub_text(ctx, members) + (f"\n\n{note}" if note else ""), kb)


async def _campaign_list(update, context) -> None:
    ctx = ctx_of(context)
    camps = ctx.repos.growth.list_campaigns()
    rows = [[_b(f"{'🟢' if c['status'] == 'active' else '⚪'} {GR.kind_label(c['kind'])} · {c['name'][:22]}", f"r:v:{c['id']}")] for c in camps]
    rows.append([_b("➕ کمپین جدید", "r:n")])
    rows.append([_b(T.BTN_BACK, "m:growth")])
    hint = "برای هر منبع جذب مخاطب (اینستاگرام، واتساپ، دوستان و ...) یک لینک دعوت اختصاصی بسازید تا عضویت‌ها به تفکیک شمرده شود."
    await show(update, f"🎯 <b>کمپین‌ها</b> ({len(camps)})\n{hint}", InlineKeyboardMarkup(rows))


async def _card(update, context, cid: int, note: str = "") -> None:
    ctx = ctx_of(context)
    c = ctx.repos.growth.get_campaign(cid)
    if not c:
        await show(update, "❌ کمپین پیدا نشد.", K.back_to_menu())
        return
    lines = [f"{GR.kind_label(c['kind'])} · <b>{esc(c['name'])}</b>",
             f"وضعیت: {'🟢 فعال' if c['status'] == 'active' else '⚪ ابطال‌شده'}",
             f"🗓 ساخته‌شده: {format_local(c['created_at'], ctx.settings.tz)}"]
    if c["invite_link"]:
        lines.append(f"🔗 <code>{esc(c['invite_link'])}</code>")
    if GR.events_available(ctx):
        per30 = ctx.repos.growth.per_campaign(30).get(cid, {"joins": 0})["joins"]
        per_all = ctx.repos.growth.per_campaign(None).get(cid, {"joins": 0})["joins"]
        lines.append(f"👥 عضو جدید از این لینک: {per30} (۳۰ روز) · کل {per_all}")
    else:
        lines.append(f"👥 عضویت از این لینک: {GR.NA} (رویداد عضویت دریافت نشده)")
    lines.append("ℹ️ تعداد کلیک در دسترس نیست؛ فقط عضویت‌های تأییدشده شمرده می‌شود.")
    if note:
        lines.append(f"\n{note}")
    i = c["id"]
    rows = []
    if c["status"] == "active" and c["invite_link"]:
        rows.append([_b("🔳 QR کد", f"r:qr:{i}"), _b("📋 لینک (برای کپی)", f"r:lk:{i}")])
        rows.append([_b("🚫 ابطال لینک", f"r:rv:{i}")])
    if c["status"] == "revoked":
        rows.append([_b("🗑 حذف کمپین", f"r:del:{i}")])
    rows.append([_b(T.BTN_BACK, "r:l"), _b(T.BTN_MAIN_MENU, "m:main")])
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))


# ---------- کالبک ----------
@admin_only
async def growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    parts = update.callback_query.data.split(":")
    action = parts[1]
    uid = update.effective_user.id
    context.user_data.pop("awaiting", None)
    try:
        if action == "l":
            await _campaign_list(update, context)
        elif action == "n":
            kinds = list(GrowthRepo.KINDS.items())
            rows = [[_b(f"{icon} {name}", f"r:nk:{key}") for key, (icon, name) in kinds[i:i + 2]] for i in range(0, len(kinds), 2)]
            rows.append([_b(T.BTN_CANCEL, "r:l")])
            await show(update, "🎯 منبع این کمپین چیست؟", InlineKeyboardMarkup(rows))
        elif action == "nk":
            if parts[2] not in GrowthRepo.KINDS:
                raise ValueError("kind")
            context.user_data["awaiting"] = f"grnew:{parts[2]}"
            await show(update, f"✏️ یک نام کوتاه برای کمپین بنویسید (حداکثر {NAME_MAX} حرف). مثال: «استوری اینستاگرام مهر»", _back("r:l"))
        elif action == "v":
            await _card(update, context, int(parts[2]))
        elif action == "lk":
            c = ctx.repos.growth.get_campaign(int(parts[2]))
            if not c or not c["invite_link"]:
                raise ValueError("campaign")
            await show(update, f"📋 لینک «{esc(c['name'])}» (روی آن بزنید تا کپی شود):\n\n<code>{esc(c['invite_link'])}</code>", _back(f"r:v:{c['id']}"))
        elif action == "qr":
            await _send_qr(update, context, int(parts[2]))
        elif action == "rv":
            c = ctx.repos.growth.get_campaign(int(parts[2]))
            if not c or c["status"] != "active":
                raise ValueError("campaign")
            await show(update, f"🚫 لینک «{esc(c['name'])}» ابطال شود؟\nبعد از ابطال کسی نمی‌تواند با آن وارد شود (اعضای قبلی می‌مانند). این کار قابل بازگشت نیست.",
                       InlineKeyboardMarkup([[_b("🚫 بله، ابطال شود", f"r:rvy:{c['id']}"), _b(T.BTN_CANCEL, f"r:v:{c['id']}")]]))
        elif action == "rvy":
            await _revoke(update, context, int(parts[2]), uid)
        elif action == "del":
            c = ctx.repos.growth.get_campaign(int(parts[2]))
            if not c or c["status"] != "revoked":
                raise ValueError("campaign")
            await show(update, f"🗑 کمپین «{esc(c['name'])}» حذف شود؟ آمار عضویت آن به «منبع نامشخص» منتقل می‌شود.",
                       InlineKeyboardMarkup([[_b("🗑 بله، حذف شود", f"r:dy:{c['id']}"), _b(T.BTN_CANCEL, f"r:v:{c['id']}")]]))
        elif action == "dy":
            if ctx.repos.growth.delete_campaign(int(parts[2])):
                ctx.repos.logs.add("campaign_growth_deleted", uid, f"id={parts[2]}")
            await _campaign_list(update, context)
        elif action == "rep":
            await show(update, GR.report_text(ctx, await ctx.channel.member_count(ctx.effective_channel_ref())), _back("m:growth"))
        elif action == "ch":
            await show(update, GR.chart_text(ctx), _back("m:growth"))
        elif action == "cap":
            ref = ctx.effective_channel_ref()
            status = await ctx.channel.check(ref) if ref else None
            await show(update, GR.capability_text(ctx, status), _back("m:growth"))
        elif action == "hs":
            if ctx.repos.settings.get("growth_hash", "0") == "1":
                ctx.repos.settings.set("growth_hash", "0")
                ctx.repos.growth.clear_hashes()
                ctx.repos.logs.add("growth_hash_off", uid)
                await show_hub(update, context, "⛔ خاموش شد و هش‌های ذخیره‌شده پاک شدند.")
            else:
                await show(update, "🔐 <b>تفکیک خروج بر اساس کمپین</b>\n\nبرای اینکه بدانید اعضای هر کمپین چند درصدشان ماندند، ربات از شناسه‌ی عضو یک "
                                   "<b>هش نمکی یک‌طرفه</b> می‌سازد (خود شناسه، نام یا نام‌کاربری ذخیره نمی‌شود) و با خروج همان عضو پاکش می‌کند.\n"
                                   "پیش‌فرض خاموش است تا کمترین اطلاعات ذخیره شود. روشن شود؟",
                           InlineKeyboardMarkup([[_b("✅ بله، روشن شود", "r:hsy"), _b(T.BTN_CANCEL, "m:growth")]]))
        elif action == "hsy":
            ctx.repos.settings.set("growth_hash", "1")
            ctx.repos.logs.add("growth_hash_on", uid)
            await show_hub(update, context, "✅ روشن شد (فقط برای عضویت‌های جدید).")
        else:
            raise ValueError(action)
    except (ValueError, IndexError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def _create_campaign(update, context, kind: str, name: str) -> None:
    ctx = ctx_of(context)
    ref = ctx.effective_channel_ref()
    if not ref:
        await show(update, T.CHANNEL_NOT_SET, _back("r:l"))
        return
    link_name = name[:LINK_NAME_MAX]
    try:
        link = await context.bot.create_chat_invite_link(chat_id=ref, name=link_name)
    except TelegramError:
        await show(update, "❌ ساخت لینک دعوت ممکن نشد. ربات باید در کانال <b>ادمین</b> باشد و حق <b>Invite Users</b> داشته باشد "
                           "(کانال ← Administrators ← ربات ← Invite Users را روشن کنید). 🧪 وضعیت دریافت رویداد را هم ببینید.", _back("r:l"))
        return
    try:
        cid = ctx.repos.growth.create_campaign(kind, name, link.invite_link, link_name)
    except ValueError:
        await show(update, f"❌ حداکثر {GrowthRepo.MAX_CAMPAIGNS} کمپین مجاز است؛ کمپین‌های قدیمی را ابطال و حذف کنید.", _back("r:l"))
        return
    ctx.repos.logs.add("campaign_growth_created", update.effective_user.id, f"id={cid} {kind}")
    await _card(update, context, cid, "✅ ساخته شد. لینک را در همان منبع منتشر کنید؛ نام کمپین روی لینک ذخیره شده است.")


async def _send_qr(update, context, cid: int) -> None:
    ctx = ctx_of(context)
    c = ctx.repos.growth.get_campaign(cid)
    if not c or not c["invite_link"] or c["status"] != "active":
        raise ValueError("campaign")
    png = make_qr_png(c["invite_link"])
    if png is None:
        await show(update, "⚠️ ساخت QR به بسته‌ی <code>segno</code> نیاز دارد: <code>pip install segno</code> و بعد ربات را دوباره اجرا کنید. "
                           f"فعلاً از لینک متنی استفاده کنید:\n\n<code>{esc(c['invite_link'])}</code>", _back(f"r:v:{cid}"))
        return
    try:
        await context.bot.send_photo(chat_id=ctx.settings.admin_user_id, photo=png,
                                     caption=f"🔳 QR کمپین «{c['name']}»\n{c['invite_link']}")
    except TelegramError:
        await show(update, "⚠️ ارسال تصویر ممکن نشد؛ از لینک متنی استفاده کنید.", _back(f"r:v:{cid}"))
        return
    await show(update, "✅ QR برایتان ارسال شد (ذخیره و در شبکه‌های اجتماعی استفاده کنید).", _back(f"r:v:{cid}"))


async def _revoke(update, context, cid: int, uid: int) -> None:
    ctx = ctx_of(context)
    c = ctx.repos.growth.get_campaign(cid)
    if not c or c["status"] != "active":
        raise ValueError("campaign")
    try:
        await context.bot.revoke_chat_invite_link(chat_id=ctx.effective_channel_ref(), invite_link=c["invite_link"])
    except TelegramError:
        await show(update, "❌ تلگرام ابطال لینک را نپذیرفت (ربات باید ادمین با حق Invite Users باشد).", _back(f"r:v:{cid}"))
        return
    ctx.repos.growth.mark_revoked(cid)
    ctx.repos.logs.add("campaign_growth_revoked", uid, f"id={cid}")
    await _card(update, context, cid, "🚫 لینک ابطال شد.")


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    kind = awaiting.split(":")[1]
    name = re.sub(r"\s+", " ", update.effective_message.text or "").strip()[:NAME_MAX]
    if not name:
        await show(update, "❌ نام معتبر بنویسید یا لغو کنید.", _back("r:l"))
        return
    context.user_data.pop("awaiting", None)
    await _create_campaign(update, context, kind, name)
