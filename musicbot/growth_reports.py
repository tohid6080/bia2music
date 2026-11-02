"""گزارش رشد. اصل صداقت: کلیک در دسترس نیست؛ عضویت فقط از رویداد تلگرام شمرده می‌شود و اگر رویدادی نیامده باشد
«در دسترس نیست» نوشته می‌شود (نه صفر). روزها به وقت UTC ذخیره می‌شوند."""
from __future__ import annotations

import html

from musicbot.db.repositories import GrowthRepo
from musicbot.publishing.timeutil import format_local, from_iso
from musicbot.reports import _signed, spark

esc = html.escape
NA = "در دسترس نیست"


def events_meta(ctx) -> dict:
    st = ctx.repos.settings
    return {"total": int(st.get("ce_total", "0")), "with_link": int(st.get("ce_with_link", "0")), "last_at": st.get("ce_last_at")}


def events_available(ctx) -> bool:
    return events_meta(ctx)["total"] > 0


def kind_label(kind: str) -> str:
    icon, name = GrowthRepo.KINDS.get(kind, ("🔗", kind))
    return f"{icon} {name}"


def capability_text(ctx, status) -> str:
    m = events_meta(ctx)
    ok = "✅"
    no = "❌"
    lines = ["🧪 <b>وضعیت دریافت رویداد عضویت</b>\n"]
    if status is None or not status.ok:
        lines.append(f"{no} کانال در دسترس نیست (⚙️ تنظیمات ← 📡 وضعیت اتصال).")
    else:
        lines.append(f"{ok if status.bot_is_admin else no} ربات ادمین کانال است")
        lines.append(f"{ok if status.can_invite else no} حق «Invite Users» (برای ساخت لینک دعوت)")
    last = format_local(m["last_at"], ctx.settings.tz) if m["last_at"] else "—"
    lines.append(f"\n📥 رویدادهای عضویت دریافت‌شده: <b>{m['total']}</b> (آخرین: {last})")
    lines.append(f"🔗 رویدادهایی که اطلاعات لینک دعوت داشتند: <b>{m['with_link']}</b>")
    if m["total"] == 0:
        lines.append("\n⚠️ <b>هنوز هیچ رویداد عضویتی نیامده.</b> یعنی یا کسی وارد/خارج نشده، یا تلگرام برای این کانال رویداد نمی‌فرستد. "
                     "تا آن موقع، آمار عضویت هر کمپین <b>در دسترس نیست</b> و فقط شمارنده‌ی کل اعضا کار می‌کند.")
        lines.append("\n<b>آزمون:</b> یک کمپین آزمایشی بسازید، با یک حساب دوم از لینکش وارد کانال شوید و بعد خارج شوید؛ سپس همین صفحه را دوباره باز کنید.")
    elif m["with_link"] == 0:
        lines.append("\n⚠️ رویداد می‌آید ولی هیچ‌کدام اطلاعات لینک نداشته؛ پس <b>منبع عضویت قابل شناسایی نیست</b> و گزارش کمپین‌ها در دسترس نیست.")
    else:
        lines.append("\n✅ رویداد و اطلاعات لینک دریافت می‌شود؛ عضویت هر کمپین قابل شمارش است.")
    lines.append("\nℹ️ تعداد <b>کلیک</b> لینک را تلگرام به ربات‌ها نمی‌دهد؛ فقط عضویت‌های تأییدشده شمرده می‌شود. کلیک و عضویت یکی نیستند.")
    return "\n".join(lines)


def hub_text(ctx, members) -> str:
    r = ctx.repos
    m = events_meta(ctx)
    lines = ["📈 <b>رشد و توسعه کانال</b>\n",
             f"👥 اعضای فعلی: <b>{members if members is not None else 'نامشخص'}</b>",
             f"📊 تغییر امروز: {_signed(r.metrics.members_change(1))} · هفته: {_signed(r.metrics.members_change(7))} · ماه: {_signed(r.metrics.members_change(30))}"]
    if events_available(ctx):
        t = r.growth.totals(1)
        lines.append(f"🔄 امروز (UTC): +{t['joins']} ورود · −{t['leaves']} خروج")
    else:
        lines.append(f"🔄 ورود/خروج: {NA} (رویداد عضویت دریافت نشده)")
    active = [c for c in r.growth.list_campaigns() if c["status"] == "active"]
    lines.append(f"🎯 کمپین فعال: {len(active)}")
    lines.append("\nهدف: فقط جذب مخاطب واقعی و علاقه‌مند؛ هیچ ابزاری برای عضو فیک، عضویت اجباری یا پیام انبوه وجود ندارد.")
    return "\n".join(lines)


def report_text(ctx, members) -> str:
    r = ctx.repos
    g = r.growth
    avail = events_available(ctx)
    lines = ["📊 <b>گزارش رشد</b>\n",
             f"👥 اعضای فعلی: <b>{members if members is not None else 'نامشخص'}</b>"]
    for label, days in (("امروز", 1), ("۷ روز", 7), ("۳۰ روز", 30)):
        ch = r.metrics.members_change(days)
        if avail:
            t = g.totals(days)
            ev = f" · ورود {t['joins']} / خروج {t['leaves']}"
        else:
            ev = f" · ورود/خروج: {NA}"
        lines.append(f"• {label}: رشد خالص {_signed(ch)}{ev}")
    lines.append("\nℹ️ «رشد خالص» از تغییر شمارنده‌ی اعضا محاسبه می‌شود؛ ممکن است با ورود−خروج رویدادها کمی فرق کند (تأخیر یا رویداد از دست‌رفته).")
    camps = {c["id"]: c for c in g.list_campaigns()}
    if not avail:
        lines.append(f"\n🎯 عضویت کمپین‌ها: {NA}. (🧪 وضعیت دریافت رویداد را ببینید.)")
    else:
        per = g.per_campaign(30)
        per_all = g.per_campaign(None)
        hashing = ctx.repos.settings.get("growth_hash", "0") == "1"
        rows = []
        for cid, v in sorted(per.items(), key=lambda x: -x[1]["joins"]):
            if cid == 0:
                continue
            c = camps.get(cid)
            if c:
                rows.append((v["joins"], f"• {kind_label(c['kind'])} «{esc(c['name'])}»: {v['joins']} عضو جدید (۳۰ روز) · کل {per_all.get(cid, {}).get('joins', 0)}"
                                         + (f" · خروج {v['leaves']}" if hashing else "")))
        lines.append("\n🎯 <b>کمپین‌ها (فقط عضویت‌های تأییدشده، ۳۰ روز)</b>")
        lines += [x[1] for x in rows] or ["هنوز عضوی از کمپین‌ها نیامده."]
        unk = per.get(0, {"joins": 0})["joins"]
        lines.append(f"• 🌐 منبع نامشخص/ارگانیک (بدون لینک): {unk}")
        best = max(((v["joins"], cid) for cid, v in per.items() if cid in camps and v["joins"] > 0), default=None)
        if best:
            c = camps[best[1]]
            lines.append(f"\n🏆 <b>بهترین کمپین:</b> {kind_label(c['kind'])} «{esc(c['name'])}» با {best[0]} عضو")
        by_kind: dict[str, int] = {}
        for cid, v in per.items():
            if cid in camps:
                by_kind[camps[cid]["kind"]] = by_kind.get(camps[cid]["kind"], 0) + v["joins"]
        if by_kind:
            top = max(by_kind.items(), key=lambda x: x[1])
            if top[1] > 0:
                lines.append(f"🥇 منبعی که بیشترین عضو آورده: {kind_label(top[0])} ({top[1]})")
        if not hashing:
            lines.append("\nℹ️ خروج‌ها به‌تفکیک کمپین ثبت نمی‌شود (برای حفظ حریم خصوصی). در «رشد و توسعه ← 🔐» قابل روشن‌کردن است.")
    lines.append("\n⚠️ <b>کلیک لینک در دسترس نیست</b> (تلگرام نمی‌دهد)؛ اعداد بالا فقط عضویت‌های واقعیِ شمرده‌شده است. روزها به وقت UTC.")
    return "\n".join(lines)


def chart_text(ctx) -> str:
    r = ctx.repos
    snaps = r.metrics.snapshots(30)
    lines = ["📈 <b>نمودار رشد اعضا</b>\n"]
    if len(snaps) < 2:
        lines.append("هنوز داده‌ی کافی نیست. ربات هر روز یک عکس از تعداد اعضا می‌گیرد؛ چند روز بعد دوباره ببینید.")
    else:
        base = min(x["members"] for x in snaps)
        lines.append(f"<code>{spark([x['members'] - base for x in snaps])}</code>")
        lines.append(f"{snaps[0]['day'][5:]} ← {snaps[-1]['day'][5:]} · از {snaps[0]['members']} به {snaps[-1]['members']} ({_signed(snaps[-1]['members'] - snaps[0]['members'])})")
    if events_available(ctx):
        d = r.growth.daily(7)
        lines.append("\n🔄 <b>ورود/خروج روزانه (۷ روز، UTC)</b>")
        lines.append(f"ورود <code>{spark([x['joins'] for x in d])}</code>\nخروج <code>{spark([x['leaves'] for x in d])}</code>")
        lines += [f"{x['day'][5:]}  +{x['joins']}  −{x['leaves']}" for x in d]
    else:
        lines.append(f"\n🔄 ورود/خروج روزانه: {NA} (رویداد عضویت دریافت نشده).")
    return "\n".join(lines)
