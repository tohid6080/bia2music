"""کیبوردهای شیشه‌ای (Inline) مناسب موبایل: حداکثر ۲ دکمه در هر ردیف، با بازگشت/لغو."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from musicbot.ui import texts as T

# الگوی callback_data: "m:<بخش>" منو ، "s:<عمل>" تنظیمات ، "c:<عمل>" کانال
MENU_PREFIX = "m:"


def _btn(label: str, data: str) -> InlineKeyboardButton:
    assert len(data.encode()) <= 64
    return InlineKeyboardButton(label, callback_data=data)


def main_menu() -> InlineKeyboardMarkup:
    buttons = [_btn(title, f"{MENU_PREFIX}{key}") for key, title, _ in T.MENU_ITEMS]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(T.BTN_MAIN_MENU, "m:main")]])


def settings_menu(users_enabled: bool = False, promo_button: bool = True, promo_footer: bool = False) -> InlineKeyboardMarkup:
    toggle = ("👥 امکانات کاربران: ✅ فعال (خاموش‌کردن)", "s:users_off") if users_enabled else (
        "👥 امکانات کاربران: ⛔ غیرفعال (روشن‌کردن)", "s:users")
    return InlineKeyboardMarkup(
        [
            [_btn(T.BTN_CHANNEL_INFO, "s:channel")],
            [_btn(*toggle)],
            [_btn(f"🔗 دکمه‌ی ربات زیر پست: {'✅' if promo_button else '⛔'}", "s:promo_btn")],
            [_btn(f"🤖 خط ربات در کپشن: {'✅' if promo_footer else '⛔'}", "s:promo_ft")],
            [_btn(T.BTN_CHANNEL_CHANGE, "s:channel_change")],
            [_btn(T.BTN_LOGS, "s:logs"), _btn("🩺 وضعیت سیستم", "s:health")],
            [_btn("💾 پشتیبان‌گیری", "s:backup")],
            [_btn("🔁 دکمه‌ی ربات روی پست‌های قبلی کانال", "b:menu")],
            [_btn(T.BTN_BACK, "m:main")],
        ]
    )


def confirm_users_on() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("✅ بله، روشن شود", "s:users_yes"), _btn(T.BTN_CANCEL, "s:cancel")]])


def back_to_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(T.BTN_BACK, "m:settings"), _btn(T.BTN_MAIN_MENU, "m:main")]])


def cancel_to_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn(T.BTN_CANCEL, "s:cancel")]])


def confirm_channel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[_btn("✅ تأیید و ذخیره", "c:confirm"), _btn(T.BTN_CANCEL, "s:cancel")]]
    )
