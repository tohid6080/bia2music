"""گزارش روزانه‌ی رادار برای مدیر. فقط متن می‌سازد؛ ارسال در زمان‌بند (فقط به چت مدیر) انجام می‌شود."""
from __future__ import annotations

import html
from datetime import datetime, timedelta
from typing import Optional

from musicbot.publishing.timeutil import format_local, from_iso, to_iso
from musicbot.radar.service import ERR_FA
from musicbot.radar.sources import BY_ID, SOURCES
from musicbot.radar import suggest as S

esc = html.escape
PER_KIND = 5
EXTRA = 3
REPEAT_DAYS = 3


def _delta(d) -> str:
    return "نامشخص" if d is None else (f"▲{d}" if d > 0 else (f"▼{-d}" if d < 0 else "＝"))


def _link(url: Optional[str]) -> str:
    return f'<a href="{esc(url, quote=True)}">لینک منبع</a>' if url else "لینک منبع: —"


def _entry(i: int, it: S.Item, badge: str = "") -> str:
    head = f"{i}. <b>{esc(it.title)}</b>{badge}"
    artist = f"\n   {esc(it.artist)}" if it.artist else ""
    if it.ts:
        a = min(it.ts.appearances, key=lambda x: x.rank)
        src = BY_ID[a.source_id].name
        return (f"{head}{artist}\n   منبع و رتبه: {esc(src)} #{a.rank}"
                f"\n   میزان تغییر رتبه: {_delta(a.delta)}\n   کشور نمودار: {esc(a.region)}\n   {_link(a.url)}")
    note = (it.manual or {}).get("source_note")
    return f"{head}{artist}\n   ثبت دستی{(' · ' + esc(note)) if note else ''}\n   {_link((it.manual or {}).get('url'))}"


def _recently_reported(it: S.Item, now: datetime) -> bool:
    r = (it.sug or {}).get("reported_at")
    return bool(r and (now - from_iso(r)) < timedelta(days=REPEAT_DAYS))


def build_report(ctx, now_utc: datetime, *, mark: bool = True) -> Optional[str]:
    """None اگر چیزی برای گزارش نیست و هیچ خطایی هم نیست (پیام بی‌فایده نمی‌رود)."""
    svc = ctx.radar_service()
    items = S.discoverable(S.build_items(ctx))
    fresh = [i for i in items if i.ts and not _recently_reported(i, now_utc)]
    iran = S.group_items("ir", fresh, now_utc)[:PER_KIND]
    foreign = S.group_items("fo", fresh, now_utc)[:PER_KIND]
    shown = {i.key for i in iran + foreign}
    new = [i for i in S.group_items("new", fresh, now_utc) if i.key not in shown][:EXTRA]
    shown |= {i.key for i in new}
    grow = [i for i in S.group_items("grow", fresh, now_utc) if i.key not in shown][:EXTRA]
    problems = []
    for src in SOURCES:
        if src.is_api and ctx.repos.radar.state(src.id)["enabled"]:
            st = ctx.repos.radar.state(src.id)
            if st["last_status"] in ("error", "partial") and st["last_error"]:
                problems.append(f"⚠️ {esc(src.name)}: {esc(st['last_error'])}")
    stale = [v for v in svc.chart_views() if v.stale]
    if stale:
        problems.append("⚠️ داده‌ی قدیمی (در گزارش نیامده): " + "، ".join(esc(f"{BY_ID[v.source_id].name}·{v.region}") for v in stale))
    if not (iran or foreign or new or grow) and not problems:
        return None
    lines = ["🔥 <b>پیشنهادهای موسیقی امروز</b>\n"]
    badge = lambda it: (" 🆕" if S.is_new(it, now_utc) else "") + (" 📈" if (it.max_delta or 0) >= S.FAST_MIN_DELTA else "")  # noqa: E731
    reported: list[S.Item] = []
    for title, rows in (("🇮🇷 موسیقی ایرانی", iran), ("🌍 موسیقی خارجی", foreign)):
        if rows:
            lines.append(title)
            lines += [_entry(n, it, badge(it)) + "\n" for n, it in enumerate(rows, 1)]
            reported += rows
    for title, rows in (("🆕 تازه منتشرشده (طبق تاریخ خود منبع)", new), ("📈 رشد بالا نسبت به عکس قبلی", grow)):
        if rows:
            lines.append(title)
            lines += [_entry(n, it) + "\n" for n, it in enumerate(rows, 1)]
            reported += rows
    if not reported:
        lines.append("امروز آهنگ تازه‌ای برای پیشنهاد نیست.")
    lines += problems
    last = [ctx.repos.radar.state(s.id)["last_ok_at"] for s in SOURCES if s.is_api]
    last = [x for x in last if x]
    lines.append(f"\n🕒 آخرین به‌روزرسانی داده‌ها: {format_local(max(last), ctx.settings.tz) if last else 'نامشخص'}")
    lines.append("ℹ️ فقط اطلاعات و لینک رسمی؛ مجوز فایل نامشخص است و هیچ آهنگی بدون تأیید شما منتشر نمی‌شود.")
    if mark:
        ctx.repos.radar.mark_reported([it.sug["id"] for it in reported if it.sug], to_iso(now_utc))
    return "\n".join(lines)
