"""متن گزارش‌های آمار (فقط خواندن؛ بدون هویت کاربران)."""
from __future__ import annotations

import html

from musicbot.publishing.timeutil import format_local, to_iso, utc_now

esc = html.escape
SPARK = "▁▂▃▄▅▆▇█"
METRIC_FA = {
    "start": "ورود به ربات", "search": "جست‌وجو", "song_view": "دیدن آهنگ", "like": "پسند", "suggest": "پیشنهاد",
    "request": "درخواست آهنگ", "download": "دریافت فایل", "premium_view": "دیدن اشتراک ویژه", "purchase": "خرید اشتراک",
}


def spark(values: list[int]) -> str:
    if not values or max(values) == 0:
        return "▁" * len(values)
    top = max(values)
    return "".join(SPARK[min(len(SPARK) - 1, int(v / top * (len(SPARK) - 1)))] for v in values)


def _signed(n) -> str:
    return "—" if n is None else (f"+{n}" if n > 0 else str(n))


def overview(ctx, members) -> str:
    r = ctx.repos
    st = r.songs.counts_by_status()
    users = r.users.stats(exclude=ctx.settings.admin_user_id)
    m7 = r.metrics.totals(7)
    lines = ["📊 <b>آمار و تحلیل</b>\n"]
    lines.append(f"👥 اعضای کانال: <b>{members if members is not None else 'نامشخص'}</b>"
                 f" (۷ روز: {_signed(r.metrics.members_change(7))} · ۳۰ روز: {_signed(r.metrics.members_change(30))})")
    lines.append(f"🎵 آرشیو: {sum(st.values())} آهنگ — منتشرشده {st.get('published', 0)} · آماده {st.get('ready', 0)} · پیش‌نویس {st.get('draft', 0)}")
    lines.append(f"👤 کاربران ربات: {users['total']} (فعال ۷ روز: {users['active_7d']})  ❤️ پسندها: {r.userdata.total_likes()}")
    if m7:
        lines.append("\n🤖 <b>تعامل در ربات (۷ روز اخیر)</b>")
        for k, label in METRIC_FA.items():
            if m7.get(k):
                lines.append(f"• {label}: {m7[k]}  {spark(r.metrics.series(k, 7))}")
    else:
        lines.append("\n🤖 هنوز تعاملی در ربات ثبت نشده (امکانات کاربران را روشن کنید).")
    top = r.userdata.top_liked(3)
    if top:
        lines.append("\n❤️ <b>محبوب‌ترین آهنگ‌ها (پسند در ربات)</b>")
        lines += [f"• {esc(' - '.join(x for x in (t['artist'], t['title']) if x))} ({t['c']})" for t in top]
    posts = r.metrics.top_posts(3)
    if posts:
        lines.append("\n⭐ <b>پست‌های پرواکنش کانال</b>")
        lines += [f"• {esc(' - '.join(x for x in (p['artist'], p['title']) if x) or 'پست ' + str(p['mid']))} ({p['reactions']} واکنش)" for p in posts]
    lines.append("\nℹ️ تلگرام تعداد بازدید پست‌ها را به ربات‌ها نمی‌دهد؛ برای بازدید از آمار خود کانال (Statistics) در تلگرام استفاده کنید. "
                 "واکنش‌ها از لحظه‌ی فعال‌بودن این نسخه شمارش می‌شود.")
    return "\n".join(lines)


def growth_chart(ctx) -> str:
    snaps = ctx.repos.metrics.snapshots(14)
    if len(snaps) < 2:
        return "📈 <b>رشد اعضا</b>\n\nهنوز داده‌ی کافی نیست. ربات هر روز یک عکس از تعداد اعضا می‌گیرد؛ چند روز بعد دوباره ببینید."
    lines = ["📈 <b>رشد اعضا (۱۴ روز اخیر)</b>", spark([x["members"] - min(y["members"] for y in snaps) for x in snaps]), ""]
    prev = None
    for sn in snaps:
        delta = "" if prev is None else f" ({_signed(sn['members'] - prev)})"
        lines.append(f"{sn['day'][5:]} → {sn['members']}{delta}")
        prev = sn["members"]
    return "\n".join(lines)


def growth_tips(ctx) -> list[str]:
    r = ctx.repos
    tips = []
    if not r.settings.user_features_enabled():
        tips.append("👥 امکانات کاربران خاموش است؛ روشن‌کردنش (⚙️ تنظیمات) به اعضا جست‌وجو و پیشنهاد می‌دهد و ماندگاری را بالا می‌برد.")
    if ctx.post_options().button_url is None and ctx.post_options().footer is None:
        tips.append("🔗 دکمه یا خط معرفی ربات زیر پست‌ها خاموش است؛ اعضا ربات را پیدا نمی‌کنند.")
    unclassified = r.songs.count("nolang")
    if unclassified:
        tips.append(f"🏷 {unclassified} آهنگ منتشرشده زبان ندارد؛ دسته‌بندی، مرور و پیشنهاد را بهتر می‌کند.")
    ch = r.metrics.members_change(7)
    if ch is not None and ch <= 0:
        tips.append("📉 در ۷ روز اخیر عضو جدیدی نیامده؛ یک همکاری/تبادل با کانال هم‌موضوع (🤝 همکاری‌ها) امتحان کنید.")
    new_req = r.userdata.count_new_requests()
    if new_req:
        tips.append(f"📨 {new_req} درخواست آهنگ بی‌پاسخ دارید؛ پاسخ به درخواست‌ها تعامل را بالا می‌برد.")
    if r.songs.count("ready"):
        tips.append(f"✅ {r.songs.count('ready')} آهنگ آماده‌ی انتشار دارید؛ ثبات در انتشار (مثلاً روزی یک آهنگ) رشد را پایدار می‌کند.")
    if r.settings.get("premium_enabled", "0") != "1" and r.users.stats(ctx.settings.admin_user_id)["total"] >= 20:
        tips.append("⭐ اشتراک ویژه خاموش است؛ برای درآمد از 📢 تبلیغات و درآمدزایی ← اشتراک ویژه روشنش کنید.")
    return tips or ["همه‌چیز مرتب است 👌 ادامه دهید."]


def promo_post_text(bot_username: str) -> str:
    return (f"🎧 ربات اختصاصی Bia2Music\n\n🔍 نام هر آهنگ یا خواننده را بنویسید و پیدا کنید\n💡 پیشنهاد آهنگ بر اساس سلیقه‌ی خودتان\n"
            f"🎧 پلی‌لیست‌های موضوعی\n🎤 آهنگ دلخواهتان را درخواست بدهید\n\n👇 همین حالا امتحان کنید:\n@{bot_username}")


def weekly(ctx, members) -> str:
    r = ctx.repos
    m7 = r.metrics.totals(7)
    week_ago = _week_ago()
    published = len([1 for l in r.logs.recent(1000) if l["action"] == "song_published" and l["created_at"] >= week_ago])
    lines = ["🗓 <b>گزارش هفتگی Bia2Music</b>\n",
             f"👥 اعضا: {members if members is not None else 'نامشخص'} ({_signed(r.metrics.members_change(7))} در هفته)",
             f"📤 آهنگ منتشرشده در هفته: {published}",
             f"🤖 ورود به ربات: {m7.get('start', 0)} · جست‌وجو: {m7.get('search', 0)} · پسند: {m7.get('like', 0)}"]
    if r.settings.get("premium_enabled", "0") == "1":
        rev = r.payments.revenue()
        lines.append(f"⭐ مشترکین فعال: {rev['active']} · درآمد ۳۰ روز: {rev['stars_30d']} استارز")
    top = r.userdata.top_liked(1)
    if top:
        lines.append(f"❤️ محبوب‌ترین: {esc(top[0]['title'] or '')} ({top[0]['c']})")
    tips = growth_tips(ctx)[:2]
    lines.append("\n💡 " + "\n💡 ".join(tips))
    return "\n".join(lines)


def _week_ago() -> str:
    from datetime import timedelta

    return to_iso(utc_now() - timedelta(days=7))
