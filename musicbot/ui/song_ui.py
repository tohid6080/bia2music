"""متن و دکمه‌های بخش آهنگ‌ها و آرشیو (فارسی، موبایل‌پسند، با بازگشت/لغو در هر صفحه)."""
from __future__ import annotations

import html
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from musicbot.ui import texts as T

esc = html.escape
PAGE_SIZE = 8
STATUS_FA = {"draft": "پیش‌نویس", "ready": "آماده انتشار", "scheduled": "زمان‌بندی‌شده", "publishing": "در حال انتشار",
             "published": "منتشرشده", "archived": "بایگانی"}
STATUS_ICON = {"draft": "📝", "ready": "✅", "scheduled": "📅", "publishing": "⏳", "published": "📤", "archived": "🗄"}
FIELD_LABEL = {"t": "نام آهنگ", "a": "نام خواننده", "l": "زبان", "g": "سبک", "m": "حال‌وهوا"}
DIM_TABLE = {"l": "languages", "g": "genres", "m": "moods"}
DIM_TITLE = {"l": "🌐 زبان", "g": "🎸 سبک", "m": "🎭 حال‌وهوا"}
NONE = "— ثبت نشده"


def _b(label: str, data: str) -> InlineKeyboardButton:
    assert len(data.encode()) <= 64, data
    return InlineKeyboardButton(label, callback_data=data)


def fmt_duration(sec: Optional[int]) -> str:
    return f"{sec // 60}:{sec % 60:02d}" if sec else "—"


def fmt_size(size: Optional[int]) -> str:
    return f"{size / 1024 / 1024:.1f} MB" if size else "—"


def missing_fields(song: dict) -> list[str]:
    """فیلدهای لازم برای ثبت نهایی در آرشیو."""
    out = []
    if not song.get("title"):
        out.append("نام آهنگ")
    if not song.get("artist"):
        out.append("نام خواننده")
    if not song.get("language_code"):
        out.append("زبان")
    return out


def song_label(song: dict, limit: int = 38) -> str:
    name = " - ".join(p for p in (song.get("artist"), song.get("title")) if p) or f"آهنگ بدون نام #{song['id']}"
    if len(name) > limit:
        name = name[: limit - 1] + "…"
    return f"{STATUS_ICON.get(song['status'], '🎵')} {name}"


def song_card_text(song: dict, similar: Optional[list[dict]] = None, note: Optional[str] = None) -> str:
    v = lambda x: esc(str(x)) if x else NONE  # noqa: E731
    lines = [
        f"🎵 <b>{v(song.get('title'))}</b>",
        f"🎤 خواننده: {v(song.get('artist'))}",
        f"🌐 زبان: {v(song.get('language_name'))}",
        f"🎸 سبک: {v(song.get('genre_name'))}",
        f"🎭 حال‌وهوا: {v(song.get('mood_name'))}",
        f"📌 وضعیت: {STATUS_ICON.get(song['status'], '')} {STATUS_FA.get(song['status'], song['status'])}",
        f"⏱ {fmt_duration(song.get('duration_seconds'))} · 💾 {fmt_size(song.get('file_size'))}",
    ]
    if not song.get("telegram_file_id"):
        lines.append("📎 فایل: ندارد (فقط اطلاعات؛ برای انتشار فایل آهنگ را — با مجوز — برای ربات بفرستید)")
    if similar:
        names = "، ".join(esc(song_label(s, 30)) for s in similar[:3])
        lines.append(f"\n⚠️ آهنگ مشابه (همان نام و خواننده) از قبل ثبت شده: {names}")
    if song.get("post_url"):
        lines.append(f"🔗 {esc(song['post_url'])}")
    if song["status"] == "published" and song.get("caption"):
        lines.append(f"🗒 {esc(song['caption'][:150])}")
    if song["status"] == "publishing":
        lines.append("\n⚠️ وضعیت انتشار نامشخص است؛ کانال را بررسی کنید.")
    if note:
        lines.append(f"\n{note}")
    return "\n".join(lines)


def song_card_keyboard(song: dict, similar: Optional[list[dict]] = None, extras: Optional[dict] = None) -> InlineKeyboardMarkup:
    i = song["id"]
    extras = extras or {}
    rows = [
        [_b("✏️ نام آهنگ", f"g:e:{i}:t"), _b("🎤 خواننده", f"g:e:{i}:a")],
        [_b("🌐 زبان", f"g:e:{i}:l"), _b("🎸 سبک", f"g:e:{i}:g")],
        [_b("🎭 حال‌وهوا", f"g:e:{i}:m")],
    ]
    for s in (similar or [])[:2]:
        rows.append([_b(f"👁 مشاهده مشابه #{s['id']}", f"g:v:{s['id']}")])
    if song["status"] != "published":
        rows.append([_b("📝 کپشن و هشتگ", f"k:{i}")])
    if song["status"] in ("ready", "scheduled", "published"):
        rows.append([_b("🎧 پلی‌لیست‌ها", f"y:sp:{i}")])
    if song["status"] == "draft":
        rows.append([_b("✅ ثبت در آرشیو", f"g:r:{i}")])
    elif song["status"] == "ready":
        rows.append([_b("📤 پیش‌نمایش و انتشار", f"p:pv:{i}")])
        rows.append([_b("↩️ بازگشت به پیش‌نویس", f"g:u:{i}")])
    elif song["status"] == "scheduled":
        rows.append([_b("📅 مشاهده زمان‌بندی", f"p:i:{i}")])
    elif song["status"] == "publishing":
        rows.append([_b("↩️ کانال را بررسی کردم؛ برگرد به «آماده»", f"g:u:{i}")])
    if song["status"] in ("draft", "ready", "archived"):
        rows.append([_b("🗑 حذف", f"g:d:{i}")])
    if extras.get("aa_l"):
        rows.append([_b(f"🌐 اعمال این زبان برای {extras['aa_l']} آهنگ دیگر این خواننده", f"g:aa:{i}:l")])
    if extras.get("aa_g"):
        rows.append([_b(f"🎸 اعمال این سبک برای {extras['aa_g']} آهنگ دیگر این خواننده", f"g:aa:{i}:g")])
    if extras.get("next"):
        rows.append([_b("⏭ بعدی بدون زبان", f"g:nx:{i}")])
    rows.append([_b(T.BTN_BACK, "g:l:all:0"), _b(T.BTN_MAIN_MENU, "m:main")])
    return InlineKeyboardMarkup(rows)


def duplicate_text(song: dict, reason: str) -> str:
    why = "همین فایل" if reason == "file_unique_id" else "فایلی با محتوای یکسان"
    return f"🔁 <b>آهنگ تکراری</b>\n{why} قبلاً در آرشیو ثبت شده است و دوباره ذخیره نشد.\n\n{song_card_text(song)}"


def duplicate_keyboard(song: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("👁 مشاهده آهنگ ثبت‌شده", f"g:v:{song['id']}")], [_b(T.BTN_MAIN_MENU, "m:main")]])


def songs_menu_text(counts: dict) -> str:
    total = sum(counts.values())
    return (
        "🎵 <b>مدیریت آهنگ‌ها</b>\n\n"
        f"📝 پیش‌نویس: {counts.get('draft', 0)}\n"
        f"✅ آماده انتشار: {counts.get('ready', 0)}\n"
        f"📚 کل آرشیو: {total}\n\n"
        "➕ برای افزودن آهنگ، <b>فایل صوتی</b> را مستقیم برای همین ربات بفرستید."
    )


def songs_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("➕ افزودن آهنگ", "g:add")],
        [_b("📝 پیش‌نویس‌ها", "g:l:draft:0"), _b("✅ آماده انتشار", "g:l:ready:0")],
        [_b(T.BTN_BACK, "m:main")],
    ])


ADD_HELP = (
    "➕ <b>افزودن آهنگ</b>\n\n"
    "فایل صوتی (MP3 و ...) را همین‌جا برای ربات بفرستید یا از کانال/چت دیگر فوروارد کنید.\n"
    "ربات نام و خواننده را از اطلاعات فایل می‌خواند، تکراری بودن را بررسی می‌کند و پیش‌نویس می‌سازد.\n"
    "هیچ‌چیز در کانال منتشر نمی‌شود."
)


def add_help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_BACK, "m:songs")]])


def archive_menu_text(counts: dict) -> str:
    return f"📚 <b>آرشیو موسیقی</b>\n\nکل آهنگ‌ها: {sum(counts.values())}\nیکی از گزینه‌ها را انتخاب کنید:"


def archive_menu_keyboard(unclassified: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [_b("🔍 جست‌وجو", "g:q")],
        [_b("📋 همه آهنگ‌ها", "g:l:all:0")],
        [_b("🌐 بر اساس زبان", "g:cd:l"), _b("🎸 بر اساس سبک", "g:cd:g")],
        [_b("🎭 بر اساس حال‌وهوا", "g:cd:m")],
    ]
    if unclassified:
        rows.append([_b(f"🏷 منتشرشده‌های بدون زبان ({unclassified})", "g:l:nolang:0")])
    rows.append([_b("📥 درون‌ریزی از کانال", "i:menu")])
    rows.append([_b(T.BTN_BACK, "m:main")])
    return InlineKeyboardMarkup(rows)


def list_text(title: str, total: int, page: int, pages: int) -> str:
    if total == 0:
        return f"📋 <b>{esc(title)}</b>\n\nموردی پیدا نشد."
    return f"📋 <b>{esc(title)}</b>\n{total} مورد · صفحه {page + 1} از {pages}"


def list_keyboard(songs: list[dict], flt: str, page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[_b(song_label(s), f"g:v:{s['id']}")] for s in songs]
    nav = []
    if page > 0:
        nav.append(_b("◀️ قبلی", f"g:l:{flt}:{page - 1}"))
    if page + 1 < pages:
        nav.append(_b("بعدی ▶️", f"g:l:{flt}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_b(T.BTN_BACK, "m:archive"), _b(T.BTN_MAIN_MENU, "m:main")])
    return InlineKeyboardMarkup(rows)


def dim_menu_keyboard(dim: str, items: list[dict], counts: dict) -> InlineKeyboardMarkup:
    buttons = [_b(f"{it['name_fa']} ({counts.get(it['key'], 0)})", f"g:l:{dim}.{it['key']}:0") for it in items]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_b(T.BTN_BACK, "m:archive")])
    return InlineKeyboardMarkup(rows)


def picker_keyboard(song_id: int, dim: str, items: list[dict]) -> InlineKeyboardMarkup:
    buttons = [_b(it["name_fa"], f"g:s:{song_id}:{dim}:{it['key']}") for it in items]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_b("➖ بدون مقدار", f"g:s:{song_id}:{dim}:0")])
    rows.append([_b(T.BTN_BACK, f"g:v:{song_id}")])
    return InlineKeyboardMarkup(rows)


def cancel_to_card(song_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_CANCEL, f"g:v:{song_id}")]])


def cancel_search() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_CANCEL, "m:archive")]])


def delete_confirm_keyboard(song_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("🗑 بله، حذف شود", f"g:dy:{song_id}"), _b(T.BTN_CANCEL, f"g:v:{song_id}")]])
