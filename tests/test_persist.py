"""پایداری روی میزبان با دیسک موقت: بازیابی از پشتیبان پین‌شده و پشتیبان خودکار (فقط چت مدیر)."""
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from musicbot import persist
from musicbot.config import ConfigError, load_settings
from musicbot.db import Database, Repositories
from tests.conftest import ADMIN

T0 = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def make_db(path):
    db = Database(str(path))
    db.migrate()
    repos = Repositories(db)
    return db, repos


def good_backup(tmp_path):
    db, repos = make_db(tmp_path / "src.sqlite3")
    repos.songs.create(title="شب", artist="علی", telegram_file_id="F", file_unique_id="u1")
    out = tmp_path / "bk.sqlite3"
    db.backup(str(out))
    db.close()
    return out


class FakeBot:
    def __init__(self, pinned=None, backup_file=None):
        self.pinned, self.backup_file = pinned, backup_file
        self.sent, self.pins, self.deleted, self.chats = [], [], [], []
        self._id = 100

    async def get_chat(self, chat_id):
        self.chats.append(chat_id)
        return SimpleNamespace(pinned_message=self.pinned)

    async def get_file(self, file_id):
        src = self.backup_file

        async def dl(dest):
            import shutil
            shutil.copyfile(src, dest)
        return SimpleNamespace(download_to_drive=dl)

    async def send_document(self, chat_id, document, filename, **kw):
        self._id += 1
        self.sent.append((chat_id, filename, document.read(13)))
        return SimpleNamespace(message_id=self._id, document=SimpleNamespace(file_name=filename, file_id=f"fid{self._id}"))

    async def pin_chat_message(self, chat_id, message_id, **kw):
        self.pins.append((chat_id, message_id))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


def pinned_doc(name=persist.PREFIX + "20261101-1000.sqlite3", mid=7):
    return SimpleNamespace(message_id=mid, document=SimpleNamespace(file_name=name, file_id="fidx"))


def settings(tmp_path, **env):
    base = {"TELEGRAM_BOT_TOKEN": "123456:" + "A" * 35, "ADMIN_USER_ID": str(ADMIN), "DATABASE_PATH": str(tmp_path / "data" / "m.sqlite3")}
    base.update(env)
    return load_settings(base, load_dotenv_file=False)


# ---------- config ----------
def test_config_webhook_and_backup_flags(tmp_path):
    st = settings(tmp_path)
    assert st.webhook_url is None and st.telegram_backup is False and st.port == 8080
    st = settings(tmp_path, WEBHOOK_URL="https://my-bot.example.com/", PORT="10000")
    assert st.webhook_url == "https://my-bot.example.com" and st.telegram_backup is True and st.port == 10000
    assert settings(tmp_path, WEBHOOK_URL="https://x.example", TELEGRAM_BACKUP="0").telegram_backup is False
    with pytest.raises(ConfigError, match="https"):
        settings(tmp_path, WEBHOOK_URL="http://x.example")
    with pytest.raises(ConfigError, match="PORT"):
        settings(tmp_path, PORT="abc")


# ---------- restore ----------
async def test_restore_when_db_missing(tmp_path):
    st = settings(tmp_path)
    bot = FakeBot(pinned=pinned_doc(), backup_file=good_backup(tmp_path))
    assert await persist.restore_if_missing(bot, st) == "restored"
    assert bot.chats == [ADMIN]                                     # فقط چت مدیر خوانده شد
    db, repos = make_db(st.database_path)
    assert repos.songs.all_with_status("draft", 10) or db.fetchone("SELECT COUNT(*) c FROM songs")["c"] == 1


async def test_restore_never_overwrites_existing_db(tmp_path):
    st = settings(tmp_path)
    db, _ = make_db(st.database_path)
    db.close()
    before = st.database_path.read_bytes()
    bot = FakeBot(pinned=pinned_doc(), backup_file=good_backup(tmp_path))
    assert await persist.restore_if_missing(bot, st) == "exists"
    assert st.database_path.read_bytes() == before and bot.chats == []


async def test_restore_ignores_unrelated_or_missing_pin(tmp_path):
    st = settings(tmp_path)
    assert await persist.restore_if_missing(FakeBot(pinned=None), st) == "none"
    assert await persist.restore_if_missing(FakeBot(pinned=pinned_doc(name="photo.pdf")), st) == "none"
    assert not st.database_path.exists()


async def test_restore_rejects_corrupt_and_newer_schema(tmp_path):
    st = settings(tmp_path)
    junk = tmp_path / "junk.sqlite3"
    junk.write_bytes(b"not a database at all" * 50)
    assert await persist.restore_if_missing(FakeBot(pinned=pinned_doc(), backup_file=junk), st) == "invalid"
    assert not st.database_path.exists()
    newer = good_backup(tmp_path)
    con = sqlite3.connect(newer)
    con.execute("PRAGMA user_version = 999")
    con.commit()
    con.close()
    assert await persist.restore_if_missing(FakeBot(pinned=pinned_doc(), backup_file=newer), st) == "invalid"
    assert not st.database_path.exists()


async def test_restore_errors_are_contained(tmp_path):
    st = settings(tmp_path)
    bot = FakeBot()
    bot.get_chat = AsyncMock(side_effect=RuntimeError("telegram down"))
    assert await persist.restore_if_missing(bot, st) == "error"


# ---------- backup ----------
async def test_backup_sends_pins_and_replaces_old_only_to_admin(tmp_path):
    st = settings(tmp_path, WEBHOOK_URL="https://x.example")
    db, repos = make_db(st.database_path)
    bot = FakeBot(pinned=pinned_doc(mid=7))
    b = persist.TelegramBackup(bot, repos, st, now=lambda: T0)
    assert b.dirty() is False and await b.maybe_backup() is False and bot.sent == []       # بدون تغییر ← پشتیبان نمی‌خواهد
    repos.songs.create(title="t", artist="a", telegram_file_id="F", file_unique_id="x1")
    assert b.dirty() and await b.maybe_backup() is True
    assert [c[0] for c in bot.sent] == [ADMIN] and bot.sent[0][2].startswith(b"SQLite format")
    assert bot.pins == [(ADMIN, 101)] and bot.deleted == [(ADMIN, 7)]                       # قدیمی جایگزین شد
    assert b.dirty() is False


async def test_backup_debounce_and_final_bypass(tmp_path):
    st = settings(tmp_path, WEBHOOK_URL="https://x.example")
    db, repos = make_db(st.database_path)
    bot = FakeBot()
    clock = {"t": T0}
    b = persist.TelegramBackup(bot, repos, st, now=lambda: clock["t"])
    repos.songs.create(title="t1", artist="a", telegram_file_id="F", file_unique_id="y1")
    assert await b.maybe_backup() is True
    repos.songs.create(title="t2", artist="a", telegram_file_id="F", file_unique_id="y2")
    clock["t"] += timedelta(minutes=2)
    assert await b.maybe_backup() is False and len(bot.sent) == 1                           # زود است
    assert await b.maybe_backup(final=True) is True and len(bot.sent) == 2                  # خاموشی ← بی‌درنگ
    repos.songs.create(title="t3", artist="a", telegram_file_id="F", file_unique_id="y3")
    clock["t"] += timedelta(minutes=11)
    assert await b.maybe_backup() is True


async def test_backup_failure_is_contained_and_retried(tmp_path):
    st = settings(tmp_path, WEBHOOK_URL="https://x.example")
    db, repos = make_db(st.database_path)
    bot = FakeBot()
    bot.send_document = AsyncMock(side_effect=RuntimeError("blocked"))
    b = persist.TelegramBackup(bot, repos, st, now=lambda: T0)
    repos.songs.create(title="t", artist="a", telegram_file_id="F", file_unique_id="z1")
    assert await b.maybe_backup() is False and b.last_error == "RuntimeError" and b.dirty()  # علامت «پشتیبان‌شده» نخورد
    bot.send_document = FakeBot().send_document
    assert await b.maybe_backup() is True


def test_valid_backup_checks(tmp_path):
    assert persist.valid_backup(str(good_backup(tmp_path))) is True
    assert persist.valid_backup(str(tmp_path / "missing.sqlite3")) is False


def test_dockerfile_has_no_secrets_and_ignores_env():
    from pathlib import Path

    root = Path(__file__).parent.parent
    df = (root / "Dockerfile").read_text()
    assert "TELEGRAM_BOT_TOKEN=" not in df and "ADMIN_USER_ID=" not in df and "COPY .env" not in df
    assert ".env" in (root / ".dockerignore").read_text().splitlines()
