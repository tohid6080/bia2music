"""📝 متن‌های تبلیغ، 🗓 برنامه‌ی هفتگی و 🏁 نقاط عطف (w:). همه فقط متن می‌سازند؛ ربات چیزی را منتشر یا ارسال نمی‌کند."""
from __future__ import annotations

import html
import re

from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from musicbot import growth_plan, growth_texts as GT
from musicbot.handlers.common import admin_only, ctx_of, show
from musicbot.songs.textutils import ascii_digits
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b

esc = html.escape
TEXT_MAX = 4000


def _back(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_BACK, target)]])


def now_local(ctx):
    from musicbot.publishing.timeutil import utc_now

    return utc_now().astimezone(ctx.settings.tz)


# ---------- متن‌های تبلیغ ----------
async def show_texts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kinds = list(GT.KINDS.items())
    rows = [[_b(f"{icon} {name}", f"w:k:{key}") for key, (icon, name) in kinds[i:i + 2]] for i in range(0, len(kinds), 2)]
    rows.append([_b("📚 متن‌های ذخیره‌شده", "w:l")])
    rows.append([_b(T.BTN_BACK, "m:growth")])
    await show(update, "📝 <b>متن‌های تبلیغ</b>\n\nمتن آماده برای هر شبکه بسازید؛ قابل ویرایش و کپی است و لینک کانال (یا لینک اختصاصی کمپین) در آن درج می‌شود.\n"
                       "فقط از داده‌ی واقعی آرشیو استفاده می‌شود و ربات خودش چیزی منتشر یا ارسال نمی‌کند؛ شما کپی می‌کنید.",
               InlineKeyboardMarkup(rows))


async def _pick_target(update, context, kind: str) -> None:
    ctx = ctx_of(context)
    camps = [c for c in ctx.repos.growth.list_campaigns() if c["status"] == "active" and c["invite_link"]][:8]
    rows = [[_b("🔗 لینک عمومی کانال", f"w:g:{kind}:0")]]
    rows += [[_b(f"🎯 {c['name'][:28]}", f"w:g:{kind}:{c['id']}")] for c in camps]
    rows.append([_b(T.BTN_BACK, "w:tx")])
    await show(update, f"{GT.KINDS[kind][0]} <b>{GT.KINDS[kind][1]}</b>\n\nلینک کدام را در متن بگذارم؟\n"
                       "(لینک اختصاصی کمپین باعث می‌شود عضویت‌ها به همان منبع نسبت داده شود.)", InlineKeyboardMarkup(rows))


async def _show_text(update, context, tid: int, note: str = "") -> None:
    ctx = ctx_of(context)
    row = ctx.repos.gcontent.get_text(tid)
    if not row:
        await show(update, "❌ متن پیدا نشد.", K.back_to_menu())
        return
    icon, name = GT.KINDS[row["kind"]]
    extra = GT.NOTES.get(row["kind"], "")
    text = (f"{icon} <b>{name}</b> · نسخه {row['variant'] + 1}{' · ✏️ ویرایش‌شده' if row['edited'] else ''}\n"
            f"(روی متن بزنید تا کپی شود)\n\n<code>{esc(row['text'])}</code>" + (f"\n\n{extra}" if extra else "") + (f"\n\n{note}" if note else ""))
    kb = InlineKeyboardMarkup([
        [_b("✏️ ویرایش", f"w:e:{tid}"), _b("🔄 نسخه‌ی دیگر", f"w:n:{tid}")],
        [_b("🗑 حذف", f"w:d:{tid}")],
        [_b(T.BTN_BACK, "w:tx"), _b(T.BTN_MAIN_MENU, "m:main")],
    ])
    await show(update, text, kb)


# ---------- برنامه‌ی هفتگی ----------
async def get_or_build_plan(ctx, force: bool = False) -> tuple[str, str]:
    members = await ctx.channel.member_count(ctx.effective_channel_ref())
    if members is not None:
        ctx.repos.metrics.snapshot_members(members)
    now = now_local(ctx)
    week = growth_plan.week_key(now)
    cached = ctx.repos.gcontent.get_plan(week)
    if cached and not force:
        return week, cached["text"]
    text = growth_plan.build_plan(ctx, members, now)
    ctx.repos.gcontent.save_plan(week, text)
    return week, text


async def show_plan(update, context, force: bool = False) -> None:
    ctx = ctx_of(context)
    week, text = await get_or_build_plan(ctx, force)
    on = ctx.repos.settings.get("weekly_plan", "1") == "1"
    parts = growth_plan.split_message(text)
    kb = InlineKeyboardMarkup([
        [_b("🔄 تولید دوباره با آمار امروز", "w:pr")],
        [_b(f"🔔 ارسال خودکار هفتگی (شنبه‌ها): {'✅' if on else '⛔'}", "w:pw")],
        [_b("🧭 استراتژی محتوا", "w:st"), _b("🏁 نقاط عطف", "w:ms")],
        [_b(T.BTN_BACK, "m:growth")],
    ])
    for extra in parts[:-1]:
        await _reply(update, extra)
    await show(update, parts[-1], kb)


async def show_strategy(update, context) -> None:
    from musicbot import growth_strategy
    from musicbot.publishing.timeutil import utc_now

    ctx = ctx_of(context)
    members = await ctx.channel.member_count(ctx.effective_channel_ref())
    text = growth_strategy.build_strategy(ctx, members, utc_now())
    parts = growth_plan.split_message(text)
    for extra in parts[:-1]:
        await _reply(update, extra)
    await show(update, parts[-1], InlineKeyboardMarkup([[_b("🔄 به‌روزرسانی", "w:st")], [_b(T.BTN_BACK, "w:pl")]]))


async def _reply(update, text: str) -> None:
    from telegram.constants import ParseMode

    msg = update.callback_query.message if update.callback_query else update.effective_message
    await msg.reply_text(text, parse_mode=ParseMode.HTML)


# ---------- نقاط عطف ----------
async def show_milestones(update, context, note: str = "") -> None:
    ctx = ctx_of(context)
    members = await ctx.channel.member_count(ctx.effective_channel_ref())
    ms = ctx.repos.gcontent.milestones()
    stage = ctx.repos.gcontent.stage(members)
    lines = ["🏁 <b>نقاط عطف رشد</b>",
             f"👥 اعضای فعلی: {members if members is not None else 'نامشخص'}",
             "این‌ها فقط نقاط پیشنهادی‌اند، قابل تغییرند و رسیدن به آن‌ها فقط پیام و عمق پیشنهادها را عوض می‌کند؛ <b>هیچ انتشار خودکاری فعال نمی‌شود.</b>\n"]
    for m in ms:
        reached = members is not None and m["members"] <= members
        lines.append(f"{'✅' if reached else '⬜'} {m['members']} — {esc(m['title'])}")
    if stage["next"] and members is not None:
        lines.append(f"\n🎯 تا نقطه‌ی بعد ({stage['next']['members']}): {stage['next']['members'] - members} عضو")
    if note:
        lines.append(f"\n{note}")
    rows = [[_b(f"{m['members']} · {m['title'][:26]}", f"w:mv:{m['id']}")] for m in ms]
    rows.append([_b("➕ نقطه‌ی جدید", "w:mn")])
    rows.append([_b(T.BTN_BACK, "w:pl")])
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _milestone_card(update, context, mid: int, note: str = "") -> None:
    ctx = ctx_of(context)
    m = ctx.repos.gcontent.get_milestone(mid)
    if not m:
        await show(update, "❌ این نقطه پیدا نشد.", K.back_to_menu())
        return
    text = f"🏁 <b>{m['members']} عضو</b>\n{esc(m['title'])}\n📝 {esc(m['note'] or '—')}" + (f"\n\n{note}" if note else "")
    kb = InlineKeyboardMarkup([
        [_b("✏️ تعداد", f"w:me:{mid}:m"), _b("✏️ عنوان", f"w:me:{mid}:t")],
        [_b("✏️ یادداشت", f"w:me:{mid}:n"), _b("🗑 حذف", f"w:md:{mid}")],
        [_b(T.BTN_BACK, "w:ms")],
    ])
    await show(update, text, kb)


# ---------- کالبک ----------
@admin_only
async def content_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    parts = update.callback_query.data.split(":")
    action = parts[1]
    uid = update.effective_user.id
    gc = ctx.repos.gcontent
    context.user_data.pop("awaiting", None)
    try:
        if action == "st":
            await show_strategy(update, context)
        elif action == "tx":
            await show_texts_menu(update, context)
        elif action == "k":
            if parts[2] not in GT.KINDS:
                raise ValueError("kind")
            await _pick_target(update, context, parts[2])
        elif action == "g":
            kind, cid = parts[2], int(parts[3])
            try:
                text, variant = GT.generate(ctx, kind, cid, 0)
            except GT.NoData as exc:
                await show(update, f"⚠️ {esc(exc.message_fa)}", _back("w:tx"))
                return
            tid = gc.add_text(kind, variant, cid, text)
            ctx.repos.logs.add("growth_text_generated", uid, f"id={tid} {kind}")
            await _show_text(update, context, tid)
        elif action == "v":
            await _show_text(update, context, int(parts[2]))
        elif action == "l":
            items = gc.list_texts(10)
            if not items:
                await show(update, "هنوز متنی ذخیره نشده.", _back("w:tx"))
                return
            rows = [[_b(f"{GT.KINDS[t['kind']][0]} {GT.KINDS[t['kind']][1][:18]} · {t['text'][:20].strip()}…", f"w:v:{t['id']}")] for t in items]
            rows.append([_b(T.BTN_BACK, "w:tx")])
            await show(update, "📚 <b>متن‌های ذخیره‌شده</b>", InlineKeyboardMarkup(rows))
        elif action == "e":
            tid = int(parts[2])
            if not gc.get_text(tid):
                raise ValueError("text")
            context.user_data["awaiting"] = f"wtx:{tid}"
            await show(update, f"✏️ متن جدید را بفرستید (حداکثر {TEXT_MAX} حرف). متن فعلی را می‌توانید کپی و اصلاح کنید.", _back(f"w:v:{tid}"))
        elif action == "n":
            row = gc.get_text(int(parts[2]))
            if not row:
                raise ValueError("text")
            if row["edited"]:
                await show(update, "⚠️ این متن را ویرایش کرده‌اید؛ «نسخه‌ی دیگر» ویرایش‌هایتان را جایگزین می‌کند. ادامه می‌دهید؟",
                           InlineKeyboardMarkup([[_b("🔄 بله", f"w:ny:{row['id']}"), _b(T.BTN_CANCEL, f"w:v:{row['id']}")]]))
            else:
                await _next_variant(update, context, row)
        elif action == "ny":
            row = gc.get_text(int(parts[2]))
            if not row:
                raise ValueError("text")
            await _next_variant(update, context, row)
        elif action == "d":
            gc.delete_text(int(parts[2]))
            await show_texts_menu(update, context)
        elif action == "pl":
            await show_plan(update, context)
        elif action == "pr":
            await show_plan(update, context, force=True)
        elif action == "pw":
            new = "0" if ctx.repos.settings.get("weekly_plan", "1") == "1" else "1"
            ctx.repos.settings.set("weekly_plan", new)
            ctx.repos.logs.add("weekly_plan_toggled", uid, new)
            await show_plan(update, context)
        elif action == "ms":
            await show_milestones(update, context)
        elif action == "mv":
            await _milestone_card(update, context, int(parts[2]))
        elif action == "mn":
            context.user_data["awaiting"] = "wms:new"
            await show(update, "➕ نقطه‌ی جدید را به شکل «تعداد | عنوان | یادداشت (اختیاری)» بنویسید. مثال:\n<code>300 | بررسی اولین نتایج همکاری | همکاری‌ها را ارزیابی کنید</code>",
                       _back("w:ms"))
        elif action == "me":
            mid, f = int(parts[2]), parts[3]
            if f not in ("m", "t", "n") or not gc.get_milestone(mid):
                raise ValueError("field")
            context.user_data["awaiting"] = f"wms:{f}:{mid}"
            prompt = {"m": "تعداد اعضای این نقطه را فقط با عدد بنویسید:", "t": "عنوان جدید را بنویسید:", "n": "یادداشت جدید را بنویسید (برای حذف: -):"}[f]
            await show(update, prompt, _back(f"w:mv:{mid}"))
        elif action == "md":
            m = gc.get_milestone(int(parts[2]))
            if not m:
                raise ValueError("ms")
            await show(update, f"🗑 نقطه‌ی «{m['members']} · {esc(m['title'])}» حذف شود؟",
                       InlineKeyboardMarkup([[_b("🗑 بله", f"w:mdy:{m['id']}"), _b(T.BTN_CANCEL, f"w:mv:{m['id']}")]]))
        elif action == "mdy":
            ok = gc.delete_milestone(int(parts[2]))
            await show_milestones(update, context, "🗑 حذف شد." if ok else "⚠️ حداقل یک نقطه باید بماند.")
        else:
            raise ValueError(action)
    except (ValueError, IndexError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def _next_variant(update, context, row: dict) -> None:
    ctx = ctx_of(context)
    try:
        text, variant = GT.generate(ctx, row["kind"], row["campaign_id"], row["variant"] + 1)
    except GT.NoData as exc:
        await show(update, f"⚠️ {esc(exc.message_fa)}", _back("w:tx"))
        return
    ctx.repos.gcontent.regenerate_text(row["id"], variant, text)
    await _show_text(update, context, row["id"])


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    ctx = ctx_of(context)
    gc = ctx.repos.gcontent
    raw = (update.effective_message.text or "").strip()
    parts = awaiting.split(":")
    if parts[0] == "wtx":
        tid = int(parts[1])
        if not raw or len(raw) > TEXT_MAX or not gc.get_text(tid):
            await show(update, f"❌ متن باید ۱ تا {TEXT_MAX} حرف باشد.", _back(f"w:v:{tid}"))
            return
        gc.edit_text(tid, raw)
        context.user_data.pop("awaiting", None)
        await _show_text(update, context, tid, "✅ ذخیره شد.")
        return
    back = _back("w:ms")
    try:
        if parts[1] == "new":
            fields = [x.strip() for x in raw.split("|")]
            if len(fields) < 2:
                raise ValueError("قالب: تعداد | عنوان | یادداشت")
            members = _num(fields[0])
            title = re.sub(r"\s+", " ", fields[1])[:80]
            if not title:
                raise ValueError("عنوان خالی است")
            gc.add_milestone(members, title, (fields[2][:200] if len(fields) > 2 and fields[2] else None))
            context.user_data.pop("awaiting", None)
            await show_milestones(update, context, "✅ اضافه شد.")
            return
        f, mid = parts[1], int(parts[2])
        if f == "m":
            gc.update_milestone(mid, members=_num(raw))
        elif f == "t":
            title = re.sub(r"\s+", " ", raw)[:80]
            if not title:
                raise ValueError("عنوان خالی است")
            gc.update_milestone(mid, title=title)
        else:
            gc.update_milestone(mid, note=None if raw == "-" else raw[:200])
    except ValueError as exc:
        msg = str(exc) if str(exc) in ("قالب: تعداد | عنوان | یادداشت", "عنوان خالی است") else "ورودی نامعتبر است (عدد بین ۱ و ۱۰۰ میلیون، غیرتکراری؛ حداکثر ۱۲ نقطه)"
        await show(update, f"❌ {esc(msg)}", back)
        return
    except Exception:  # noqa: BLE001 - مثلاً تکراری‌بودن تعداد (UNIQUE)
        await show(update, "❌ این تعداد قبلاً ثبت شده یا نامعتبر است.", back)
        return
    context.user_data.pop("awaiting", None)
    await _milestone_card(update, context, mid, "✅ ذخیره شد.")


def _num(text: str) -> int:
    digits = ascii_digits(text).replace(",", "").replace("٬", "").strip()
    if not digits.isdigit():
        raise ValueError("members")
    return int(digits)
