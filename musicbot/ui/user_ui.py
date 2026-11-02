"""رابط کاربران عادی (u:). فقط آهنگ‌های منتشرشده نمایش داده می‌شود و فایل ارسال نمی‌شود، لینک پست کانال داده می‌شود."""
from __future__ import annotations

import html
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from musicbot.ui import texts as T
from musicbot.ui.song_ui import NONE, _b

esc = html.escape
PAGE = 8
HOME = "u:home"


def home_text(channel_title: str) -> str:
    return (f"🎧 <b>به ربات {esc(channel_title)} خوش آمدید</b>\n\n"
            "آهنگ پیدا کنید، پیشنهاد بگیرید و پلی‌لیست‌ها را ببینید.\n"
            "💡 برای جست‌وجو، کافی است نام آهنگ یا خواننده را همین‌جا بنویسید.")


def home_keyboard(channel_url: Optional[str], premium: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [_b("🔍 جست‌وجوی آهنگ", "u:s"), _b("💡 پیشنهاد برای من", "u:r")],
        [_b("🎭 بر اساس حال‌وهوا", "u:cm"), _b("🌐 بر اساس زبان", "u:cl")],
        [_b("🎧 پلی‌لیست‌ها", "u:p"), _b("❤️ پسندهای من", "u:l:likes:0")],
        [_b("⚙️ علایق من", "u:i"), _b("🎤 درخواست آهنگ", "u:q")],
        [_b("🔒 حریم خصوصی", "u:pv")],
    ]
    if premium:
        rows.append([_b("⭐ اشتراک ویژه", "u:pr")])
    if channel_url:
        rows.append([InlineKeyboardButton("📢 کانال", url=channel_url)])
    return InlineKeyboardMarkup(rows)


def premium_text(benefits: str, stars: int, days: int, until_text: str | None) -> str:
    status = f"✅ اشتراک شما تا <b>{esc(until_text)}</b> فعال است." if until_text else "اشتراک فعالی ندارید."
    return f"⭐ <b>اشتراک ویژه</b>\n\n{benefits}\n\n💰 {stars} استارز برای {days} روز\n{status}\n\n📜 /terms · 📞 /paysupport"


def premium_keyboard(active: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("🔁 تمدید اشتراک" if active else "⭐ خرید اشتراک", "u:buy")], [_b(T.BTN_BACK, HOME)]])


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_BACK, HOME)]])


def cancel_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_CANCEL, HOME)]])


def song_label(song: dict, limit: int = 38) -> str:
    name = " - ".join(p for p in (song.get("artist"), song.get("title")) if p) or "آهنگ"
    return "🎵 " + (name if len(name) <= limit else name[: limit - 1] + "…")


def song_text(song: dict, likes: int) -> str:
    v = lambda x: esc(str(x)) if x else NONE  # noqa: E731
    meta = " · ".join(esc(x) for x in (song.get("language_name"), song.get("genre_name"), song.get("mood_name")) if x)
    return (f"🎵 <b>{v(song.get('title'))}</b>\n🎤 {v(song.get('artist'))}\n"
            + (f"🏷 {meta}\n" if meta else "") + f"❤️ {likes} پسند")


def song_keyboard(song: dict, liked: bool, download: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if song.get("post_url"):
        rows.append([InlineKeyboardButton("🎧 شنیدن در کانال", url=song["post_url"])])
    rows.append([_b("💔 برداشتن پسند" if liked else "❤️ پسندیدم", f"u:lk:{song['id']}")])
    if download:
        rows.append([_b("📥 دریافت فایل (ویژه ⭐)", f"u:dl:{song['id']}")])
    rows.append([_b(T.BTN_BACK, HOME)])
    return InlineKeyboardMarkup(rows)


def list_keyboard(songs: list[dict], flt: str, page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[_b(song_label(s), f"u:v:{s['id']}")] for s in songs]
    nav = []
    if page > 0:
        nav.append(_b("◀️ قبلی", f"u:l:{flt}:{page - 1}"))
    if page + 1 < pages:
        nav.append(_b("بعدی ▶️", f"u:l:{flt}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_b(T.BTN_BACK, HOME)])
    return InlineKeyboardMarkup(rows)


def playlist_song_keyboard(songs: list[dict], pid: int, page: int, pages: int) -> InlineKeyboardMarkup:
    rows = [[_b(song_label(s), f"u:v:{s['id']}")] for s in songs]
    nav = []
    if page > 0:
        nav.append(_b("◀️ قبلی", f"u:pl:{pid}:{page - 1}"))
    if page + 1 < pages:
        nav.append(_b("بعدی ▶️", f"u:pl:{pid}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([_b(T.BTN_BACK, "u:p")])
    return InlineKeyboardMarkup(rows)


def pick_keyboard(items: list[dict], prefix: str, suffix: str = "") -> InlineKeyboardMarkup:
    buttons = [_b(it["name_fa"], f"{prefix}{it['key']}{suffix}") for it in items]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_b(T.BTN_BACK, HOME)])
    return InlineKeyboardMarkup(rows)


def empty_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("🎤 درخواست آهنگ", "u:q")], [_b(T.BTN_BACK, HOME)]])


def suggest_keyboard(songs: list[dict]) -> InlineKeyboardMarkup:
    rows = [[_b(song_label(s), f"u:v:{s['id']}")] for s in songs]
    rows.append([_b("🔄 پیشنهاد دیگر", "u:r")])
    rows.append([_b(T.BTN_BACK, HOME)])
    return InlineKeyboardMarkup(rows)


PRIVACY = (
    "🔒 <b>حریم خصوصی</b>\n\n"
    "• برای جست‌وجو و دیدن آهنگ‌ها چیزی از شما ذخیره نمی‌شود، جز شناسه و نام کاربری تلگرام شما (برای مدیریت ربات).\n"
    "• <b>علایق و پسندها فقط با رضایت صریح شما</b> ذخیره می‌شود و فقط همان چیزی است که خودتان انتخاب می‌کنید؛ "
    "ربات چیزی را حدس نمی‌زند.\n"
    "• مدیر فقط آمار تجمیعی علایق را می‌بیند.\n"
    "• هر زمان با «🗑 حذف اطلاعات من» همه‌چیز پاک می‌شود."
)
CONSENT = (
    "🔒 برای ذخیره <b>علایق و پسندها</b> رضایت شما لازم است.\n\n"
    "فقط انتخاب‌های خودتان (سبک، حال‌وهوا، زبان، آهنگ‌های پسندیده) ذخیره می‌شود تا پیشنهاد بهتری بگیرید. "
    "هر زمان می‌توانید همه را حذف کنید.\n\nموافقید؟"
)


def consent_keyboard(after: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("✅ موافقم", f"u:cy:{after}"), _b("❌ نه", HOME)]])


def interests_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("🌐 زبان‌ها", "u:ip:l"), _b("🎸 سبک‌ها", "u:ip:g")],
        [_b("🎭 حال‌وهواها", "u:ip:m")],
        [_b("🗑 حذف اطلاعات من", "u:dx")],
        [_b(T.BTN_BACK, HOME)],
    ])


def interest_picker(items: list[dict], dim: str, chosen: set[str]) -> InlineKeyboardMarkup:
    buttons = [_b(("✅ " if str(it["key"]) in chosen else "⬜ ") + it["name_fa"], f"u:it:{dim}:{it['key']}") for it in items]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_b(T.BTN_BACK, "u:i")])
    return InlineKeyboardMarkup(rows)


def delete_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("🗑 بله، همه حذف شود", "u:dy"), _b(T.BTN_CANCEL, "u:i")]])
