"""🔥 رادار موسیقی‌های ترند (x:): مدیریت منابع، دریافت با کش، نمودارها، رتبه‌ی ترکیبی شفاف، ثبت دستی.

اصول: هیچ منبعی بدون تأیید صریح مدیر فعال نمی‌شود؛ منبع بدون API رسمی فقط لینک است؛ فقط متادیتا و لینک رسمی نمایش داده می‌شود
(هیچ فایلی دانلود یا منتشر نمی‌شود)؛ هیچ رتبه/تاریخ/آمار حدس زده نمی‌شود؛ زمان آخرین به‌روزرسانی همیشه نمایش داده می‌شود."""
from __future__ import annotations

import html
import math
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from musicbot.handlers.common import admin_only, ctx_of, show
from musicbot.publishing.timeutil import format_local, from_iso, utc_now
from musicbot.radar import report as report_mod
from musicbot.radar import scoring
from musicbot.radar import suggest as S
from musicbot.radar.service import ERR_FA, STALE_FACTOR, validate_regions
from musicbot.radar.sources import BY_ID, SOURCES
from musicbot.songs.textutils import ascii_digits
from musicbot.ui import keyboards as K
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b

esc = html.escape
PAGE = 8
KIND_FA = {"iran": "🇮🇷 ایرانی", "foreign": "🌍 خارجی"}
ICON = {"link": "🔗", "needs_key": "🔑", "off": "⚪", "never": "🟡", "ok": "🟢", "partial": "🟠", "error": "🔴"}
STATUS_FA = {"link": "فقط لینک", "needs_key": "کلید API تنظیم نشده", "off": "خاموش (نیازمند تأیید شما)", "never": "فعال؛ هنوز دریافتی نشده",
             "ok": "سالم", "partial": "بخشی از مناطق خطا داد", "error": "آخرین دریافت ناموفق بود"}


def _back(target: str = "m:radar") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_BACK, target)]])


def _a(url, label: str) -> str:
    return f'<a href="{esc(url, quote=True)}">{esc(label)}</a>' if url else ""


def _delta(d) -> str:
    if d is None:
        return "تغییر: نامشخص"
    return f"▲{d}" if d > 0 else (f"▼{-d}" if d < 0 else "＝")


def _ago(ctx, iso) -> str:
    if not iso:
        return "هنوز نه"
    return format_local(iso, ctx.settings.tz)


def last_update(ctx) -> str:
    oks = [ctx.repos.radar.state(s.id)["last_ok_at"] for s in SOURCES if s.is_api]
    oks = [x for x in oks if x]
    return _ago(ctx, max(oks)) if oks else "هنوز داده‌ای دریافت نشده"


# ---------- هاب ----------
async def show_hub(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    ctx = ctx_of(context)
    svc = ctx.radar_service()
    api = [s for s in SOURCES if s.is_api]
    enabled = [s for s in api if ctx.repos.radar.state(s.id)["enabled"]]
    manual = len(ctx.repos.radar.manual_list(500))
    lines = [
        "🔥 <b>رادار موسیقی‌های ترند</b>\n",
        f"🌐 منابع API فعال: {len(enabled)} از {len(api)} · منابع فقط‌لینک: {len(SOURCES) - len(api)}",
        f"🕒 آخرین به‌روزرسانی داده‌ها: {last_update(ctx)}",
        f"✍️ ثبت دستی: {manual} آهنگ",
        "\nهیچ منبعی بدون تأیید صریح شما فعال نمی‌شود. فقط متادیتا و لینک رسمی نمایش داده می‌شود؛ هیچ فایلی دانلود یا منتشر نمی‌شود. "
        "اگر منبعی داده ندهد، این صفحه آن را «در دسترس نیست» می‌نویسد و چیزی حدس نمی‌زند.",
    ]
    if not enabled:
        lines.append("\n💡 شروع: «🌐 منابع» را بزنید، منبعی را بخوانید و تأیید کنید. (منابع کلیددار به کلید رایگان در `.env` نیاز دارند.)")
    if note:
        lines.append(f"\n{note}")
    kb = InlineKeyboardMarkup([
        [_b("🔥 ترندهای امروز", "x:top:0")],
        [_b("🇮🇷 ایرانی", "x:gl:ir:0"), _b("🌍 خارجی", "x:gl:fo:0")],
        [_b("🆕 تازه‌ها", "x:gl:new:0"), _b("📈 سریع‌ترین رشد", "x:gl:grow:0")],
        [_b("🎤 خوانندگان پرطرفدار", "x:art"), _b("🎧 بر اساس سبک", "x:gs")],
        [_b("⭐ پیشنهادهای من", "x:gl:saved:0"), _b("🎛 فیلترها", "x:fl")],
        [_b("📰 گزارش روزانه", "x:dr"), _b("🛠 منابع و ابزارها", "x:tools")],
        [_b(T.BTN_BACK, "m:main")],
    ])
    await show(update, "\n".join(lines), kb)


# ---------- منابع ----------
async def _sources(update, context) -> None:
    ctx = ctx_of(context)
    svc = ctx.radar_service()
    rows = [[_b(f"{ICON[svc.status(s)]} {s.name}", f"x:s:{s.id}")] for s in SOURCES]
    rows.append([_b(T.BTN_BACK, "m:radar")])
    legend = "🟢 سالم · 🟡 فعال بدون دریافت · ⚪ خاموش · 🔑 نیازمند کلید · 🔗 فقط لینک · 🟠/🔴 خطا"
    await show(update, f"🌐 <b>منابع رادار</b>\n{legend}", InlineKeyboardMarkup(rows))


async def _source_panel(update, context, sid: str, note: str = "") -> None:
    ctx = ctx_of(context)
    svc = ctx.radar_service()
    src = BY_ID.get(sid)
    if not src:
        await show(update, "❌ منبع پیدا نشد.", K.back_to_menu())
        return
    st = ctx.repos.radar.state(sid)
    status = svc.status(src)
    lines = [f"{ICON[status]} <b>{esc(src.name)}</b> · {KIND_FA[src.kind]}",
             f"روش: {'API رسمی/عمومی' if src.is_api else 'فقط لینک (اسکرپ نمی‌شود)'}",
             f"وضعیت: {STATUS_FA[status]}", f"ℹ️ {esc(src.note)}"]
    if src.is_api:
        if src.key_attr:
            lines.append(f"🔑 کلید: {'✅ تنظیم شده' if svc.key_for(src) else '❌ نیست'} (متغیر <code>{src.key_env}</code> در .env؛ رایگان)")
        lines.append(f"📜 شرایط استفاده توسط من خوانده شده: {'✅' if src.terms_verified else '⚠️ خیر؛ خودتان بخوانید'}")
        lines.append(f"🧪 با داده‌ی واقعی آزموده شده: {'✅' if src.verified_live else '⚠️ خیر؛ بعد از فعال‌سازی «آزمایش» بزنید'}")
        lines.append(f"🌍 مناطق: {esc(', '.join(svc.regions_for(src)))} · کش: {src.ttl_s // 3600} ساعت")
        lines.append(f"🕒 آخرین تلاش: {_ago(ctx, st['last_fetch_at'])} · آخرین موفق: {_ago(ctx, st['last_ok_at'])}")
        if st["last_error"]:
            lines.append(f"⚠️ {esc(st['last_error'])}")
    if note:
        lines.append(f"\n{note}")
    rows = []
    if src.is_api:
        if not st["enabled"]:
            if not src.key_attr or svc.key_for(src):
                rows.append([_b("✅ بررسی و فعال‌سازی", f"x:ap:{sid}")])
        else:
            rows.append([_b("🧪 دریافت/آزمایش اکنون", f"x:f:{sid}"), _b("⛔ خاموش", f"x:off:{sid}")])
            rows.append([_b("🌍 تغییر مناطق", f"x:rg:{sid}")])
    else:
        rows.append([_b("🧪 بررسی robots.txt (فقط اطلاع)", f"x:rb:{sid}")])
    url_row = [InlineKeyboardButton("🔗 صفحه‌ی منبع", url=src.home_url)]
    if src.terms_url != src.home_url:
        url_row.append(InlineKeyboardButton("📜 شرایط", url=src.terms_url))
    rows.append(url_row)
    for label, url in src.links:
        rows.append([InlineKeyboardButton(f"🔗 {label}", url=url)])
    rows.append([_b(T.BTN_BACK, "x:src")])
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))


def _refresh_text(res) -> str:
    if res.skipped:
        return {"disabled": "منبع خاموش است.", "no_key": "کلید API تنظیم نشده.", "too_soon": "همین چند لحظه پیش دریافت شده؛ کمی بعد دوباره.",
                "fresh": "داده‌ها هنوز تازه‌اند (کش).", "link_only": "این منبع فقط لینک است.", "unknown": "منبع ناشناخته."}.get(res.skipped, res.skipped)
    parts = []
    for r in res.regions:
        parts.append(f"✅ {esc(r.region)}: {r.count} ردیف" if r.ok else f"❌ {esc(r.region)}: {esc(r.error_fa or '')}")
    return "\n".join(parts) or "—"


# ---------- نمودارها ----------
async def _chart_list(update, context) -> None:
    ctx = ctx_of(context)
    svc = ctx.radar_service()
    rows = []
    for src in SOURCES:
        if not src.is_api or not ctx.repos.radar.state(src.id)["enabled"]:
            continue
        for i, region in enumerate(svc.regions_for(src)):
            snap = ctx.repos.radar.latest_snapshot(src.id, region)
            if snap:
                stale = "⚠️ " if svc.is_stale(src, snap["fetched_at"]) else ""
                rows.append([_b(f"{stale}{src.name} · {region} ({snap['entry_count']})", f"x:c:{src.id}:{i}")])
    rows.append([_b(T.BTN_BACK, "m:radar")])
    text = "📋 <b>نمودار هر منبع</b>\nرتبه و شاخص‌ها همان مقدار اصلی منبع است." if len(rows) > 1 else "هنوز نموداری دریافت نشده. منبعی را فعال کنید (🌐 منابع)."
    await show(update, text, InlineKeyboardMarkup(rows))


async def _chart(update, context, sid: str, idx: int) -> None:
    ctx = ctx_of(context)
    svc = ctx.radar_service()
    src = BY_ID.get(sid)
    regions = svc.regions_for(src) if src else []
    if not src or idx >= len(regions):
        raise ValueError("chart")
    region = regions[idx]
    snap = ctx.repos.radar.latest_snapshot(sid, region)
    if not snap:
        await show(update, "هنوز داده‌ای برای این نمودار نیست.", _back("x:cs"))
        return
    prev = ctx.repos.radar.previous_snapshot(sid, region, snap["id"])
    prev_ranks = {scoring.row_key(e): e["rank"] for e in ctx.repos.radar.entries(prev["id"])} if prev else None
    stale = svc.is_stale(src, snap["fetched_at"])
    lines = [f"📋 <b>{esc(src.name)} · {esc(region)}</b>", f"🕒 دریافت: {_ago(ctx, snap['fetched_at'])}"
             + (" · ⚠️ <b>به‌روز نیست</b> (قدیمی؛ جدید در نظر نگیرید)" if stale else "")]
    if prev_ranks is None:
        lines.append("ℹ️ عکس قبلی نیست؛ تغییر رتبه «نامشخص» است.")
    for e in ctx.repos.radar.entries(snap["id"])[:20]:
        if prev_ranks is None:
            d = "تغییر: نامشخص"
        else:
            old = prev_ranks.get(scoring.row_key(e))
            d = "🆕 تازه وارد" if old is None else _delta(old - e["rank"])
        extra = " · ".join(x for x in (esc(e["native_label"]) if e.get("native_label") else "", f"انتشار: {esc(e['published_at'][:10])}" if e.get("published_at") else "") if x)
        link = f" {_a(e['url'], '🔎')}" if e.get("url") else ""
        lines.append(f"{e['rank']}. <b>{esc(e['title'])}</b>{(' — ' + esc(e['artist'])) if e.get('artist') else ''} ({d}){(' · ' + extra) if extra else ''}{link}")
    await show(update, "\n".join(lines)[:4000], InlineKeyboardMarkup([[InlineKeyboardButton("🔗 صفحه‌ی منبع", url=src.home_url)], [_b(T.BTN_BACK, "x:cs")]]))


GROUP_TITLES = {
    "top": "🔥 <b>ترندهای ترکیبی</b> (امتیاز ربات؛ جدا از شاخص رسمی منابع)",
    "ir": "🇮🇷 <b>آهنگ‌های ترند ایرانی</b> (تقریبی: بر اساس خط فارسی عنوان/خواننده)",
    "fo": "🌍 <b>آهنگ‌های ترند خارجی</b>",
    "new": "🆕 <b>آهنگ‌های تازه منتشرشده</b> (فقط طبق تاریخ انتشار خود منبع)",
    "grow": "📈 <b>سریع‌ترین رشد</b> (صعود ≥ ۳ پله نسبت به عکس قبلی همان منبع)",
    "saved": "⭐ <b>پیشنهادهای من</b>",
    "rej": "🚫 <b>پیشنهادهای ردشده</b>",
}


def _track_block(i: int, it: S.Item) -> str:
    badge = STATUS_BADGE.get(it.status, "")
    if it.ts:
        t = it.ts
        apps = []
        for a in t.appearances:
            link = f" {_a(a.url, '🔎')}" if a.url else ""
            nat = f" ({esc(a.native_label)})" if a.native_label else ""
            apps.append(f"{esc(BY_ID[a.source_id].name)}·{esc(a.region)} #{a.rank} [{_delta(a.delta)}]{nat}{link}")
        fresh = f"انتشار (طبق منبع): {esc(t.published_at[:10])}" if t.published_at else "تاریخ انتشار: نامشخص"
        return (f"{i}. {badge}<b>{esc(t.title)}</b>{(' — ' + esc(t.artist)) if t.artist else ''}\n   امتیاز ربات: <b>{t.total:g}</b> "
                f"(رتبه {t.rank_points:g} · تغییر {t.move_points:g} · چندمنبعی {t.multi_points:g} · تازگی {t.fresh_points:g})\n   📍 " + " | ".join(apps) + f"\n   🗓 {fresh}")
    if it.manual:
        m = it.manual
        return (f"{i}. {badge}<b>{esc(m['title'])}</b>{(' — ' + esc(m['artist'])) if m['artist'] else ''}\n   ✍️ ثبت دستی"
                + (f" · {esc(m['source_note'])}" if m["source_note"] else "") + (f" {_a(m['url'], '🔎')}" if m["url"] else ""))
    g = it.sug or {}
    src = BY_ID.get(g.get("source_id") or "")
    return (f"{i}. {badge}<b>{esc(it.title)}</b>{(' — ' + esc(it.artist)) if it.artist else ''}\n   آخرین مشاهده: "
            f"{esc(src.name) if src else (g.get('source_id') or '—')}{(' #' + str(g['best_rank'])) if g.get('best_rank') else ''} (ممکن است دیگر در نمودار نباشد) {_a(g.get('url'), '🔎')}")


STATUS_BADGE = {"saved": "⭐ ", "drafted": "✅ ", "in_archive": "📚 ", "rejected": "🚫 "}


def _sug_items(ctx, status: str) -> list[S.Item]:
    out = []
    for g in ctx.repos.radar.suggestions_by_status(status, 100):
        out.append(S.Item(g["key_norm"], g["title"], g["artist"], g["kind"], sug=g, genre=g.get("genre"), published_at=g.get("published_at")))
    return out


async def _group(update, context, group: str, page: int, genre_idx: int | None = None) -> None:
    ctx = ctx_of(context)
    svc = ctx.radar_service()
    now = utc_now()
    views = svc.chart_views()
    filt = S.load_filters(ctx)
    cb_prefix = "x:top" if group == "top" else (f"x:gg:{genre_idx}" if group == "genre" else f"x:gl:{group}")
    if group in ("saved", "rej"):
        items = _sug_items(ctx, "saved" if group == "saved" else "rejected")
        if group == "saved":
            items += [i for i in _sug_items(ctx, "drafted") + _sug_items(ctx, "in_archive")]
        active = ""
    else:
        if not views and not ctx.repos.radar.manual_list(1):
            await show(update, "هنوز هیچ منبعی داده نداده. اول یک منبع را فعال کنید (🌐 منابع).", InlineKeyboardMarkup([[_b("🌐 منابع", "x:src")], [_b(T.BTN_BACK, "m:radar")]]))
            return
        all_items = S.build_items(ctx)
        pool = S.discoverable(all_items)
        if group == "genre":
            names = S.available_options(ctx, pool)["genre"][1:]
            if genre_idx is None or genre_idx >= len(names):
                raise ValueError("genre")
            filt = {**filt, "genre": names[genre_idx]}
            items = S.apply_filters(S.group_items("top", pool, now), filt, now)
        else:
            items = S.apply_filters(S.group_items(group, pool, now), filt, now)
        if not any(i.ts for i in all_items) and not items and views:
            await show(update, "همه‌ی نمودارهای دریافت‌شده قدیمی‌اند و در امتیاز نمی‌آیند. «🔄 به‌روزرسانی» را بزنید.", _back())
            return
        active = S.active_filters_text(filt)
    stale = [v for v in views if v.stale]
    pages = max(1, math.ceil(len(items) / PAGE))
    page = min(max(page, 0), pages - 1)
    title = GROUP_TITLES.get(group) or f"🎧 <b>سبک: {esc(filt.get('genre', ''))}</b>"
    lines = [title, f"🕒 آخرین به‌روزرسانی: {last_update(ctx)} · صفحه {page + 1} از {pages}"]
    if active:
        lines.append(f"🎛 فیلتر فعال: {esc(active)}")
    if stale:
        lines.append("⚠️ نمودارهای کهنه (در امتیاز نیامده): " + "، ".join(esc(f"{BY_ID[v.source_id].name}·{v.region}") for v in stale))
    if not items:
        lines.append("\nموردی برای نمایش نیست." + (" (فیلترها را بررسی کنید)" if active else ""))
    lines.append("")
    chunk = items[page * PAGE:(page + 1) * PAGE]
    for n, it in enumerate(chunk, page * PAGE + 1):
        lines.append(_track_block(n, it))
    rows = [[_b(f"{STATUS_BADGE.get(it.status, '')}{it.title[:26]}", f"x:sg:{it.sug['id']}")] for it in chunk if it.sug]
    nav = []
    if page > 0:
        nav.append(_b("◀️ قبلی", f"{cb_prefix}:{page - 1}"))
    if page + 1 < pages:
        nav.append(_b("بعدی ▶️", f"{cb_prefix}:{page + 1}"))
    if nav:
        rows.append(nav)
    if group in ("top", "ir", "fo", "new", "grow", "genre"):
        rows.append([_b("🎛 فیلترها", "x:fl"), _b("📐 روش محاسبه", "x:how")])
    rows.append([_b(T.BTN_BACK, "m:radar")])
    await show(update, "\n".join(lines)[:4000], InlineKeyboardMarkup(rows))


async def _top(update, context, page: int) -> None:
    await _group(update, context, "top", page)


async def _how(update, context, note: str = "") -> None:
    ctx = ctx_of(context)
    w = ctx.radar_service().weights()
    kb = InlineKeyboardMarkup([[_b("✏️ تغییر وزن‌ها", "x:w"), _b("↺ پیش‌فرض", "x:wr")], [_b(T.BTN_BACK, "m:radar")]])
    await show(update, scoring.explain(w) + f"\n\nوزن‌های فعلی (رتبه, تغییر, چندمنبعی, تازگی): <code>{w.dump()}</code>" + (f"\n\n{note}" if note else ""), kb)


# ---------- ابزارها، فیلترها، سبک، خوانندگان ----------
async def _tools(update, context) -> None:
    kb = InlineKeyboardMarkup([
        [_b("🌐 منابع", "x:src"), _b("📋 نمودار هر منبع", "x:cs")],
        [_b("🔄 به‌روزرسانی", "x:fa"), _b("✍️ ثبت دستی", "x:ml")],
        [_b("📐 روش محاسبه", "x:how"), _b("🚫 ردشده‌ها", "x:gl:rej:0")],
        [_b(T.BTN_BACK, "m:radar")],
    ])
    await show(update, "🛠 <b>منابع و ابزارها</b>", kb)


async def _filters(update, context, note: str = "") -> None:
    ctx = ctx_of(context)
    f = S.load_filters(ctx)
    pool = S.discoverable(S.build_items(ctx, sync=False))
    lines = ["🎛 <b>فیلترهای رادار</b>\nروی همه‌ی فهرست‌ها (ترند، ایرانی، خارجی، تازه‌ها، رشد، سبک) اعمال می‌شود."]
    for k, label in S.FILTER_LABELS.items():
        lines.append(f"• {label}: <b>{esc(S.VALUE_FA.get(k, {}).get(f[k], f[k]))}</b>")
    lines.append("\nℹ️ «ایرانی/زبان» تقریبی است (از روی خط نوشتار). «بازه‌ی انتشار» فقط آهنگ‌هایی را نگه می‌دارد که خود منبع تاریخ انتشار داده؛ "
                 "تاریخ نامشخص کنار گذاشته می‌شود. «سبک» فقط از منبعی می‌آید که سبک بدهد.")
    if note:
        lines.append(f"\n{note}")
    rows, btns = [], [_b(f"{S.FILTER_LABELS[k]}: {S.VALUE_FA.get(k, {}).get(f[k], f[k])}", f"x:fc:{k}") for k in S.FILTER_LABELS]
    rows += [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([_b("↺ پاک‌کردن فیلترها", "x:fr"), _b(T.BTN_BACK, "m:radar")])
    await show(update, "\n".join(lines), InlineKeyboardMarkup(rows))


def _cycle_options(ctx, key: str) -> list[str]:
    if key in S.CYCLES:
        return S.CYCLES[key]
    pool = S.discoverable(S.build_items(ctx, sync=False))
    return S.available_options(ctx, pool)[key]


async def _genre_menu(update, context) -> None:
    ctx = ctx_of(context)
    pool = S.discoverable(S.build_items(ctx))
    names = S.available_options(ctx, pool)["genre"][1:]
    if not names:
        await show(update, "🎧 هیچ منبعی هنوز سبک نداده. (فقط بعضی منابع مثل Apple Music سبک می‌دهند؛ سبک حدس زده نمی‌شود.)", _back())
        return
    counts = {n: sum(1 for i in pool if i.genre == n) for n in names}
    rows = [[_b(f"{n} ({counts[n]})", f"x:gg:{i}:0")] for i, n in enumerate(names)]
    rows.append([_b(T.BTN_BACK, "m:radar")])
    await show(update, "🎧 <b>بر اساس سبک</b> (سبک طبق اعلام خود منبع)", InlineKeyboardMarkup(rows))


async def _artists(update, context) -> None:
    ctx = ctx_of(context)
    pool = S.discoverable(S.build_items(ctx))
    arts = S.top_artists(pool)
    if not arts:
        await show(update, "هنوز داده‌ای برای خوانندگان نیست. منبعی را فعال کنید (🌐 منابع).", _back())
        return
    lines = ["🎤 <b>خوانندگان پرطرفدار</b> (مجموع امتیازِ رتبه‌ی آهنگ‌هایشان در نمودارهای فعلی؛ تقریبی)", f"🕒 آخرین به‌روزرسانی: {last_update(ctx)}\n"]
    for n, a in enumerate(arts, 1):
        lines.append(f"{n}. <b>{esc(a['artist'])}</b> — {a['tracks']} آهنگ در نمودار · {len(a['sources'])} منبع · امتیاز رتبه {a['points']:g}")
    await show(update, "\n".join(lines), _back())


# ---------- کارت پیشنهاد ----------
LICENSE_TEXT = {
    "unknown": "🎼 <b>مجوز فایل: نامشخص.</b> ربات فقط اطلاعات و لینک می‌دهد؛ دانلود یا انتشار فایل دارای حق نشر بدون مجوز مجاز نیست.",
    "official_link": "🎼 لینک بالا رسمی خود منبع است (فقط برای شنیدن/اطلاعات). <b>مجوز انتشار فایل: نامشخص.</b>",
    "licensed_by_admin": "✅ مجوز ثبت‌شده توسط شما",
}


async def _card(update, context, sid: int, note: str = "") -> None:
    ctx = ctx_of(context)
    g = ctx.repos.radar.get_suggestion(sid)
    if not g:
        await show(update, "❌ این پیشنهاد پیدا نشد.", K.back_to_menu())
        return
    it = next((i for i in S.build_items(ctx, sync=False) if i.key == g["key_norm"]), None)
    from musicbot.songs.textutils import normalize

    dup = ctx.repos.songs.find_by_norm(normalize(g["title"]), normalize(g["artist"]))
    is_dup = bool(dup and dup["id"] != g.get("song_id"))
    lines = [f"{STATUS_BADGE.get(g['status'], '')}🎵 <b>{esc(g['title'])}</b>{(' — ' + esc(g['artist'])) if g['artist'] else ''}",
             f"{'🇮🇷 ایرانی' if g['kind'] == 'iran' else '🌍 خارجی'} (تقریبی؛ قابل تغییر) · وضعیت: {S.STATUS_FA.get(g['status'], g['status'])}"]
    if is_dup:
        lines.append(f"📚 <b>این آهنگ از قبل در آرشیو ربات هست</b> (آهنگ #{dup['id']}) — دوباره پیشنهاد داده نمی‌شود.")
    if it and it.ts:
        t = it.ts
        lines.append(f"امتیاز ربات: <b>{t.total:g}</b> (رتبه {t.rank_points:g} · تغییر {t.move_points:g} · چندمنبعی {t.multi_points:g} · تازگی {t.fresh_points:g}) — جدا از شاخص رسمی منابع")
        for a in t.appearances:
            nat = f" · {esc(a.native_label)}" if a.native_label else ""
            lines.append(f"📍 {esc(BY_ID[a.source_id].name)} · کشور/منطقه: {esc(a.region)} · رتبه‌ی رسمی منبع: #{a.rank} · تغییر: {_delta(a.delta)}{nat}")
        lines.append(f"🗓 انتشار (طبق منبع): {esc(t.published_at[:10])}" if t.published_at else "🗓 تاریخ انتشار: نامشخص")
        if t.genre:
            lines.append(f"🎧 سبک (طبق منبع): {esc(t.genre)}")
    else:
        src = BY_ID.get(g.get("source_id") or "")
        lines.append(f"ℹ️ آخرین مشاهده: {esc(src.name) if src else ('ثبت دستی' if g.get('source_id') == 'manual' else '—')}"
                     f"{(' · رتبه #' + str(g['best_rank'])) if g.get('best_rank') else ''} — اکنون در نمودارهای تازه نیست (اطلاعات ممکن است قدیمی باشد).")
        if g.get("native_label") and g.get("source_id") == "manual":
            lines.append(f"یادداشت منبع: {esc(g['native_label'])}")
    lines.append(LICENSE_TEXT.get(g["license_status"], "") + (f": {esc(g['license_note'])}" if g["license_status"] == "licensed_by_admin" and g.get("license_note") else ""))
    lines.append("📎 فایل آهنگ از کجا؟ ربات فایل نمی‌دهد؛ از ناشر/خواننده یا پلتفرم رسمی <b>با مجوز</b> تهیه کنید و بعد برای ربات بفرستید (به همین آهنگ وصل می‌شود).")
    if g.get("song_id"):
        lines.append(f"🎵 در آرشیو ربات: آهنگ #{g['song_id']} (بدون فایل تا زمانی که فایل را بفرستید)")
    if note:
        lines.append(f"\n{note}")
    i = g["id"]
    rows = []
    if g["status"] == "rejected":
        rows.append([_b("↩️ برگرداندن", f"x:sa:{i}:un")])
    elif is_dup:
        rows.append([_b("🎵 آهنگ در آرشیو", f"g:v:{dup['id']}"), _b("❌ رد", f"x:sa:{i}:rj")])
    else:
        rows.append([_b("⭐ برداشتن" if g["status"] == "saved" else "⭐ ذخیره در پیشنهادهای من", f"x:sa:{i}:sv"), _b("❌ رد پیشنهاد", f"x:sa:{i}:rj")])
        rows.append([_b("📚 افزودن به آرشیو", f"x:sa:{i}:ar"), _b("📝 آماده‌سازی کپشن", f"x:sa:{i}:cp")])
        rows.append([_b("✅ افزودن به پیش‌نویس انتشار", f"x:sa:{i}:dr")])
    if g.get("url"):
        rows.append([InlineKeyboardButton("🔎 مشاهده منبع اصلی", url=g["url"])])
    rows.append([_b("🔁 ایرانی/خارجی", f"x:sa:{i}:kd"), _b("🔏 ثبت مجوز", f"x:sa:{i}:lc")] + ([_b("↩️ پاک‌کردن مجوز", f"x:sa:{i}:lx")] if g["license_status"] == "licensed_by_admin" else []))
    if g.get("song_id"):
        rows.append([_b("🎵 کارت آهنگ در آرشیو", f"g:v:{g['song_id']}")])
    rows.append([_b(T.BTN_BACK, "m:radar")])
    await show(update, "\n".join(x for x in lines if x)[:4000], InlineKeyboardMarkup(rows))


async def _suggestion_action(update, context, sid: int, act: str, uid: int) -> None:
    ctx = ctx_of(context)
    repo = ctx.repos.radar
    g = repo.get_suggestion(sid)
    if not g:
        raise ValueError("suggestion")
    if act == "sv":
        if g["status"] in ("new", "saved"):
            repo.set_suggestion(sid, status="new" if g["status"] == "saved" else "saved")
        await _card(update, context, sid)
    elif act == "rj":
        repo.set_suggestion(sid, status="rejected")
        ctx.repos.logs.add("radar_rejected", uid, f"id={sid}")
        await _card(update, context, sid, "🚫 رد شد و دیگر پیشنهاد داده نمی‌شود (از «ردشده‌ها» قابل برگشت است).")
    elif act == "un":
        repo.set_suggestion(sid, status="new")
        await _card(update, context, sid, "↩️ برگشت.")
    elif act == "kd":
        repo.set_suggestion(sid, kind="foreign" if g["kind"] == "iran" else "iran", kind_override=1)
        await _card(update, context, sid, "🔁 تغییر کرد.")
    elif act in ("ar", "cp", "dr"):
        song_id, how = S.ensure_song(ctx, g, uid)
        how_txt = {"created": f"📚 آهنگ #{song_id} (بدون فایل) در آرشیو ساخته شد.",
                   "existing_link": f"📚 این آهنگ از قبل در آرشیو بود (#{song_id}) و به همین پیشنهاد وصل شد؛ دوباره ساخته نشد.",
                   "linked": f"📚 آهنگ #{song_id} در آرشیو."}[how]
        if act == "cp":
            from musicbot.handlers import captions as captions_h
            from musicbot.publishing.captions import ensure_caption

            await ensure_caption(ctx, song_id)
            await captions_h.show_panel(update, context, song_id, how_txt)
            return
        if act == "ar":
            if g["status"] in ("new", "saved"):
                repo.set_suggestion(sid, status="in_archive")
            await _card(update, context, sid, how_txt)
            return
        from musicbot.publishing.captions import ensure_caption
        from musicbot.ui.song_ui import missing_fields

        await ensure_caption(ctx, song_id)
        if g["status"] != "drafted":
            repo.set_suggestion(sid, status="drafted")
        song = ctx.repos.songs.get(song_id)
        todo = missing_fields(song) + ([] if song.get("telegram_file_id") else ["فایل آهنگ (با مجوز)"])
        await _card(update, context, sid, f"{how_txt}\n✅ به پیش‌نویس انتشار اضافه شد و کپشن آماده است.\n"
                                        + ("📝 برای انتشار لازم است: " + "، ".join(todo) if todo else "آماده‌ی ثبت و پیش‌نمایش است.") + "\n(هیچ‌چیز بدون تأیید شما منتشر نمی‌شود.)")
    elif act == "lc":
        context.user_data["awaiting"] = f"xl:{sid}"
        await show(update, "🔏 یادداشت مجوز را بنویسید (مثلاً «اجازه‌ی کتبی از خواننده» یا «مجوز ناشر»؛ حداکثر ۲۰۰ حرف). "
                           "این فقط برای یادآوری شماست و ربات آن را بررسی یا تأیید حقوقی نمی‌کند.", _back(f"x:sg:{sid}"))
    elif act == "lx":
        repo.set_suggestion(sid, license_status="official_link" if g.get("url") and g.get("source_id") != "manual" else "unknown", license_note=None)
        await _card(update, context, sid, "↩️ مجوز پاک شد.")
    else:
        raise ValueError(act)


# ---------- گزارش روزانه ----------
async def _report_panel(update, context, note: str = "") -> None:
    ctx = ctx_of(context)
    st = ctx.repos.settings
    on = st.get("radar_report_on", "0") == "1"
    when = st.get("radar_report_time", "09:30")
    lines = ["📰 <b>گزارش روزانه‌ی رادار</b>\n", f"وضعیت: {'✅ روشن' if on else '⛔ خاموش'}", f"ساعت ارسال ({esc(str(ctx.settings.timezone))}): <b>{esc(when)}</b>",
             "فقط به چت شما می‌آید؛ شامل ایرانی، خارجی، تازه‌ها و رشد بالا با منبع، رتبه، تغییر رتبه، کشور نمودار و لینک، و زمان آخرین به‌روزرسانی. "
             f"آهنگ‌های تکراری آرشیو، ردشده‌ها و آنچه در {report_mod.REPEAT_DAYS} روز اخیر گزارش شده نمی‌آید. اگر منبعی خطا بدهد در گزارش نوشته می‌شود."]
    if note:
        lines.append(f"\n{note}")
    kb = InlineKeyboardMarkup([
        [_b("⛔ خاموش‌کردن" if on else "✅ روشن‌کردن", "x:drt"), _b("🕒 تغییر ساعت", "x:drh")],
        [_b("👁 پیش‌نمایش گزارش اکنون", "x:drp")],
        [_b(T.BTN_BACK, "m:radar")],
    ])
    await show(update, "\n".join(lines), kb)


# ---------- ثبت دستی ----------
async def _manual_list(update, context) -> None:
    ctx = ctx_of(context)
    items = ctx.repos.radar.manual_list(15)
    lines = ["✍️ <b>ثبت دستی</b>\nآهنگی را که از منابع فقط‌لینک (مثل FarsiChart) یا جای دیگر دیده‌اید ثبت کنید. فقط نام و لینک ذخیره می‌شود؛ رتبه یا آماری ساخته نمی‌شود.\n"]
    rows = []
    for m in items:
        lines.append(f"• <b>{esc(m['title'])}</b>{(' — ' + esc(m['artist'])) if m['artist'] else ''} {_a(m['url'], '🔎')}" + (f" · {esc(m['source_note'])}" if m["source_note"] else ""))
        rows.append([_b(f"🗑 {m['title'][:24]}", f"x:md:{m['id']}")])
    if not items:
        lines.append("هنوز موردی ثبت نشده.")
    rows.insert(0, [_b("➕ ثبت آهنگ", "x:m")])
    rows.append([_b(T.BTN_BACK, "m:radar")])
    await show(update, "\n".join(lines)[:4000], InlineKeyboardMarkup(rows))


# ---------- کالبک ----------
@admin_only
async def radar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctx = ctx_of(context)
    svc = ctx.radar_service()
    parts = update.callback_query.data.split(":")
    action = parts[1]
    uid = update.effective_user.id
    context.user_data.pop("awaiting", None)
    try:
        if action == "src":
            await _sources(update, context)
        elif action == "s":
            await _source_panel(update, context, parts[2])
        elif action == "ap":
            src = BY_ID[parts[2]]
            if not src.is_api or (src.key_attr and not svc.key_for(src)):
                raise ValueError("source")
            await show(update, f"✅ <b>فعال‌سازی {esc(src.name)}</b>\n\nبا تأیید، ربات به این سرویس درخواست (محدود و کش‌شده) می‌فرستد.\n"
                               f"• {esc(src.note)}\n• شرایط استفاده را خودتان بخوانید: {_a(src.terms_url, src.terms_url)}\n"
                               f"• مسئولیت رعایت شرایط سرویس با شماست.\n\nشرایط را خوانده‌اید و می‌پذیرید؟",
                       InlineKeyboardMarkup([[_b("✅ بله، خوانده‌ام؛ فعال شود", f"x:apy:{src.id}"), _b(T.BTN_CANCEL, f"x:s:{src.id}")]]))
        elif action == "apy":
            src = BY_ID[parts[2]]
            if not src.is_api or (src.key_attr and not svc.key_for(src)):
                raise ValueError("source")
            ctx.repos.radar.set_enabled(src.id, True)
            ctx.repos.logs.add("radar_source_enabled", uid, src.id)
            res = await svc.refresh_source(src.id, force=True)
            await _source_panel(update, context, src.id, "🧪 نتیجه‌ی اولین دریافت:\n" + _refresh_text(res))
        elif action == "off":
            ctx.repos.radar.set_enabled(BY_ID[parts[2]].id, False)
            ctx.repos.logs.add("radar_source_disabled", uid, parts[2])
            await _source_panel(update, context, parts[2], "⛔ خاموش شد.")
        elif action == "f":
            src = BY_ID[parts[2]]
            res = await svc.refresh_source(src.id, force=True)
            ctx.repos.logs.add("radar_refresh", uid, src.id)
            await _source_panel(update, context, src.id, "🔄 نتیجه:\n" + _refresh_text(res))
        elif action == "fa":
            results = await svc.refresh_all(force=True)
            if not results:
                await show_hub(update, context, "هیچ منبع API فعالی نیست؛ ابتدا از «🌐 منابع» یکی را فعال کنید.")
                return
            lines = [f"<b>{esc(BY_ID[r.source_id].name)}</b>: {_refresh_text(r)}" for r in results]
            await show_hub(update, context, "🔄 نتیجه‌ی به‌روزرسانی:\n" + "\n".join(lines))
        elif action == "rg":
            src = BY_ID[parts[2]]
            if not src.is_api:
                raise ValueError("source")
            context.user_data["awaiting"] = f"xrg:{src.id}"
            await show(update, f"🌍 مناطق {esc(src.name)} را بنویسید ({esc(src.region_help)}). با کاما جدا کنید، حداکثر ۸.\nفعلی: {esc(', '.join(svc.regions_for(src)))}",
                       _back(f"x:s:{src.id}"))
        elif action == "rb":
            src = BY_ID[parts[2]]
            res = await svc.check_robots(src.links[0][1] if src.links else src.home_url)
            ctx.repos.logs.add("radar_robots_checked", uid, src.id)
            if not res.fetched:
                msg = f"❌ بررسی نشد: {esc(res.error or '')}"
            else:
                verdict = {True: "✅ طبق robots.txt برای ربات‌ها مجاز است", False: "⛔ طبق robots.txt برای ربات‌ها ممنوع است", None: "نامشخص"}[res.allowed]
                msg = f"{verdict}\n\n<code>{esc(res.excerpt)}</code>"
            await _source_panel(update, context, src.id, f"🧪 <b>robots.txt</b> (فقط اطلاع؛ ربات هیچ صفحه‌ای از این منبع را اسکرپ نمی‌کند و شرایط سایت جدا از robots است):\n{msg}")
        elif action == "tools":
            await _tools(update, context)
        elif action == "gl":
            if parts[2] not in ("ir", "fo", "new", "grow", "saved", "rej"):
                raise ValueError("group")
            await _group(update, context, parts[2], int(parts[3]))
        elif action == "gs":
            await _genre_menu(update, context)
        elif action == "gg":
            await _group(update, context, "genre", int(parts[3]), int(parts[2]))
        elif action == "art":
            await _artists(update, context)
        elif action == "fl":
            await _filters(update, context)
        elif action == "fc":
            key = parts[2]
            if key not in S.FILTER_LABELS:
                raise ValueError("filter")
            f = S.load_filters(ctx)
            opts = _cycle_options(ctx, key)
            nxt = opts[(opts.index(f[key]) + 1) % len(opts)] if f[key] in opts else opts[0]
            S.save_filters(ctx, {**f, key: nxt})
            await _filters(update, context)
        elif action == "fr":
            S.save_filters(ctx, dict(S.DEFAULT_FILTERS))
            await _filters(update, context, "↺ همه‌ی فیلترها پاک شد.")
        elif action == "sg":
            await _card(update, context, int(parts[2]))
        elif action == "sa":
            await _suggestion_action(update, context, int(parts[2]), parts[3], uid)
        elif action == "dr":
            await _report_panel(update, context)
        elif action == "drt":
            new = "0" if ctx.repos.settings.get("radar_report_on", "0") == "1" else "1"
            ctx.repos.settings.set("radar_report_on", new)
            ctx.repos.logs.add("radar_report_toggled", uid, new)
            await _report_panel(update, context)
        elif action == "drh":
            context.user_data["awaiting"] = "xt"
            await show(update, "🕒 ساعت ارسال را به شکل HH:MM (۲۴ ساعته، به وقت منطقه‌ی زمانی ربات) بنویسید. مثال: <code>09:30</code>", _back("x:dr"))
        elif action == "drp":
            text = report_mod.build_report(ctx, utc_now(), mark=False)
            await show(update, (text or "امروز موردی برای گزارش نیست (منبع فعالی نیست یا همه‌ی آهنگ‌ها قبلاً گزارش/رد شده یا در آرشیو هستند).")[:3900], _back("x:dr"))
        elif action == "cs":
            await _chart_list(update, context)
        elif action == "c":
            await _chart(update, context, parts[2], int(parts[3]))
        elif action == "top":
            await _top(update, context, int(parts[2]))
        elif action == "how":
            await _how(update, context)
        elif action == "w":
            context.user_data["awaiting"] = "xw"
            await show(update, "✏️ چهار عدد (بین ۰ و ۱۰۰) را با کاما بنویسید: رتبه, تغییر, چندمنبعی, تازگی\nمثال: <code>1,1,10,1</code>", _back("x:how"))
        elif action == "wr":
            ctx.repos.settings.set("radar_weights", scoring.Weights().dump())
            await _how(update, context, "↺ پیش‌فرض شد.")
        elif action == "m":
            context.user_data["awaiting"] = "xm"
            await show(update, "➕ به شکل «عنوان | خواننده | لینک | یادداشت منبع» بنویسید (فقط عنوان لازم است). مثال:\n"
                               "<code>نام آهنگ | نام خواننده | https://farsichart.com/... | FarsiChart Trending</code>", _back("x:ml"))
        elif action == "ml":
            await _manual_list(update, context)
        elif action == "md":
            ctx.repos.radar.delete_manual(int(parts[2]))
            await _manual_list(update, context)
        else:
            raise ValueError(action)
    except (ValueError, IndexError, KeyError):
        await show(update, "❌ درخواست نامعتبر بود.", K.back_to_menu())


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE, awaiting: str) -> None:
    ctx = ctx_of(context)
    raw = (update.effective_message.text or "").strip()
    kind = awaiting.split(":")[0]
    if kind == "xl":
        sid = int(awaiting.split(":")[1])
        note = re.sub(r"\s+", " ", raw)[:200]
        if not note or not ctx.repos.radar.get_suggestion(sid):
            await show(update, "❌ متن معتبر بنویسید یا برگردید.", _back(f"x:sg:{sid}"))
            return
        ctx.repos.radar.set_suggestion(sid, license_status="licensed_by_admin", license_note=note)
        context.user_data.pop("awaiting", None)
        ctx.repos.logs.add("radar_license_noted", update.effective_user.id, f"id={sid}")
        await _card(update, context, sid, "✅ مجوز ثبت شد.")
    elif kind == "xt":
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", ascii_digits(raw).strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            await show(update, "❌ ساعت را به شکل HH:MM بنویسید (مثل 09:30).", _back("x:dr"))
            return
        ctx.repos.settings.set("radar_report_time", f"{int(m.group(1)):02d}:{m.group(2)}")
        context.user_data.pop("awaiting", None)
        await _report_panel(update, context, "✅ ذخیره شد.")
    elif kind == "xrg":
        src = BY_ID.get(awaiting.split(":")[1])
        try:
            regions = validate_regions(src, raw)
        except (ValueError, AttributeError):
            await show(update, "❌ مناطق نامعتبر است. مثال درست را در پیام قبلی ببینید.", _back(f"x:s:{src.id}" if src else "x:src"))
            return
        ctx.repos.radar.set_regions(src.id, ",".join(regions))
        context.user_data.pop("awaiting", None)
        await _source_panel(update, context, src.id, "✅ ذخیره شد؛ «دریافت اکنون» را بزنید.")
    elif kind == "xw":
        try:
            nums = [float(ascii_digits(x).strip()) for x in raw.replace("،", ",").split(",")]
            if len(nums) != 4 or any(n < 0 or n > 100 for n in nums):
                raise ValueError
        except ValueError:
            await show(update, "❌ چهار عدد بین ۰ تا ۱۰۰ با کاما بنویسید.", _back("x:how"))
            return
        ctx.repos.settings.set("radar_weights", scoring.Weights(*nums).dump())
        context.user_data.pop("awaiting", None)
        await _how(update, context, "✅ ذخیره شد.")
    else:  # xm
        fields = [x.strip() for x in raw.split("|")]
        title = re.sub(r"\s+", " ", fields[0])[:150] if fields else ""
        url = fields[2] if len(fields) > 2 and fields[2] else None
        if not title or (url and not re.fullmatch(r"https?://\S+", url, re.I)):
            await show(update, "❌ عنوان لازم است و لینک (اگر هست) باید با http یا https شروع شود.", _back("x:ml"))
            return
        try:
            ctx.repos.radar.add_manual(title, (fields[1][:100] or None) if len(fields) > 1 else None, url, (fields[3][:100] or None) if len(fields) > 3 else None)
        except ValueError:
            await show(update, "❌ حداکثر ۵۰۰ مورد دستی مجاز است.", _back("x:ml"))
            return
        context.user_data.pop("awaiting", None)
        ctx.repos.logs.add("radar_manual_added", update.effective_user.id)
        await _manual_list(update, context)
