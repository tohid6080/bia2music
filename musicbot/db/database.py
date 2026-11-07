"""اتصال SQLite. تمام دسترسی‌ها از طریق Repositoryها است تا جابه‌جایی به PostgreSQL ساده بماند."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from musicbot.db import schema


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

    # --- اجرا ---
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    @property
    def total_changes(self) -> int:
        with self._lock:
            return self._conn.total_changes

    def backup(self, dest_path: str) -> None:
        """نسخه‌ی کاملاً سازگار از دیتابیس (حتی هنگام اجرا) در فایل مقصد."""
        import sqlite3

        dest = sqlite3.connect(dest_path)
        try:
            with self._lock:
                self._conn.backup(dest)
        finally:
            dest.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- مهاجرت و داده‌های اولیه ---
    def migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for version in sorted(schema.MIGRATIONS):
                if version > current:
                    self._conn.executescript(schema.MIGRATIONS[version])
                    self._conn.execute(f"PRAGMA user_version = {int(version)}")
            self._conn.commit()
            self._seed()

    def _seed(self) -> None:
        # فقط اگر خالی بود؛ ویرایش‌های بعدی مدیر بازنویسی نمی‌شود.
        if not self._conn.execute("SELECT 1 FROM languages LIMIT 1").fetchone():
            self._conn.executemany(
                "INSERT INTO languages(code,name_fa,sort_order) VALUES (?,?,?)",
                [(c, n, i) for i, (c, n) in enumerate(schema.SEED_LANGUAGES)],
            )
        if not self._conn.execute("SELECT 1 FROM genres LIMIT 1").fetchone():
            self._conn.executemany(
                "INSERT INTO genres(code,name_fa,sort_order) VALUES (?,?,?)",
                [(c, n, i) for i, (c, n) in enumerate(schema.SEED_GENRES)],
            )
        if not self._conn.execute("SELECT 1 FROM moods LIMIT 1").fetchone():
            self._conn.executemany(
                "INSERT INTO moods(code,name_fa,sort_order) VALUES (?,?,?)",
                [(c, n, i) for i, (c, n) in enumerate(schema.SEED_MOODS)],
            )
        self._conn.commit()
