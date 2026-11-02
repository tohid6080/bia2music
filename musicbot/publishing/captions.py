"""کپشن و هشتگ: تولید با AI Provider (فعلاً قالب و قوانین)، ذخیره، و ساخت متن نهایی پست."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from musicbot.ai import CaptionRequest

MAX_CAPTION = 1024   # سقف کپشن فایل صوتی در تلگرام
MAX_HASHTAGS = 15


def request_from_song(song: dict) -> CaptionRequest:
    return CaptionRequest(
        title=song.get("title"), artist=song.get("artist"), language=song.get("language_name"),
        genre=song.get("genre_name"), mood=song.get("mood_name"),
    )


def normalize_hashtags(text: str) -> list[str]:
    """ورودی آزاد (با فاصله/کاما/خط جدید) ← فهرست هشتگ‌های تمیز و بدون تکرار."""
    out: list[str] = []
    for raw in re.split(r"[\s,،]+", text or ""):
        tag = re.sub(r"[^\w‌]", "", raw.lstrip("#"), flags=re.UNICODE).replace("‌", "_")
        tag = tag.strip("_")
        if tag and f"#{tag}" not in out:
            out.append(f"#{tag}")
    return out[:MAX_HASHTAGS]


@dataclass(frozen=True)
class PostOptions:
    """افزوده‌های ثابت پست (معرفی ربات). جزو اثر انگشت‌اند تا پیش‌نمایش و انتشار یکسان بمانند."""

    footer: Optional[str] = None
    button_url: Optional[str] = None
    button_label: str = "🔍 جست‌وجو و پیشنهاد آهنگ در ربات"


def post_markup(opts: Optional[PostOptions]) -> Optional[InlineKeyboardMarkup]:
    if opts and opts.button_url:
        return InlineKeyboardMarkup([[InlineKeyboardButton(opts.button_label, url=opts.button_url)]])
    return None


def final_caption(song: dict, opts: Optional[PostOptions] = None) -> str:
    parts = [(song.get("caption") or "").strip(), (song.get("hashtags") or "").strip(), (opts.footer or "") if opts else ""]
    return "\n\n".join(p for p in parts if p)


def fingerprint(song: dict, opts: Optional[PostOptions] = None) -> str:
    """اثر انگشت محتوای پست؛ انتشار فقط وقتی مجاز است که با پیش‌نمایش دیده‌شده یکی باشد."""
    raw = "\x00".join([str(song.get(k) or "") for k in ("caption", "hashtags", "title", "artist", "file_unique_id")]
                      + ([opts.footer or "", opts.button_url or ""] if opts else []))
    return hashlib.sha1(raw.encode()).hexdigest()[:8]


async def ensure_caption(ctx, song_id: int, force: bool = False) -> Optional[bool]:
    """اگر کپشن نبود (یا force) می‌سازد. خروجی: is_real_ai مولد، یا None اگر کاری نشد."""
    song = ctx.repos.songs.get(song_id)
    if not song or (song.get("caption") and not force):
        return None
    req = request_from_song(song)
    result = await ctx.caption_provider().generate_caption(req)
    ctx.repos.songs.update(song_id, caption=result.caption, hashtags=" ".join(result.hashtags))
    return result.is_real_ai
