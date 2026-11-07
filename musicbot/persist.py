"""پایداری دیتابیس روی میزبانِ رایگانی که دیسکش موقت است (با هر خواب/استقرار پاک می‌شود).

ایده: نسخه‌ی پشتیبان دیتابیس به‌صورت فایل برای خودِ مدیر فرستاده و «پین» می‌شود. هنگام راه‌اندازی، اگر فایل دیتابیس نبود،
آخرین پیام پین‌شده‌ی مدیر خوانده و دیتابیس از آن بازیابی می‌شود. فقط به چت مدیر ارسال می‌شود؛ هیچ سرویس بیرونی‌ای لازم نیست.
محدودیت صادقانه: تغییرات بین آخرین پشتیبان و خوابیدن/خاموشی ناگهانی ممکن است از دست برود (پشتیبان هر ≥۱۰ دقیقه پس از تغییر و هنگام خاموشی).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from musicbot.db import schema

log = logging.getLogger(__name__)
PREFIX = "musicbot-backup-"
MIN_INTERVAL = 600


def valid_backup(path: str) -> bool:
    """فایل واقعاً یک دیتابیس سالم و نه جدیدتر از این نسخه‌ی برنامه است."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            return {"songs", "users", "admins"} <= tables and con.execute("PRAGMA user_version").fetchone()[0] <= max(schema.MIGRATIONS)
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _is_backup_doc(msg) -> bool:
    doc = getattr(msg, "document", None)
    return bool(doc and (doc.file_name or "").startswith(PREFIX))


async def restore_if_missing(bot, settings) -> str:
    """نتیجه: exists | restored | none | invalid | error. هیچ‌گاه دیتابیس موجود را بازنویسی نمی‌کند."""
    path = Path(settings.database_path)
    if path.exists() and path.stat().st_size > 0:
        return "exists"
    try:
        chat = await bot.get_chat(settings.admin_user_id)
        pm = getattr(chat, "pinned_message", None)
        if not pm or not _is_backup_doc(pm):
            return "none"
        tg_file = await bot.get_file(pm.document.file_id)
        tmp = tempfile.mkdtemp(prefix="musicbot-restore-")
        try:
            dest = os.path.join(tmp, "restore.sqlite3")
            await tg_file.download_to_drive(dest)
            if not valid_backup(dest):
                log.error("پشتیبان پین‌شده معتبر نیست؛ بازیابی انجام نشد.")
                return "invalid"
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dest, path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        log.info("دیتابیس از پشتیبان پین‌شده بازیابی شد.")
        return "restored"
    except Exception:  # noqa: BLE001
        log.exception("بازیابی از پشتیبان ناموفق بود")
        return "error"


class TelegramBackup:
    def __init__(self, bot, repos, settings, now=lambda: datetime.now(timezone.utc)):
        self.bot, self.repos, self.settings, self.now = bot, repos, settings, now
        self.last_changes = repos.db.total_changes          # تغییرات شروع (مهاجرت/seed) پشتیبان نمی‌خواهند
        self.last_at: Optional[datetime] = None
        self.last_error: Optional[str] = None

    def dirty(self) -> bool:
        return self.repos.db.total_changes != self.last_changes

    async def maybe_backup(self, *, final: bool = False) -> bool:
        if not self.dirty():
            return False
        if not final and self.last_at and (self.now() - self.last_at).total_seconds() < MIN_INTERVAL:
            return False
        return await self.backup_now()

    async def backup_now(self) -> bool:
        changes = self.repos.db.total_changes
        tmp = tempfile.mkdtemp(prefix="musicbot-bk-")
        try:
            name = f"{PREFIX}{self.now():%Y%m%d-%H%M}.sqlite3"
            path = os.path.join(tmp, name)
            self.repos.db.backup(path)
            old = None
            try:
                chat = await self.bot.get_chat(self.settings.admin_user_id)
                old = getattr(chat, "pinned_message", None)
            except Exception:  # noqa: BLE001
                old = None
            with open(path, "rb") as fh:
                msg = await self.bot.send_document(chat_id=self.settings.admin_user_id, document=fh, filename=name, disable_notification=True,
                                                   caption="💾 پشتیبان خودکار (پین‌شده؛ برای بازیابی پس از پاک‌شدن دیسک میزبان). شامل شناسه‌ی کاربران است؛ پاکش نکنید.")
            await self.bot.pin_chat_message(chat_id=self.settings.admin_user_id, message_id=msg.message_id, disable_notification=True)
            if old is not None and _is_backup_doc(old) and old.message_id != msg.message_id:
                try:
                    await self.bot.delete_message(chat_id=self.settings.admin_user_id, message_id=old.message_id)
                except Exception:  # noqa: BLE001
                    pass                                   # پیام قدیمی (>۴۸ ساعت) حذف‌نشدنی است؛ مشکلی نیست
            self.last_changes, self.last_at, self.last_error = changes, self.now(), None
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = type(exc).__name__
            log.exception("پشتیبان خودکار ناموفق بود")
            return False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


async def backup_loop(backup: TelegramBackup, interval: int = 300) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await backup.maybe_backup()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("backup loop")
