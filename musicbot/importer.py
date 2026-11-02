"""درون‌ریزی آهنگ‌های قدیمی کانال به آرشیو.

ربات‌ها نمی‌توانند تاریخچه‌ی کانال را بخوانند؛ اما ربات ادمین کانال می‌تواند هر پست را با شماره‌اش
به چت خصوصی مدیر «فوروارد» کند. اینجا هر شماره فوروارد، خوانده و بلافاصله از چت مدیر پاک می‌شود.
مقصد فوروارد همیشه و فقط چت خود مدیر است؛ هیچ‌چیزی در کانال منتشر یا تغییر نمی‌کند."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from musicbot.db import Repositories
from musicbot.publishing.service import post_url_for
from musicbot.songs.service import extract_meta
from musicbot.songs.textutils import clean_text, normalize, parse_filename

log = logging.getLogger(__name__)
# فقط خطاهای «همین پست»؛ مثلاً «chat not found» (کانال اشتباه) نباید رد شود.
_SKIPPABLE = ("message to forward not found", "message not found", "can't be forwarded", "cannot be forwarded", "message_id_invalid")
_ALIASES = {"ایرانی": "fa", "فارسی": "fa", "ترکی": "tr", "انگلیسی": "en", "عربی": "ar"}


@dataclass
class ImportStats:
    scanned: int = 0
    imported: int = 0
    updated: int = 0      # آهنگ از قبل در ربات بود و اکنون «منتشرشده» شد
    duplicates: int = 0
    other: int = 0        # پست غیرصوتی
    missing: int = 0      # پست پاک‌شده/وجودنداشته
    errors: int = 0
    last_id: int = 0


def parse_message_number(text: str) -> Optional[int]:
    """شماره‌ی پست از لینک (t.me/name/123 یا t.me/c/123/456) یا عدد ساده."""
    # شماره باید یک بخش مستقل باشد (اول متن یا بعد از «/»)؛ تا عدد انتهای نام کاربری (bia2music1395) شماره حساب نشود.
    m = re.search(r"(?:^|/)(\d+)\s*/?\s*(?:\?.*)?$", (text or "").strip())
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 50_000_000 else None


def guess_categories(repos: Repositories, *texts: Optional[str]) -> dict:
    """تطبیق دقیق نام دسته‌ها (مثل «پاپ»، «غمگین») در عنوان/کپشن/هشتگ‌ها؛ فقط اگر یکتا و بدون ابهام باشد."""
    hay = f" {normalize(' '.join(t for t in texts if t))} "
    result: dict = {"language_code": None, "genre_id": None, "mood_id": None}

    def phrase(name: str) -> bool:
        n = normalize(name)
        return bool(n) and f" {n} " in hay

    langs = {it["key"] for it in repos.categories.list("languages") if not it["name_fa"].startswith("سایر") and phrase(it["name_fa"])}
    langs |= {code for alias, code in _ALIASES.items() if phrase(alias) and repos.categories.exists("languages", code)}
    if len(langs) == 1:
        result["language_code"] = next(iter(langs))
    for col, table in (("genre_id", "genres"), ("mood_id", "moods")):
        hits = [it["key"] for it in repos.categories.list(table) if not it["name_fa"].startswith("سایر") and phrase(it["name_fa"])]
        if len(hits) == 1:
            result[col] = hits[0]
    return result


class ChannelImporter:
    def __init__(self, bot, repos: Repositories, channel_ref: str, admin_id: int, *,
                 pace: float = 1.0, sleep: Callable[[float], Awaitable] = asyncio.sleep):
        self.bot, self.repos, self.channel_ref, self.admin_id = bot, repos, channel_ref, admin_id
        self.pace, self._sleep = pace, sleep

    async def run(self, start: int, end: int, stats: ImportStats, stop: asyncio.Event,
                  on_progress: Optional[Callable[[ImportStats], Awaitable]] = None, progress_every: int = 25) -> Optional[str]:
        """شماره‌های start..end را می‌خواند. خروجی: پیام خطای فارسی برای توقف اجباری، یا None."""
        for i in range(start, end + 1):
            if stop.is_set():
                return None
            try:
                await self._one(i, stats)
            except _Fatal as exc:
                return exc.message_fa
            stats.scanned += 1
            stats.last_id = i
            if on_progress and stats.scanned % progress_every == 0:
                await on_progress(stats)
            if self.pace:
                await self._sleep(self.pace)
        return None

    async def _forward(self, i: int):
        for attempt in range(6):
            try:
                # مقصد: فقط چت خود مدیر
                return await self.bot.forward_message(chat_id=self.admin_id, from_chat_id=self.channel_ref,
                                                      message_id=i, disable_notification=True)
            except RetryAfter as exc:
                await self._sleep(float(exc.retry_after) + 1)
            # توجه: BadRequest و Forbidden زیرمجموعه‌ی NetworkError هستند؛ پس باید «قبل» از آن بیایند.
            except Forbidden:
                raise _Fatal("ربات به کانال دسترسی ندارد. ربات را در کانال ادمین کنید.") from None
            except BadRequest as exc:
                if any(k in str(exc).lower() for k in _SKIPPABLE):
                    return None
                raise _Fatal("تلگرام درخواست را نپذیرفت (شناسه‌ی کانال یا دسترسی ربات را بررسی کنید).") from None
            except (TimedOut, NetworkError):
                await self._sleep(2 * (attempt + 1))
        raise _Soft()

    async def _one(self, i: int, stats: ImportStats) -> None:
        if self.repos.songs.find_by_channel_message(i):
            stats.duplicates += 1
            return
        try:
            msg = await self._forward(i)
        except _Soft:
            stats.errors += 1
            return
        if msg is None:
            stats.missing += 1
            return
        try:
            meta = extract_meta(msg)
            if meta is None:
                stats.other += 1
                return
            self._store(i, msg, meta, stats)
        finally:
            try:
                await self.bot.delete_message(self.admin_id, msg.message_id)
            except Exception:  # noqa: BLE001 - پیام موقت؛ اگر پاک نشد مهم نیست
                pass

    def _store(self, i: int, msg, meta, stats: ImportStats) -> None:
        songs = self.repos.songs
        url = post_url_for(self.channel_ref, i)
        existing = songs.find_by_unique_id(meta.file_unique_id)
        if existing:
            if existing["status"] in ("published",) or existing["channel_message_id"]:
                stats.duplicates += 1
            else:  # در ربات بود و پیش‌تر در کانال منتشر شده بود
                songs.mark_published(existing["id"], i, url)
                self.repos.queue.cancel_for_song(existing["id"], restore_song=False)
                stats.updated += 1
            return
        f_artist, f_title = parse_filename(meta.file_name)
        title = clean_text(meta.title) or f_title
        artist = clean_text(meta.performer) or f_artist
        caption = (getattr(msg, "caption", None) or "").strip()[:1024] or None
        guess = guess_categories(self.repos, title, artist, caption)
        songs.create_imported(
            title=title, artist=artist, telegram_file_id=meta.file_id, file_unique_id=meta.file_unique_id,
            duration_seconds=meta.duration, file_size=meta.file_size, caption=caption, message_id=i, post_url=url,
            created_by=self.admin_id, **guess)
        stats.imported += 1


class _Fatal(Exception):
    def __init__(self, message_fa: str):
        super().__init__(message_fa)
        self.message_fa = message_fa


class _Soft(Exception):
    pass


@dataclass
class ImportJob:
    """وضعیت اجرای فعلی (فقط یکی در هر زمان)."""

    mode: str                                   # test | full
    start: int
    end: int
    stats: ImportStats = field(default_factory=ImportStats)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None
    running: bool = True
    error: Optional[str] = None
