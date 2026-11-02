from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from musicbot.publishing.timeutil import QUICK
from musicbot.ui import texts as T
from musicbot.ui.song_ui import _b


def preview_keyboard(sid: int, fp: str, promo_url: str | None = None, promo_label: str = "") -> InlineKeyboardMarkup:
    rows = [
        [_b("✅ تأیید و انتشار", f"p:ok:{sid}:{fp}")],
        [_b("✏️ ویرایش کپشن", f"k:{sid}"), _b("🎵 تغییر اطلاعات آهنگ", f"g:v:{sid}")],
        [_b("💾 ذخیره در پیش‌نویس", f"p:dr:{sid}"), _b("📅 زمان‌بندی", f"p:sc:{sid}")],
        [_b("❌ لغو", f"p:cx:{sid}")],
    ]
    if promo_url:  # همان دکمه‌ای که زیر پست منتشرشده هم هست
        rows.append([InlineKeyboardButton(promo_label, url=promo_url)])
    return InlineKeyboardMarkup(rows)


def confirm_keyboard(sid: int, fp: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b("✅ بله، همین حالا منتشر شود", f"p:go:{sid}:{fp}")],
                                 [_b("↩️ برگشت", f"p:bk:{sid}:{fp}")]])


def schedule_keyboard(sid: int) -> InlineKeyboardMarkup:
    buttons = [_b(label, f"p:st:{sid}:{code}") for code, label in QUICK.items()]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_b("🕒 زمان دلخواه", f"p:sx:{sid}")])
    rows.append([_b(T.BTN_BACK, f"g:v:{sid}")])
    return InlineKeyboardMarkup(rows)


def custom_time_keyboard(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_CANCEL, f"p:sc:{sid}")]])


def queue_item_keyboard(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("👁 پیش‌نمایش و انتشار", f"p:pv:{sid}")],
        [_b("🕒 تغییر زمان", f"p:sc:{sid}"), _b("❌ لغو زمان‌بندی", f"p:qc:{sid}")],
        [_b(T.BTN_BACK, "p:q"), _b(T.BTN_MAIN_MENU, "m:main")],
    ])


def after_publish_keyboard(url: str | None) -> InlineKeyboardMarkup:
    rows = []
    if url:
        rows.append([InlineKeyboardButton("🔗 مشاهده پست", url=url)])
    rows.append([_b(T.BTN_MAIN_MENU, "m:main")])
    return InlineKeyboardMarkup(rows)


def caption_panel_keyboard(sid: int, previewable: bool) -> InlineKeyboardMarkup:
    rows = [
        [_b("🔄 تولید دوباره", f"k:gen:{sid}")],
        [_b("✏️ ویرایش کپشن", f"k:ec:{sid}"), _b("#️⃣ ویرایش هشتگ", f"k:eh:{sid}")],
    ]
    if previewable:
        rows.append([_b("👁 پیش‌نمایش پست", f"p:pv:{sid}")])
    rows.append([_b(T.BTN_BACK, f"g:v:{sid}")])
    return InlineKeyboardMarkup(rows)


def cancel_to_caption(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_b(T.BTN_CANCEL, f"k:{sid}")]])


def publish_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("✅ آماده انتشار", "g:l:ready:0")],
        [_b("📅 زمان‌بندی‌شده‌ها", "p:q"), _b("📤 منتشرشده‌ها", "g:l:published:0")],
        [_b(T.BTN_BACK, "m:main")],
    ])


def captions_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_b("✅ آهنگ‌های آماده", "g:l:ready:0"), _b("📝 پیش‌نویس‌ها", "g:l:draft:0")],
        [_b(T.BTN_BACK, "m:main")],
    ])


def schedule_list_keyboard(items: list[dict], labels: dict) -> InlineKeyboardMarkup:
    rows = [[_b(labels[i["song_id"]], f"p:i:{i['song_id']}")] for i in items]
    rows.append([_b(T.BTN_BACK, "m:publish"), _b(T.BTN_MAIN_MENU, "m:main")])
    return InlineKeyboardMarkup(rows)
