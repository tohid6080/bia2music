"""مرحله ۱۰: اتصال رشد به محتوا. استراتژی هفتگیِ «پیشنهادی» که نقطه‌ی عطف فعلی، آمار واقعی کانال، علایق مخاطبان، آرشیو و پیشنهادهای رادار
را کنار هم می‌گذارد. فقط متن می‌سازد؛ چیزی منتشر یا ارسال نمی‌شود، هیچ عددی حدس زده نمی‌شود و هیچ ادعای قطعی درباره‌ی رشد نمی‌رود."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from musicbot import growth_reports as GR
from musicbot.growth_plan import POSTS
from musicbot.radar import suggest as S

esc = html.escape
DISCLAIMER = "⚠️ این‌ها فقط <b>پیشنهاد</b> است؛ هیچ پستی خودکار منتشر نمی‌شود و هیچ‌کدام رشد قطعی را تضمین نمی‌کند. فایل آهنگ را فقط با مجوز تهیه کنید."
FOCUS = {
    0: "آزمایش و ثبات: چند سبک را امتحان کنید و ببینید کدام واکنش بهتری می‌گیرد.",
    1: "شناخت سلیقه: علایق و پسندهای مخاطبان را جمع کنید و محتوا را به آن نزدیک‌تر کنید.",
    2: "توسعه و تنوع: بر پایه‌ی سلیقه‌ی ثابت، تنوع سبک/حال‌وهوا را بالا ببرید.",
    3: "تحلیل جدی‌تر: آزمایش‌های زمان و موضوع را مقایسه و ثبت کنید.",
    4: "بهینه‌سازی: فقط بر اساس نتیجه‌ی آزمایش‌های ثبت‌شده تصمیم بگیرید.",
}


def _lang_pref(ctx, agg) -> str | None:
    langs = agg.get("language") or {}
    return max(langs, key=langs.get) if langs else None


def pick_radar(ctx, now: datetime, pref_lang: str | None, n: int = 3) -> tuple[list[S.Item], str]:
    """پیشنهادهای رادار که با علاقه‌ی ثبت‌شده سازگارند (زبان فارسی ← ایرانی؛ سایر زبان‌ها ← خارجی). بدون علاقه: مخلوط."""
    items = S.discoverable(S.build_items(ctx, sync=False))
    items = S.apply_filters(items, S.load_filters(ctx), now)
    ranked = S.group_items("top", items, now)
    if pref_lang == "fa":
        sel = [i for i in ranked if i.kind == "iran"]
        why = "علاقه‌ی ثبت‌شده‌ی مخاطبان: فارسی"
    elif pref_lang:
        sel = [i for i in ranked if i.kind == "foreign"]
        why = "علاقه‌ی ثبت‌شده‌ی مخاطبان: غیرفارسی"
    else:
        sel, why = ranked, "علایق مخاطبان هنوز ثبت نشده؛ مخلوط"
    return (sel or ranked)[:n], why


def build_strategy(ctx, members, now_utc: datetime) -> str:
    r = ctx.repos
    stage = r.gcontent.stage(members)
    tier, cur, nxt = stage["tier"], stage["current"], stage["next"]
    st = r.songs.counts_by_status()
    ready = st.get("ready", 0)
    lo, hi = POSTS[tier]
    agg = r.userdata.aggregate()
    consented = r.users.stats(exclude=ctx.settings.admin_user_id)["consented"]
    events = GR.events_available(ctx)
    t7 = r.growth.totals(7) if events else None
    ch7 = r.metrics.members_change(7)

    lines = ["🧭 <b>استراتژی محتوا و رشد (پیشنهادی)</b>\n"]
    lines.append(f"📌 اعضا: {members if members is not None else 'نامشخص'}"
                 + (f" · مرحله: «{esc(cur['title'])}»" if cur else " · هنوز به اولین نقطه‌ی عطف نرسیده‌اید")
                 + (f" · تا نقطه‌ی بعدی ({nxt['members']}): {nxt['members'] - members} عضو" if nxt and members is not None else ""))
    lines.append(f"🎯 تمرکز این مرحله: {FOCUS[tier]}")
    if ch7 is not None:
        lines.append(f"📈 تغییر اعضا در ۷ روز: {ch7:+d}")
    else:
        lines.append("⚪ روند اعضا در دسترس نیست (چند روز عکس لازم است).")

    # محتوا ← از رادار
    lines.append("\n🔥 <b>چه چیزی از رادار بررسی کنیم؟</b>")
    picks, why = pick_radar(ctx, now_utc, _lang_pref(ctx, agg))
    if picks:
        lines.append(f"({why}" + (f"؛ نمونه‌ی کوچک: {consented} کاربر" if 0 < consented < 20 else "") + ")")
        for i in picks:
            lines.append(f"• <b>{esc(i.title)}</b>" + (f" — {esc(i.artist)}" if i.artist else "") + f" · امتیاز ربات {i.score:g}")
        lines.append("برای هرکدام از «🔥 رادار» کارت را باز کنید: ✅ پیش‌نویس · 📝 کپشن. (مجوز فایل نامشخص است تا خودتان ثبت کنید.)")
    else:
        lines.append("• فعلاً پیشنهاد رادار ندارم (منبعی فعال/به‌روز نیست یا همه رد/در آرشیو هستند).")

    # خط لوله‌ی محتوا
    lines.append("\n📦 <b>آمادگی برای این هفته</b>")
    lines.append(f"• هدف: {lo} تا {hi} پست؛ «آماده‌ی انتشار»: {ready}")
    if ready < lo:
        lines.append(f"• کمبود حدود {lo - ready} آهنگ آماده. ابتدا موارد زیر را کامل کنید:")
    drafted = r.radar.suggestions_by_status("drafted", 50)
    nofile = []
    for g in drafted:
        s = r.songs.get(g["song_id"]) if g.get("song_id") else None
        if s and not s.get("telegram_file_id"):
            nofile.append(g)
    if nofile:
        lines.append(f"• {len(nofile)} آهنگ در پیش‌نویس رادار فایل ندارد: " + "، ".join(esc(g["title"]) for g in nofile[:3])
                     + " — فایل را (با مجوز) برای ربات بفرستید تا وصل شود.")
    saved = r.radar.suggestions_by_status("saved", 50)
    if saved:
        lines.append(f"• {len(saved)} پیشنهاد ذخیره‌شده منتظر تصمیم شماست.")
    if ready >= lo and not nofile and not saved:
        lines.append("• خط لوله‌ی محتوا برای این هفته کافی است.")

    # اتصال رشد ← محتوا
    lines.append("\n🔗 <b>اتصال رشد به محتوا</b>")
    if t7 is not None and t7["joins"] + t7["leaves"] >= 3 and t7["leaves"] > t7["joins"]:
        lines.append("• خروج‌ها از ورودها بیشتر بوده: پست‌های پرتکرار را کم و کیفیت و تنوع را بیشتر کنید.")
    elif t7 is not None and t7["joins"] > t7["leaves"]:
        lines.append("• ورود از خروج بیشتر بوده: همین ریتم و سبک‌ها را حفظ و فقط یک آزمایش جدید اضافه کنید.")
    else:
        lines.append("• داده‌ی ورود/خروج کافی نیست؛ بدون رویداد عضویت نمی‌توان اثر هر پست را به عضو جدید نسبت داد.")
    done = [c for c in r.campaigns.list("collab", 50) + r.campaigns.list("ad", 50)
            if c["status"] == "done" and c["members_start"] is not None and c["members_end"] is not None]
    done.sort(key=lambda c: c["members_end"] - c["members_start"], reverse=True)
    if done:
        c = done[0]
        lines.append(f"• بهترین کمپین قبلی: «{esc(c['title'])}» ({c['members_end'] - c['members_start']:+d} عضو؛ علت قطعی نیست). "
                     "برای کمپین بعدی یک پست شاخص از محتوای پرپسند آماده کنید.")
    else:
        lines.append("• کمپینی ثبت نشده؛ از 📈 رشد یک لینک اختصاصی بسازید تا اثر محتوا و منبع جدا سنجیده شود.")
    lines.append("• هر پست را با یک تغییر (سبک یا زمان) آزمایش کنید و واکنش‌ها را در 📊 آمار مقایسه کنید.")
    lines.append("\n" + DISCLAIMER)
    return "\n".join(lines)
