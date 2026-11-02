"""برنامه‌ی هفتگی پیشنهادی رشد. قانون‌محور (نه AI) و مبتنی بر آمار واقعی؛ هر بخش پایه‌ی داده‌اش را می‌گوید، ساعت‌ها
«آزمایش» هستند نه «بهترین»، و هیچ ادعایی درباره‌ی افزایش قطعی عضو نمی‌شود. فقط متن می‌سازد؛ چیزی منتشر یا ارسال نمی‌کند."""
from __future__ import annotations

import html
from datetime import datetime

from musicbot import growth_reports as GR
from musicbot.recommend import audience_rank

esc = html.escape
DAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]    # با weekday() پایتون (دوشنبه=۰)
WINDOWS = ["12:00–14:00", "18:00–20:00", "20:00–22:00", "22:00–24:00"]
DAY_ORDER = [5, 6, 0, 1, 2, 3, 4]                                              # هفته با شنبه شروع می‌شود
POSTS = {0: (3, 4), 1: (4, 5), 2: (5, 6), 3: (5, 7), 4: (5, 7)}
DISCLAIMER = "⚠️ همه‌ی موارد بالا <b>پیشنهاد آزمایشی</b> است و هیچ تضمینی برای افزایش اعضا ندارد؛ اعداد کم (مثلاً ۲۲ عضو) نتیجه‌ی قابل‌اعتماد نمی‌دهند."


def week_key(now_local: datetime) -> str:
    y, w, _ = now_local.isocalendar()
    return f"{y}-W{w:02d}"


def _names(ctx, table: str) -> dict:
    return {str(i["key"]): i["name_fa"] for i in ctx.repos.categories.list(table)}


def _top(agg: dict[str, int], names: dict, n: int = 2) -> list[str]:
    return [names[k] for k, _ in sorted(agg.items(), key=lambda x: -x[1])[:n] if k in names]


def experiment_slots(now_local: datetime) -> list[str]:
    """سه آزمایش زمانی برای این هفته؛ چرخشی و قطعی (بر اساس شماره‌ی هفته)، نه «بهترین زمان»."""
    w = now_local.isocalendar()[1]
    return [f"{DAYS[DAY_ORDER[(w + i * 2) % 7]]} · {WINDOWS[(w + i) % len(WINDOWS)]}" for i in range(3)]


def build_plan(ctx, members, now_local: datetime) -> str:
    r = ctx.repos
    stage = r.gcontent.stage(members)
    tier = stage["tier"]
    st = r.songs.counts_by_status()
    ready, published = st.get("ready", 0), st.get("published", 0)
    ud = r.userdata
    agg = ud.aggregate()
    users = r.users.stats(exclude=ctx.settings.admin_user_id)
    consented = users["consented"]
    events = GR.events_available(ctx)
    t7 = r.growth.totals(7) if events else None
    ch7 = r.metrics.members_change(7)
    top_liked = ud.top_liked(3)

    g_names, m_names, l_names = _names(ctx, "genres"), _names(ctx, "moods"), _names(ctx, "languages")
    pub_lang = _top({str(k): v for k, v in r.songs.counts_by("l", published_only=True).items()}, l_names, 3)
    pub_genre = _top({str(k): v for k, v in r.songs.counts_by("g", published_only=True).items()}, g_names, 3)

    lines = [f"🗓 <b>برنامه‌ی پیشنهادی رشد · هفته‌ی {week_key(now_local)}</b>\n"]

    # ۱) وضعیت و پایه‌ی داده
    cur = stage["current"]
    nxt = stage["next"]
    lines.append(f"📌 <b>وضعیت</b>: {members if members is not None else 'اعضا نامشخص'} عضو"
                 + (f" · مرحله: «{esc(cur['title'])}»" if cur else " · هنوز به اولین نقطه‌ی عطف نرسیده‌اید")
                 + (f" · نقطه‌ی بعدی: {nxt['members']} ({esc(nxt['title'])})" if nxt else ""))
    if cur and cur.get("note"):
        lines.append(f"💡 {esc(cur['note'])}")
    have = [x for ok, x in ((published > 0, f"آرشیو منتشرشده ({published})"), (consented > 0, f"علایق {consented} کاربر"),
                            (bool(top_liked), "پسندها"), (events, "ورود/خروج"), (ch7 is not None, "روند اعضا"), (bool(r.metrics.top_posts(1)), "واکنش پست‌ها")) if ok]
    miss = [x for ok, x in ((published > 0, "آرشیو منتشرشده"), (consented > 0, "علایق کاربران"), (bool(top_liked), "پسندها"),
                            (events, "ورود/خروج اعضا"), (ch7 is not None, "روند اعضا (چند روز عکس لازم است)")) if not ok]
    lines.append("📊 داده‌ی استفاده‌شده: " + ("، ".join(have) if have else "هیچ (هنوز داده‌ای نیست)"))
    if miss:
        lines.append("⚪ در دسترس نیست: " + "، ".join(miss))

    # ۲) چه موسیقی‌ای
    lines.append("\n🎵 <b>چه موسیقی‌هایی منتشر شود؟</b>")
    interest = [f"{label}: {'، '.join(v)}" for label, v in (("سبک", _top(agg["genre"], g_names)), ("حال‌وهوا", _top(agg["mood"], m_names)),
                                                           ("زبان", _top(agg["language"], l_names))) if v]
    if interest:
        small = " (نمونه‌ی کوچک؛ با احتیاط)" if consented < 20 else ""
        lines.append(f"• علایق ثبت‌شده‌ی مخاطبان (بر پایه‌ی {consented} کاربر){small}: " + " · ".join(interest))
        lines.append("• بیشتر از همین‌ها منتشر کنید، ولی هر هفته یک آهنگ از خارج این علایق برای آزمایش بگذارید.")
    else:
        lines.append("• علایق مخاطبان هنوز ثبت نشده؛ این هفته ۲–۳ سبک متفاوت منتشر کنید و واکنش‌ها را مقایسه کنید.")
    if pub_lang or pub_genre:
        lines.append("• ترکیب فعلی آرشیو منتشرشده: " + " · ".join(x for x in (("زبان: " + "، ".join(pub_lang)) if pub_lang else "", ("سبک: " + "، ".join(pub_genre)) if pub_genre else "") if x))
    if top_liked:
        lines.append("• پرپسندترین‌ها: " + "، ".join(esc(t["title"] or "؟") for t in top_liked) + " — از همین سلیقه بیشتر بگذارید.")
    ranked = [s for s, sc in audience_rank(r, r.songs.all_with_status("ready", 100)) if sc > 0][:3]
    if ranked:
        lines.append("• از آماده‌های شما نزدیک‌ترین به علایق: " + "، ".join(esc(s["title"] or "؟") for s in ranked))
    if tier >= 2:
        lines.append("• تنوع: در هفته حداقل ۲ سبک و ۲ حال‌وهوا را پوشش دهید.")

    # ۳) تعداد پست
    lo, hi = POSTS[tier]
    lines.append("\n🗓 <b>چند پست در هفته؟</b>")
    lines.append(f"• برای این مرحله حدود {lo} تا {hi} پست (پیشنهاد آزمایشی؛ ثبات از تعداد مهم‌تر است).")
    if ready < lo:
        lines.append(f"• فقط {ready} آهنگ «آماده‌ی انتشار» دارید؛ برای رسیدن به این تعداد آهنگ بیشتری ثبت کنید (📚 آرشیو، 📥 درون‌ریزی).")
    if t7 is not None and t7["joins"] + t7["leaves"] >= 3 and t7["leaves"] > t7["joins"]:
        lines.append("• در ۷ روز اخیر خروج بیشتر از ورود بوده؛ به‌جای افزایش تعداد، کیفیت و ثبات را بالا ببرید.")

    # ۴) آزمایش زمان
    lines.append("\n⏰ <b>آزمایش روز و ساعت انتشار (نه «بهترین زمان»)</b>")
    lines += [f"• آزمایش {i}: {s}" for i, s in enumerate(experiment_slots(now_local), 1)]
    lines.append("• ارزیابی: واکنش‌های پست (در 📊 آمار) و عضو جدید همان روز (اگر رویداد عضویت دارید). بازدید پست در دسترس ربات نیست. "
                 "هر زمان را حداقل ۳ هفته آزمایش کنید.")

    # ۵) نظرسنجی
    lines.append("\n🗳 <b>موضوع نظرسنجی (دستی در کانال بسازید)</b>")
    g_opts = _top(agg["genre"], g_names, 4) or pub_genre or list(g_names.values())[:4]
    m_opts = _top(agg["mood"], m_names, 4) or list(m_names.values())[:4]
    lines.append(f"• «کدام سبک را بیشتر می‌خواهید؟» — {'، '.join(esc(x) for x in g_opts[:4])}")
    lines.append(f"• «حال‌وهوای آهنگ‌های هفته‌ی بعد؟» — {'، '.join(esc(x) for x in m_opts[:4])}")
    if top_liked:
        lines.append("• «بهترین آهنگ این هفته؟» — " + "، ".join(esc(t['title'] or '؟') for t in top_liked))
    if tier >= 2:
        lines.append(f"• «کدام زبان را بیشتر می‌خواهید؟» — {'، '.join(esc(x) for x in list(l_names.values())[:4])}")

    # ۶) همکاری
    lines.append("\n🤝 <b>کانال‌های همکاری برای بررسی</b>")
    lines.append("• معیار: هم‌موضوع (موسیقی)، اندازه‌ی نزدیک به کانال شما، تعامل واقعی، بدون عضو خریداری‌شده. (نام کانال خاصی را حدس نمی‌زنم.)")
    done = [c for c in r.campaigns.list("collab", 50) + r.campaigns.list("ad", 50)
            if c["status"] == "done" and c["members_start"] is not None and c["members_end"] is not None]
    done.sort(key=lambda c: c["members_end"] - c["members_start"], reverse=True)
    if done:
        lines += [f"• نتیجه‌ی قبلی: «{esc(c['title'])}» {c['members_end'] - c['members_start']:+d} عضو" for c in done[:2]]
        lines.append("• توجه: افزایش اعضا همیشه معلول همان همکاری نیست؛ با لینک اختصاصی کمپین بسنجید.")
    else:
        lines.append("• هنوز همکاری ثبت‌شده‌ای نیست؛ در 📢 تبلیغات ← 🤝 ثبت کنید و لینک اختصاصی بسازید تا نتیجه سنجیده شود.")

    # ۷) اشتراک‌پذیر
    lines.append("\n📣 <b>محتوای اشتراک‌پذیرتر</b>")
    n_pl = len(r.playlists.list(public_only=True))
    lines.append(f"• پلی‌لیست‌های موضوعی (فعلاً {n_pl} پلی‌لیست عمومی)" + (" — ابتدا چند پلی‌لیست بسازید." if n_pl == 0 else " را معرفی کنید."))
    lines.append("• پست‌های کوتاه حال‌وهوایی («مناسب رانندگی»، «آرامش‌بخش») و جمع‌بندی هفتگی ۳ آهنگ پرپسند.")
    lines.append("• یک متن/QR با لینک اختصاصی کمپین برای هر شبکه (📈 رشد ← 📝 متن‌های تبلیغ) بسازید تا منبع عضویت مشخص شود.")
    if tier >= 3:
        lines.append("• نتیجه‌ی آزمایش‌ها (روز/ساعت/واکنش) را در یک جدول ساده ثبت و هر ماه مقایسه کنید.")

    lines.append("\n" + DISCLAIMER)
    return "\n".join(lines)


def split_message(text: str, limit: int = 3900) -> list[str]:
    """تقسیم متن بلند در مرز خط (سقف پیام تلگرام ۴۰۹۶ حرف)."""
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            parts.append(cur)
            cur = ""
        cur += (line + "\n")
    if cur.strip():
        parts.append(cur.rstrip())
    return parts
