"""اعمال «دکمه‌ی ربات» روی پست‌های قبلی کانال (آهنگ‌های منتشرشده/واردشده).

فقط reply_markup (دکمه‌ی لینک) ویرایش می‌شود؛ متن/کپشن/فایل هرگز دست نمی‌خورد (بی‌اتلاف). مقصد فقط کانال تنظیم‌شده و فقط
پست‌هایی که در دیتابیس آهنگ منتشرشده‌اند. فقط با دکمه‌ی مدیر اجرا می‌شود. هر پست یک‌بار ثبت می‌شود تا ادامه/توقف امن باشد."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from musicbot.db import Repositories

log = logging.getLogger(__name__)
BATCH = 50
_NOT_MODIFIED = ("message is not modified",)
_UNEDITABLE = ("message to edit not found", "message can't be edited", "message_id_invalid", "message not found", "there is no reply markup")


@dataclass
class BackfillStats:
    scanned: int = 0
    done: int = 0           # دکمه اعمال/برداشته شد
    already: int = 0        # همان دکمه از قبل بود
    skipped: int = 0        # پست پاک‌شده/غیرقابل‌ویرایش
    errors: int = 0


@dataclass
class BackfillJob:
    mode: str                                   # apply | remove
    limit: Optional[int]                        # None = همه؛ ۱ = آزمایش
    stats: BackfillStats = field(default_factory=BackfillStats)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None
    running: bool = True
    error: Optional[str] = None


class PromoBackfill:
    def __init__(self, bot, repos: Repositories, channel_ref: str, markup: Optional[InlineKeyboardMarkup], *,
                 pace: float = 1.5, sleep: Callable[[float], Awaitable] = asyncio.sleep):
        self.bot, self.repos, self.channel_ref, self.markup = bot, repos, channel_ref, markup
        self.pace, self._sleep = pace, sleep

    async def run(self, mode: str, limit: Optional[int], stats: BackfillStats, stop: asyncio.Event,
                  on_progress: Optional[Callable[[BackfillStats], Awaitable]] = None) -> Optional[str]:
        """خروجی: پیام خطای فارسی برای توقف اجباری، یا None."""
        if mode == "apply" and self.markup is None:
            return "دکمه‌ی ربات خاموش است یا نام کاربری ربات هنوز مشخص نشده."
        done_total = 0
        attempted: set[int] = set()                 # پست‌هایی که در همین اجرا امتحان شده‌اند (برای جلوگیری از حلقه‌ی بی‌پایان روی خطای شبکه)
        while not stop.is_set():
            want = BATCH if limit is None else min(BATCH, limit - done_total)
            batch = [t for t in self.repos.songs.promo_targets(mode, want + len(attempted)) if t["channel_message_id"] not in attempted][:want]
            if not batch or (limit is not None and done_total >= limit):
                return None
            for t in batch:
                if stop.is_set() or (limit is not None and done_total >= limit):
                    return None
                try:
                    await self._one(mode, t["channel_message_id"], stats)
                except _Fatal as exc:
                    return exc.message_fa
                attempted.add(t["channel_message_id"])
                stats.scanned += 1
                done_total += 1
                if on_progress and stats.scanned % 20 == 0:
                    await on_progress(stats)
                if self.pace:
                    await self._sleep(self.pace)
        return None

    async def _edit(self, message_id: int, markup: Optional[InlineKeyboardMarkup]) -> None:
        for attempt in range(6):
            try:
                await self.bot.edit_message_reply_markup(chat_id=self.channel_ref, message_id=message_id, reply_markup=markup)
                return
            except RetryAfter as exc:
                await self._sleep(float(exc.retry_after) + 1)
            # BadRequest و Forbidden زیرمجموعه‌ی NetworkError هستند؛ پس باید قبل از آن بیایند.
            except Forbidden:
                raise _Fatal("ربات اجازه‌ی ویرایش پست‌های کانال را ندارد. در کانال، ربات را ادمین کنید و «Edit messages of others» را روشن کنید.") from None
            except BadRequest as exc:
                low = str(exc).lower()
                if any(k in low for k in _NOT_MODIFIED):
                    raise _AlreadyThere from None
                if any(k in low for k in _UNEDITABLE):
                    raise _Uneditable from None
                raise _Fatal("تلگرام ویرایش را نپذیرفت (کانال مقصد یا دسترسی ربات را بررسی کنید).") from None
            except (TimedOut, NetworkError):
                await self._sleep(2 * (attempt + 1))
        raise _Soft()

    async def _one(self, mode: str, message_id: int, stats: BackfillStats) -> None:
        marker = self.repos.songs.promo_mark
        try:
            await self._edit(message_id, self.markup if mode == "apply" else None)
        except _AlreadyThere:
            stats.already += 1
            marker(message_id, "applied" if mode == "apply" else None)
        except _Uneditable:
            stats.skipped += 1
            marker(message_id, "skipped" if mode == "apply" else None)
        except _Soft:
            stats.errors += 1                       # علامت نمی‌خورد؛ دور بعد دوباره امتحان می‌شود
        else:
            stats.done += 1
            marker(message_id, "applied" if mode == "apply" else None)


class _Fatal(Exception):
    def __init__(self, message_fa: str):
        super().__init__(message_fa)
        self.message_fa = message_fa


class _Soft(Exception):
    pass


class _AlreadyThere(Exception):
    pass


class _Uneditable(Exception):
    pass
