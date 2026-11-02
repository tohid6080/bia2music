"""ارسال به تلگرام: پیش‌نمایش برای مدیر و انتشار در کانال.

قانون حیاتی: `publish_now` فقط باید از handlers/publish.py تابع `_go` (دکمه «بله، همین حالا منتشر شود»)
صدا زده شود. تست ایمنی این را به‌صورت ساختاری بررسی می‌کند. زمان‌بند هرگز به این ماژول دسترسی ندارد.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from telegram import Bot, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError, TimedOut

from musicbot.db import Repositories
from musicbot.publishing.captions import MAX_CAPTION, PostOptions, fingerprint, final_caption, post_markup
from musicbot.ui import song_ui as U

log = logging.getLogger(__name__)


class PublishError(Exception):
    def __init__(self, message_fa: str, uncertain: bool = False):
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.uncertain = uncertain  # true: ممکن است پست ارسال شده باشد؛ کانال را بررسی کنید


@dataclass
class PublishResult:
    message_id: int
    post_url: Optional[str]


def post_url_for(channel_ref: str, message_id: int) -> Optional[str]:
    if channel_ref.startswith("@"):
        return f"https://t.me/{channel_ref[1:]}/{message_id}"
    if channel_ref.startswith("-100"):
        return f"https://t.me/c/{channel_ref[4:]}/{message_id}"
    return None


def readiness_problems(song: dict, opts: Optional[PostOptions] = None) -> list[str]:
    """دلایلی که مانع پیش‌نمایش/انتشار است (خالی = آماده)."""
    problems = [f"{f} کامل نیست" for f in U.missing_fields(song)]
    caption = final_caption(song, opts)
    if not (song.get("caption") or "").strip():
        problems.append("کپشن خالی است")
    if len(caption) > MAX_CAPTION:
        problems.append(f"کپشن و هشتگ {len(caption)} حرف است (حداکثر {MAX_CAPTION})")
    if not song.get("telegram_file_id"):
        problems.append("فایل آهنگ موجود نیست")
    return problems


async def send_preview(bot: Bot, chat_id: int, song: dict, keyboard: InlineKeyboardMarkup, opts: Optional[PostOptions] = None):
    """پیش‌نمایش فقط برای چت خصوصی مدیر؛ دقیقاً همان فایل و کپشنی که منتشر خواهد شد."""
    return await bot.send_audio(
        chat_id=chat_id, audio=song["telegram_file_id"], caption=final_caption(song, opts),
        title=song.get("title"), performer=song.get("artist"), duration=song.get("duration_seconds"),
        reply_markup=keyboard,
    )


async def publish_now(bot: Bot, repos: Repositories, channel_ref: Optional[str], song_id: int,
                      admin_id: int, expected_fingerprint: str, opts: Optional[PostOptions] = None) -> PublishResult:
    """انتشار در کانال. فراخواننده موظف است فقط پس از تأیید صریح مدیر آن را صدا بزند."""
    if not channel_ref:
        raise PublishError("کانال مقصد تنظیم نشده است (⚙️ تنظیمات).")
    song = repos.songs.get(song_id)
    if not song:
        raise PublishError("آهنگ پیدا نشد.")
    if song["status"] == "published":
        raise PublishError("این آهنگ قبلاً منتشر شده است.")
    if song["status"] not in ("ready", "scheduled"):
        raise PublishError("فقط آهنگ ثبت‌شده در آرشیو قابل انتشار است.")
    problems = readiness_problems(song, opts)
    if problems:
        raise PublishError("انتشار ممکن نیست: " + "؛ ".join(problems))
    if fingerprint(song, opts) != expected_fingerprint:
        raise PublishError("محتوای پست بعد از این پیش‌نمایش تغییر کرده است. دوباره پیش‌نمایش بگیرید و تأیید کنید.")

    previous = repos.songs.claim_for_publishing(song_id)
    if previous is None:  # کس دیگری/ضربه دوم همزمان
        raise PublishError("این آهنگ در حال انتشار است یا قبلاً منتشر شده است.")
    try:
        msg = await bot.send_audio(
            chat_id=channel_ref, audio=song["telegram_file_id"], caption=final_caption(song, opts),
            title=song.get("title"), performer=song.get("artist"), duration=song.get("duration_seconds"),
            reply_markup=post_markup(opts),
        )
    except Forbidden:
        repos.songs.release_claim(song_id, previous)
        repos.logs.add("publish_failed", admin_id, f"id={song_id} forbidden", level="error")
        raise PublishError("ربات اجازه ارسال در کانال را ندارد. ربات را ادمین کنید و Post Messages را روشن کنید.") from None
    except BadRequest:
        repos.songs.release_claim(song_id, previous)
        repos.logs.add("publish_failed", admin_id, f"id={song_id} bad_request", level="error")
        raise PublishError("تلگرام ارسال را نپذیرفت. شناسه کانال و دسترسی ربات را بررسی کنید.") from None
    except (TimedOut, NetworkError):
        # نامعلوم: شاید پست رفته باشد. برای جلوگیری از انتشار تکراری وضعیت «در حال انتشار» می‌ماند.
        repos.logs.add("publish_uncertain", admin_id, f"id={song_id}", level="error")
        raise PublishError("ارتباط حین ارسال قطع شد و معلوم نیست پست ارسال شده یا نه. "
                           "کانال را بررسی کنید، سپس وضعیت آهنگ را از کارت آن اصلاح کنید.", uncertain=True) from None
    except TelegramError:
        repos.songs.release_claim(song_id, previous)
        repos.logs.add("publish_failed", admin_id, f"id={song_id} telegram_error", level="error")
        raise PublishError("ارسال به کانال ناموفق بود. کمی بعد دوباره تلاش کنید.") from None

    url = post_url_for(channel_ref, msg.message_id)
    repos.songs.mark_published(song_id, msg.message_id, url)
    repos.queue.record_published(song_id, channel_ref, admin_id)
    repos.logs.add("song_published", admin_id, f"id={song_id} msg={msg.message_id}")
    return PublishResult(msg.message_id, url)


# ---------------------------------------------------------------------------
# پست تبلیغی (متنی) در کانال: همان قانون آهنگ‌ها؛ فقط از handlers/campaigns.py تابع `_go`
# ---------------------------------------------------------------------------
MAX_AD_TEXT = 4096


def ad_fingerprint(c: dict) -> str:
    import hashlib

    raw = "\x00".join(str(c.get(k) or "") for k in ("title", "post_text", "button_label", "button_url"))
    return hashlib.sha1(raw.encode()).hexdigest()[:8]


def ad_markup(c: dict) -> Optional[InlineKeyboardMarkup]:
    from telegram import InlineKeyboardButton

    if c.get("button_label") and c.get("button_url"):
        return InlineKeyboardMarkup([[InlineKeyboardButton(c["button_label"], url=c["button_url"])]])
    return None


def ad_problems(c: dict) -> list[str]:
    out = []
    text = (c.get("post_text") or "").strip()
    if not text:
        out.append("متن پست خالی است")
    if len(text) > MAX_AD_TEXT:
        out.append(f"متن {len(text)} حرف است (حداکثر {MAX_AD_TEXT})")
    if bool(c.get("button_label")) != bool(c.get("button_url")):
        out.append("دکمه ناقص است (متن و لینک هر دو لازم است)")
    return out


async def send_ad_preview(bot: Bot, chat_id: int, c: dict, keyboard: InlineKeyboardMarkup):
    """پیش‌نمایش پست تبلیغی فقط برای چت خصوصی مدیر."""
    return await bot.send_message(chat_id=chat_id, text=c["post_text"], reply_markup=keyboard)


async def publish_ad_now(bot: Bot, repos: Repositories, channel_ref: Optional[str], campaign_id: int,
                         admin_id: int, expected_fingerprint: str) -> PublishResult:
    """انتشار پست تبلیغی. فراخواننده موظف است فقط پس از تأیید صریح مدیر آن را صدا بزند."""
    if not channel_ref:
        raise PublishError("کانال مقصد تنظیم نشده است (⚙️ تنظیمات).")
    c = repos.campaigns.get(campaign_id)
    if not c or c["kind"] != "ad":
        raise PublishError("تبلیغ پیدا نشد.")
    if c["status"] != "draft" or c["channel_message_id"]:
        raise PublishError("این تبلیغ قبلاً منتشر شده یا در حال انتشار است.")
    problems = ad_problems(c)
    if problems:
        raise PublishError("انتشار ممکن نیست: " + "؛ ".join(problems))
    if ad_fingerprint(c) != expected_fingerprint:
        raise PublishError("محتوای تبلیغ بعد از این پیش‌نمایش تغییر کرده است. دوباره پیش‌نمایش بگیرید و تأیید کنید.")
    try:
        members = await bot.get_chat_member_count(channel_ref)   # تعداد اعضا «قبل» از پست
    except Exception:  # noqa: BLE001 - اختیاری
        members = None
    if not repos.campaigns.claim_publishing(campaign_id):
        raise PublishError("این تبلیغ در حال انتشار است یا قبلاً منتشر شده است.")
    try:
        msg = await bot.send_message(chat_id=channel_ref, text=c["post_text"], reply_markup=ad_markup(c))
    except Forbidden:
        repos.campaigns.release_claim(campaign_id)
        raise PublishError("ربات اجازه ارسال در کانال را ندارد. ربات را ادمین کنید و Post Messages را روشن کنید.") from None
    except BadRequest:
        repos.campaigns.release_claim(campaign_id)
        raise PublishError("تلگرام ارسال را نپذیرفت. متن/دکمه و دسترسی ربات را بررسی کنید.") from None
    except (TimedOut, NetworkError):
        repos.logs.add("ad_publish_uncertain", admin_id, f"id={campaign_id}", level="error")
        raise PublishError("ارتباط حین ارسال قطع شد و معلوم نیست پست رفته یا نه. کانال را بررسی کنید.", uncertain=True) from None
    except TelegramError:
        repos.campaigns.release_claim(campaign_id)
        raise PublishError("ارسال به کانال ناموفق بود. کمی بعد دوباره تلاش کنید.") from None
    repos.campaigns.mark_published(campaign_id, msg.message_id, members)
    repos.logs.add("ad_published", admin_id, f"id={campaign_id} msg={msg.message_id}")
    return PublishResult(msg.message_id, post_url_for(channel_ref, msg.message_id))


# ---------------------------------------------------------------------------
# دریافت فایل آهنگ توسط مشترک ویژه: فقط به چت خود همان کاربر
# ---------------------------------------------------------------------------
async def send_song_to_user(bot: Bot, user_id: int, song: dict) -> bool:
    """فایل را فقط به چت خود کاربر می‌فرستد (با protect_content تا فوروارد/ذخیره نشود). فراخواننده مشترک بودن را بررسی می‌کند."""
    if not song.get("telegram_file_id"):
        return False
    try:
        await bot.send_audio(
            chat_id=user_id, audio=song["telegram_file_id"], caption=" - ".join(p for p in (song.get("artist"), song.get("title")) if p) or None,
            title=song.get("title"), performer=song.get("artist"), duration=song.get("duration_seconds"), protect_content=True,
        )
        return True
    except TelegramError:
        return False
