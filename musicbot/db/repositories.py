"""Repositoryها: تنها جایی که SQL نوشته می‌شود."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from musicbot.db.database import Database


@dataclass(frozen=True)
class ChannelSetting:
    id: int
    channel_ref: str
    title: Optional[str]
    last_checked_at: Optional[str]


class ActivityLogRepo:
    def __init__(self, db: Database):
        self.db = db

    def add(self, action: str, actor_user_id: Optional[int] = None, details: Optional[str] = None, level: str = "info") -> None:
        # details نباید شامل رازها باشد؛ فراخواننده مسئول است.
        self.db.execute(
            "INSERT INTO activity_logs(actor_user_id,action,details,level) VALUES (?,?,?,?)",
            (actor_user_id, action, details, level),
        )

    def recent(self, limit: int = 10) -> list[dict]:
        rows = self.db.fetchall("SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


class AdminRepo:
    def __init__(self, db: Database):
        self.db = db

    def ensure_owner(self, telegram_user_id: int) -> None:
        self.db.execute(
            "INSERT INTO admins(telegram_user_id, role) VALUES (?, 'owner') "
            "ON CONFLICT(telegram_user_id) DO UPDATE SET is_active=1",
            (telegram_user_id,),
        )
        # هر مدیر دیگری که در ENV نیست در مرحله اول غیرفعال می‌شود.
        self.db.execute("UPDATE admins SET is_active=0 WHERE telegram_user_id<>? AND role='owner'", (telegram_user_id,))

    def is_active_admin(self, telegram_user_id: int) -> bool:
        row = self.db.fetchone("SELECT 1 FROM admins WHERE telegram_user_id=? AND is_active=1", (telegram_user_id,))
        return row is not None


class UserRepo:
    def __init__(self, db: Database):
        self.db = db

    def touch(self, telegram_user_id: int, username: Optional[str], first_name: Optional[str], language_code: Optional[str]) -> None:
        self.db.execute(
            "INSERT INTO users(telegram_user_id,username,first_name,language_code) VALUES (?,?,?,?) "
            "ON CONFLICT(telegram_user_id) DO UPDATE SET username=excluded.username, "
            "first_name=excluded.first_name, last_seen_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')",
            (telegram_user_id, username, first_name, language_code),
        )

    def count(self) -> int:
        return self.db.fetchone("SELECT COUNT(*) c FROM users")["c"]

    def get(self, telegram_user_id: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM users WHERE telegram_user_id=?", (telegram_user_id,))
        return dict(row) if row else None

    def is_blocked(self, telegram_user_id: int) -> bool:
        row = self.db.fetchone("SELECT is_blocked FROM users WHERE telegram_user_id=?", (telegram_user_id,))
        return bool(row and row["is_blocked"])

    def set_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        self.db.execute("UPDATE users SET is_blocked=? WHERE telegram_user_id=?", (1 if blocked else 0, telegram_user_id))

    def recent(self, limit: int = 10, exclude: Optional[int] = None) -> list[dict]:
        rows = self.db.fetchall("SELECT * FROM users WHERE telegram_user_id<>? ORDER BY last_seen_at DESC LIMIT ?", (exclude or 0, limit))
        return [dict(r) for r in rows]

    def stats(self, exclude: Optional[int] = None) -> dict:
        ex = exclude or 0
        q = lambda w: self.db.fetchone(f"SELECT COUNT(*) c FROM users WHERE telegram_user_id<>? {w}", (ex,))["c"]  # noqa: E731
        return {
            "total": q(""),
            "active_7d": q("AND last_seen_at>=strftime('%Y-%m-%dT%H:%M:%SZ','now','-7 day')"),
            "consented": q("AND consent_at IS NOT NULL"),
            "blocked": q("AND is_blocked=1"),
        }


class ChannelSettingsRepo:
    def __init__(self, db: Database):
        self.db = db

    def get_active(self) -> Optional[ChannelSetting]:
        row = self.db.fetchone("SELECT * FROM channel_settings WHERE is_active=1 ORDER BY id DESC LIMIT 1")
        if not row:
            return None
        return ChannelSetting(row["id"], row["channel_ref"], row["title"], row["last_checked_at"])

    def set_active(self, channel_ref: str, title: Optional[str]) -> None:
        with self.db._lock:
            self.db._conn.execute("UPDATE channel_settings SET is_active=0, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE is_active=1")
            self.db._conn.execute(
                "INSERT INTO channel_settings(channel_ref,title,is_active) VALUES (?,?,1)", (channel_ref, title)
            )
            self.db._conn.commit()

    def mark_checked(self) -> None:
        self.db.execute(
            "UPDATE channel_settings SET last_checked_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE is_active=1"
        )


class AISettingsRepo:
    def __init__(self, db: Database):
        self.db = db

    def set(self, key: str, value: Optional[str]) -> None:
        self.db.execute(
            "INSERT INTO ai_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET "
            "value=excluded.value, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')",
            (key, value),
        )

    def get(self, key: str) -> Optional[str]:
        row = self.db.fetchone("SELECT value FROM ai_settings WHERE key=?", (key,))
        return row["value"] if row else None


_SONG_SELECT = (
    "SELECT s.*, l.name_fa AS language_name, g.name_fa AS genre_name, m.name_fa AS mood_name "
    "FROM songs s LEFT JOIN languages l ON l.code=s.language_code "
    "LEFT JOIN genres g ON g.id=s.genre_id LEFT JOIN moods m ON m.id=s.mood_id"
)
_UPDATABLE = {"title", "artist", "language_code", "genre_id", "mood_id", "status", "caption", "hashtags"}
STATUSES = ("draft", "ready", "scheduled", "publishing", "published", "archived")
_CATEGORY_TABLES = {"languages": "code", "genres": "id", "moods": "id"}


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class SongRepo:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _norm(text):
        from musicbot.songs.textutils import normalize

        return normalize(text) or None

    def create(self, *, title, artist, telegram_file_id=None, file_unique_id=None, file_hash=None,
               duration_seconds=None, file_size=None, created_by=None) -> int:
        cur = self.db.execute(
            "INSERT INTO songs(title,artist,title_norm,artist_norm,telegram_file_id,file_unique_id,file_hash,"
            "duration_seconds,file_size,created_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title, artist, self._norm(title), self._norm(artist), telegram_file_id, file_unique_id,
             file_hash, duration_seconds, file_size, created_by),
        )
        return cur.lastrowid

    def get(self, song_id: int) -> Optional[dict]:
        row = self.db.fetchone(_SONG_SELECT + " WHERE s.id=?", (song_id,))
        return dict(row) if row else None

    def find_by_unique_id(self, uid: str) -> Optional[dict]:
        row = self.db.fetchone(_SONG_SELECT + " WHERE s.file_unique_id=?", (uid,))
        return dict(row) if row else None

    def find_by_norm(self, title_norm: Optional[str], artist_norm: Optional[str]) -> Optional[dict]:
        """آهنگ هم‌نام در آرشیو (هر وضعیتی): جفت دقیق خواننده+عنوان، یا همان عنوان با خوانندهٔ شامل‌شونده. بدون خواننده فقط تطبیق دقیق بدون خواننده."""
        if not title_norm:
            return None
        if artist_norm:
            row = self.db.fetchone(
                _SONG_SELECT + " WHERE s.title_norm=? AND s.artist_norm IS NOT NULL AND s.artist_norm<>'' AND "
                "(s.artist_norm=? OR instr(s.artist_norm, ?)>0 OR instr(?, s.artist_norm)>0) LIMIT 1",
                (title_norm, artist_norm, artist_norm, artist_norm))
        else:
            row = self.db.fetchone(_SONG_SELECT + " WHERE s.title_norm=? AND (s.artist_norm IS NULL OR s.artist_norm='') LIMIT 1", (title_norm,))
        return dict(row) if row else None

    def find_fileless_match(self, title_norm: Optional[str], artist_norm: Optional[str]) -> Optional[dict]:
        """آهنگ بدون فایل (ساخته‌شده از رادار) که عنوان و خواننده‌اش دقیقاً با فایل تازه‌رسیده یکی است."""
        if not title_norm or not artist_norm:
            return None
        row = self.db.fetchone(_SONG_SELECT + " WHERE s.telegram_file_id IS NULL AND s.title_norm=? AND s.artist_norm=? AND s.status IN ('draft','ready') "
                               "ORDER BY s.id LIMIT 1", (title_norm, artist_norm))
        return dict(row) if row else None

    def attach_file(self, song_id: int, file_id: str, unique_id: str, file_hash, duration, size) -> None:
        self.db.execute("UPDATE songs SET telegram_file_id=?, file_unique_id=?, file_hash=?, duration_seconds=?, file_size=?, "
                        "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=? AND telegram_file_id IS NULL",
                        (file_id, unique_id, file_hash, duration, size, song_id))

    def find_by_hash(self, file_hash: str) -> Optional[dict]:
        row = self.db.fetchone(_SONG_SELECT + " WHERE s.file_hash=? LIMIT 1", (file_hash,))
        return dict(row) if row else None

    def find_similar(self, song: dict) -> list[dict]:
        """آهنگ دیگری با همان عنوان و خوانندهٔ نرمال‌شده (فایل متفاوت)."""
        if not song.get("title_norm") or not song.get("artist_norm"):
            return []
        rows = self.db.fetchall(
            _SONG_SELECT + " WHERE s.title_norm=? AND s.artist_norm=? AND s.id<>? ORDER BY s.id",
            (song["title_norm"], song["artist_norm"], song["id"]),
        )
        return [dict(r) for r in rows]

    def update(self, song_id: int, **fields) -> None:
        bad = set(fields) - _UPDATABLE
        if bad:
            raise ValueError(f"فیلد غیرمجاز: {bad}")
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError("وضعیت نامعتبر")
        cols = dict(fields)
        if "title" in fields:
            cols["title_norm"] = self._norm(fields["title"])
        if "artist" in fields:
            cols["artist_norm"] = self._norm(fields["artist"])
        sets = ", ".join(f"{c}=?" for c in cols)
        self.db.execute(
            f"UPDATE songs SET {sets}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
            (*cols.values(), song_id),
        )

    # --- انتشار: فقط از طریق این متدها (مسیر Publisher) ---
    def claim_for_publishing(self, song_id: int) -> Optional[str]:
        """قفل اتمیک: آهنگ آماده/زمان‌بندی‌شده را «در حال انتشار» می‌کند و وضعیت قبلی را برمی‌گرداند."""
        with self.db._lock:
            row = self.db._conn.execute("SELECT status, channel_message_id FROM songs WHERE id=?", (song_id,)).fetchone()
            if not row or row["status"] not in ("ready", "scheduled") or row["channel_message_id"] is not None:
                return None
            self.db._conn.execute("UPDATE songs SET status='publishing' WHERE id=?", (song_id,))
            self.db._conn.commit()
            return row["status"]

    def release_claim(self, song_id: int, previous_status: str) -> None:
        self.db.execute("UPDATE songs SET status=? WHERE id=? AND status='publishing'", (previous_status, song_id))

    def mark_published(self, song_id: int, message_id: int, post_url: Optional[str]) -> None:
        self.db.execute(
            "UPDATE songs SET status='published', channel_message_id=?, post_url=?, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
            (message_id, post_url, song_id),
        )

    def delete(self, song_id: int) -> None:
        with self.db._lock:
            self.db._conn.execute("DELETE FROM publication_queue WHERE song_id=?", (song_id,))
            self.db._conn.execute("DELETE FROM songs WHERE id=?", (song_id,))
            self.db._conn.commit()

    # --- فهرست و جست‌وجو ---
    @staticmethod
    def _where(flt: str, q_norm: Optional[str]) -> tuple[str, tuple]:
        if flt == "all":
            return "1=1", ()
        if flt in ("draft", "ready", "scheduled", "published"):
            return "s.status=?", (flt,)
        if flt == "nolang":  # منتشرشده‌های بدون زبان (برای دسته‌بندی آرشیو واردشده)
            return "(s.status='published' AND s.language_code IS NULL)", ()
        if flt == "q":
            if not q_norm:
                raise ValueError("empty query")
            like = _like(q_norm)
            return "(s.title_norm LIKE ? ESCAPE '\\' OR s.artist_norm LIKE ? ESCAPE '\\')", (like, like)
        kind, _, val = flt.partition(".")
        if kind == "l" and val:
            return "s.language_code=?", (val,)
        if kind in ("g", "m") and val.isdigit():
            return ("s.genre_id=?" if kind == "g" else "s.mood_id=?"), (int(val),)
        raise ValueError("فیلتر نامعتبر")

    PUBLIC = "s.status='published'"

    def list(self, flt: str = "all", q_norm: Optional[str] = None, limit: int = 8, offset: int = 0,
             published_only: bool = False) -> list[dict]:
        where, params = self._where(flt, q_norm)
        if published_only:
            where = f"{self.PUBLIC} AND ({where})"
        rows = self.db.fetchall(_SONG_SELECT + f" WHERE {where} ORDER BY s.id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
        return [dict(r) for r in rows]

    def count(self, flt: str = "all", q_norm: Optional[str] = None, published_only: bool = False) -> int:
        where, params = self._where(flt, q_norm)
        if published_only:
            where = f"{self.PUBLIC} AND ({where})"
        return self.db.fetchone(f"SELECT COUNT(*) c FROM songs s WHERE {where}", params)["c"]

    # --- درون‌ریزی از کانال و دسته‌بندی سریع ---
    def find_by_channel_message(self, message_id: int) -> Optional[dict]:
        row = self.db.fetchone(_SONG_SELECT + " WHERE s.channel_message_id=? LIMIT 1", (message_id,))
        return dict(row) if row else None

    def create_imported(self, *, title, artist, telegram_file_id, file_unique_id, duration_seconds, file_size,
                        caption, message_id, post_url, language_code=None, genre_id=None, mood_id=None, created_by=None) -> int:
        cur = self.db.execute(
            "INSERT INTO songs(title,artist,title_norm,artist_norm,telegram_file_id,file_unique_id,duration_seconds,file_size,"
            "caption,status,channel_message_id,post_url,language_code,genre_id,mood_id,created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,'published',?,?,?,?,?,?)",
            (title, artist, self._norm(title), self._norm(artist), telegram_file_id, file_unique_id, duration_seconds,
             file_size, caption, message_id, post_url, language_code, genre_id, mood_id, created_by))
        return cur.lastrowid

    def ai_candidates(self, limit: int) -> list[dict]:
        """منتشرشده‌هایی که هنوز AI بررسی نکرده و حداقل یکی از زبان/سبک/حال‌وهوایشان خالی است."""
        rows = self.db.fetchall(
            "SELECT id, title, artist, language_code, genre_id, mood_id FROM songs WHERE status='published' AND ai_checked=0 "
            "AND (title IS NOT NULL OR artist IS NOT NULL) AND (language_code IS NULL OR genre_id IS NULL OR mood_id IS NULL) "
            "ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def ai_candidates_count(self) -> int:
        return self.db.fetchone(
            "SELECT COUNT(*) c FROM songs WHERE status='published' AND ai_checked=0 AND (title IS NOT NULL OR artist IS NOT NULL) "
            "AND (language_code IS NULL OR genre_id IS NULL OR mood_id IS NULL)")["c"]

    def apply_ai_guess(self, song_id: int, language, genre, mood) -> int:
        """فقط فیلدهای «خالی» پر می‌شود (هرگز بازنویسی نمی‌کند) و آهنگ بررسی‌شده علامت می‌خورد. تعداد فیلد پرشده."""
        with self.db._lock:
            row = self.db._conn.execute("SELECT language_code, genre_id, mood_id FROM songs WHERE id=?", (song_id,)).fetchone()
            if not row:
                return 0
            sets, params = [], []
            for col, new in (("language_code", language), ("genre_id", genre), ("mood_id", mood)):
                if new is not None and row[col] is None:
                    sets.append(f"{col}=?")
                    params.append(new)
            sets.append("ai_checked=1")
            self.db._conn.execute(f"UPDATE songs SET {', '.join(sets)} WHERE id=?", (*params, song_id))
            self.db._conn.commit()
            return len(sets) - 1

    def mark_ai_checked(self, ids: list[int]) -> None:
        if ids:
            self.db.execute(f"UPDATE songs SET ai_checked=1 WHERE id IN ({','.join('?' * len(ids))})", ids)

    def reset_ai_checked(self) -> None:
        self.db.execute("UPDATE songs SET ai_checked=0 WHERE ai_checked=1")

    # --- پست‌های قبلی کانال: دکمه‌ی ربات ---
    def promo_targets(self, mode: str, limit: int) -> list[dict]:
        """apply: منتشرشده‌های دارای پست در کانال که هنوز ردیف ندارند؛ remove: آن‌هایی که «اعمال‌شده» ثبت شده‌اند."""
        if mode == "apply":
            rows = self.db.fetchall(
                "SELECT s.id, s.channel_message_id FROM songs s LEFT JOIN promo_applied p ON p.channel_message_id=s.channel_message_id "
                "WHERE s.status='published' AND s.channel_message_id IS NOT NULL AND p.channel_message_id IS NULL "
                "ORDER BY s.channel_message_id DESC LIMIT ?", (limit,))
        else:
            rows = self.db.fetchall(
                "SELECT s.id, s.channel_message_id FROM songs s JOIN promo_applied p ON p.channel_message_id=s.channel_message_id "
                "WHERE p.status='applied' ORDER BY s.channel_message_id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def promo_counts(self) -> dict:
        eligible = self.db.fetchone("SELECT COUNT(*) c FROM songs WHERE status='published' AND channel_message_id IS NOT NULL")["c"]
        by = {r["status"]: r["c"] for r in self.db.fetchall(
            "SELECT p.status, COUNT(*) c FROM promo_applied p JOIN songs s ON s.channel_message_id=p.channel_message_id GROUP BY p.status")}
        return {"eligible": eligible, "applied": by.get("applied", 0), "skipped": by.get("skipped", 0)}

    def promo_mark(self, message_id: int, status: Optional[str]) -> None:
        if status is None:
            self.db.execute("DELETE FROM promo_applied WHERE channel_message_id=?", (message_id,))
        else:
            self.db.execute("INSERT INTO promo_applied(channel_message_id,status) VALUES (?,?) ON CONFLICT(channel_message_id) DO UPDATE SET "
                            "status=excluded.status, at=strftime('%Y-%m-%dT%H:%M:%SZ','now')", (message_id, status))

    def promo_reset_skipped(self) -> None:
        self.db.execute("DELETE FROM promo_applied WHERE status='skipped'")

    def next_unclassified(self, after_id: int) -> Optional[int]:
        """بعدی (با شناسه کمتر؛ در صورت نبود، از بالا) منتشرشده‌ی بدون زبان."""
        for cond, params in (("id<?", (after_id,)), ("id>=?", (after_id,))):
            row = self.db.fetchone(f"SELECT id FROM songs WHERE status='published' AND language_code IS NULL AND {cond} "
                                   "ORDER BY id DESC LIMIT 1", params)
            if row and row["id"] != after_id:
                return row["id"]
        return None

    def same_artist_unset(self, song: dict, column: str) -> int:
        if column not in ("language_code", "genre_id") or not song.get("artist_norm"):
            return 0
        return self.db.fetchone(f"SELECT COUNT(*) c FROM songs WHERE artist_norm=? AND id<>? AND {column} IS NULL",
                                (song["artist_norm"], song["id"]))["c"]

    def apply_to_same_artist(self, song: dict, column: str) -> int:
        """مقدار دسته‌ی این آهنگ را به آهنگ‌های همان خواننده که هنوز مقدار ندارند می‌دهد (بازنویسی نمی‌کند)."""
        if column not in ("language_code", "genre_id") or not song.get("artist_norm") or song.get(column) is None:
            return 0
        cur = self.db.execute(f"UPDATE songs SET {column}=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                              f"WHERE artist_norm=? AND id<>? AND {column} IS NULL", (song[column], song["artist_norm"], song["id"]))
        return cur.rowcount

    def get_published(self, song_id: int) -> Optional[dict]:
        row = self.db.fetchone(_SONG_SELECT + " WHERE s.id=? AND s.status='published'", (song_id,))
        return dict(row) if row else None

    def all_published(self, limit: int = 20000) -> list[dict]:
        rows = self.db.fetchall(_SONG_SELECT + " WHERE s.status='published' ORDER BY s.id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def all_with_status(self, status: str, limit: int = 500) -> list[dict]:
        rows = self.db.fetchall(_SONG_SELECT + " WHERE s.status=? ORDER BY s.id DESC LIMIT ?", (status, limit))
        return [dict(r) for r in rows]

    def counts_by_status(self) -> dict:
        rows = self.db.fetchall("SELECT status, COUNT(*) c FROM songs GROUP BY status")
        return {r["status"]: r["c"] for r in rows}

    def counts_by(self, dim: str, published_only: bool = False) -> dict:
        col = {"l": "language_code", "g": "genre_id", "m": "mood_id"}[dim]
        cond = " AND status='published'" if published_only else ""
        rows = self.db.fetchall(f"SELECT {col} k, COUNT(*) c FROM songs WHERE {col} IS NOT NULL{cond} GROUP BY {col}")
        return {r["k"]: r["c"] for r in rows}


class QueueRepo:
    """صف انتشار/زمان‌بندی. وضعیت‌ها: pending (منتظر زمان) | due (یادآوری فرستاده شد) | published | cancelled | failed."""

    ACTIVE = ("pending", "due")

    def __init__(self, db: Database):
        self.db = db

    def schedule(self, song_id: int, channel_ref: str, when_iso: str) -> int:
        """زمان‌بندی جدید؛ زمان‌بندی فعال قبلی همان آهنگ لغو می‌شود. approved_* خالی می‌ماند: تأیید در لحظه انتشار گرفته می‌شود."""
        with self.db._lock:
            self.db._conn.execute("UPDATE publication_queue SET status='cancelled' WHERE song_id=? AND status IN ('pending','due')", (song_id,))
            cur = self.db._conn.execute(
                "INSERT INTO publication_queue(song_id,channel_ref,scheduled_at,status) VALUES (?,?,?,'pending')",
                (song_id, channel_ref, when_iso),
            )
            self.db._conn.execute("UPDATE songs SET status='scheduled' WHERE id=? AND status='ready'", (song_id,))
            self.db._conn.commit()
            return cur.lastrowid

    def active_for_song(self, song_id: int) -> Optional[dict]:
        row = self.db.fetchone(
            "SELECT * FROM publication_queue WHERE song_id=? AND status IN ('pending','due') ORDER BY id DESC LIMIT 1", (song_id,))
        return dict(row) if row else None

    def list_active(self) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT q.*, s.title, s.artist FROM publication_queue q JOIN songs s ON s.id=q.song_id "
            "WHERE q.status IN ('pending','due') ORDER BY q.scheduled_at")
        return [dict(r) for r in rows]

    def due_pending(self, now_iso: str) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT * FROM publication_queue WHERE status='pending' AND scheduled_at<=? ORDER BY scheduled_at", (now_iso,))
        return [dict(r) for r in rows]

    def mark_due(self, queue_id: int) -> None:
        self.db.execute("UPDATE publication_queue SET status='due' WHERE id=? AND status='pending'", (queue_id,))

    def snooze(self, song_id: int, when_iso: str) -> None:
        self.db.execute("UPDATE publication_queue SET status='pending', scheduled_at=? WHERE song_id=? AND status IN ('pending','due')",
                        (when_iso, song_id))

    def cancel_for_song(self, song_id: int, restore_song: bool = True) -> None:
        with self.db._lock:
            self.db._conn.execute("UPDATE publication_queue SET status='cancelled' WHERE song_id=? AND status IN ('pending','due')", (song_id,))
            if restore_song:
                self.db._conn.execute("UPDATE songs SET status='ready' WHERE id=? AND status='scheduled'", (song_id,))
            self.db._conn.commit()

    def record_published(self, song_id: int, channel_ref: str, admin_id: int) -> None:
        with self.db._lock:
            self.db._conn.execute("UPDATE publication_queue SET status='cancelled' WHERE song_id=? AND status IN ('pending','due')", (song_id,))
            self.db._conn.execute(
                "INSERT INTO publication_queue(song_id,channel_ref,status,approved_by,approved_at,published_at) "
                "VALUES (?,?,'published',?,strftime('%Y-%m-%dT%H:%M:%SZ','now'),strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (song_id, channel_ref, admin_id),
            )
            self.db._conn.commit()


class BotSettingsRepo:
    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.db.fetchone("SELECT value FROM bot_settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO bot_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET "
            "value=excluded.value, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')", (key, value))

    def user_features_enabled(self) -> bool:
        return self.get("user_features", "0") == "1"

    def set_user_features(self, enabled: bool) -> None:
        self.set("user_features", "1" if enabled else "0")


class UserDataRepo:
    """رضایت، علایق، پسندها و درخواست‌ها. همه با شناسه عددی تلگرام؛ حذف کامل با یک فراخوان."""

    KINDS = ("language", "genre", "mood")

    def __init__(self, db: Database):
        self.db = db

    # --- رضایت ---
    def has_consent(self, uid: int) -> bool:
        row = self.db.fetchone("SELECT consent_at FROM users WHERE telegram_user_id=?", (uid,))
        return bool(row and row["consent_at"])

    def give_consent(self, uid: int) -> None:
        self.db.execute("UPDATE users SET consent_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE telegram_user_id=?", (uid,))

    # --- علایق ---
    def interests(self, uid: int) -> set[tuple[str, str]]:
        rows = self.db.fetchall("SELECT kind, ref FROM user_interests WHERE telegram_user_id=?", (uid,))
        return {(r["kind"], r["ref"]) for r in rows}

    def toggle_interest(self, uid: int, kind: str, ref: str) -> bool:
        """خروجی: True اگر اکنون فعال است. بدون رضایت ثبت نمی‌شود (ValueError)."""
        if kind not in self.KINDS:
            raise ValueError("kind")
        if not self.has_consent(uid):
            raise ValueError("no consent")
        with self.db._lock:
            cur = self.db._conn.execute("DELETE FROM user_interests WHERE telegram_user_id=? AND kind=? AND ref=?", (uid, kind, ref))
            if cur.rowcount:
                self.db._conn.commit()
                return False
            self.db._conn.execute("INSERT INTO user_interests(telegram_user_id,kind,ref) VALUES (?,?,?)", (uid, kind, ref))
            self.db._conn.commit()
            return True

    def aggregate(self) -> dict[str, dict[str, int]]:
        """آمار تجمیعی بدون هویت: {kind: {ref: count}}."""
        out: dict[str, dict[str, int]] = {k: {} for k in self.KINDS}
        for r in self.db.fetchall("SELECT kind, ref, COUNT(*) c FROM user_interests GROUP BY kind, ref"):
            out[r["kind"]][r["ref"]] = r["c"]
        return out

    # --- پسندها ---
    def toggle_like(self, uid: int, song_id: int) -> bool:
        if not self.has_consent(uid):
            raise ValueError("no consent")
        with self.db._lock:
            cur = self.db._conn.execute("DELETE FROM song_likes WHERE telegram_user_id=? AND song_id=?", (uid, song_id))
            if cur.rowcount:
                self.db._conn.commit()
                return False
            self.db._conn.execute("INSERT INTO song_likes(telegram_user_id,song_id) VALUES (?,?)", (uid, song_id))
            self.db._conn.commit()
            return True

    def is_liked(self, uid: int, song_id: int) -> bool:
        return self.db.fetchone("SELECT 1 FROM song_likes WHERE telegram_user_id=? AND song_id=?", (uid, song_id)) is not None

    def like_count(self, song_id: int) -> int:
        return self.db.fetchone("SELECT COUNT(*) c FROM song_likes WHERE song_id=?", (song_id,))["c"]

    def like_counts(self) -> dict[int, int]:
        return {r["song_id"]: r["c"] for r in self.db.fetchall("SELECT song_id, COUNT(*) c FROM song_likes GROUP BY song_id")}

    def liked_ids(self, uid: int) -> set[int]:
        return {r["song_id"] for r in self.db.fetchall("SELECT song_id FROM song_likes WHERE telegram_user_id=?", (uid,))}

    def liked_songs(self, uid: int, limit: int, offset: int) -> list[dict]:
        rows = self.db.fetchall(
            _SONG_SELECT + " JOIN song_likes k ON k.song_id=s.id WHERE k.telegram_user_id=? AND s.status='published' "
            "ORDER BY k.created_at DESC, s.id DESC LIMIT ? OFFSET ?", (uid, limit, offset))
        return [dict(r) for r in rows]

    def liked_count(self, uid: int) -> int:
        return self.db.fetchone(
            "SELECT COUNT(*) c FROM song_likes k JOIN songs s ON s.id=k.song_id WHERE k.telegram_user_id=? AND s.status='published'",
            (uid,))["c"]

    def top_liked(self, limit: int = 5) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT s.id, s.title, s.artist, COUNT(*) c FROM song_likes k JOIN songs s ON s.id=k.song_id "
            "WHERE s.status='published' GROUP BY s.id ORDER BY c DESC, s.id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def total_likes(self) -> int:
        return self.db.fetchone("SELECT COUNT(*) c FROM song_likes")["c"]

    # --- درخواست آهنگ ---
    def add_request(self, uid: int, text: str) -> int:
        return self.db.execute("INSERT INTO song_requests(telegram_user_id,text) VALUES (?,?)", (uid, text)).lastrowid

    def requests_last_day(self, uid: int) -> int:
        return self.db.fetchone(
            "SELECT COUNT(*) c FROM song_requests WHERE telegram_user_id=? AND created_at>=strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 day')",
            (uid,))["c"]

    def new_requests(self, limit: int = 10) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT r.*, u.username, u.first_name FROM song_requests r LEFT JOIN users u ON u.telegram_user_id=r.telegram_user_id "
            "WHERE r.status='new' ORDER BY r.id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def set_request_status(self, request_id: int, status: str) -> None:
        if status not in ("done", "dismissed"):
            raise ValueError("status")
        self.db.execute("UPDATE song_requests SET status=? WHERE id=?", (status, request_id))

    def count_new_requests(self) -> int:
        return self.db.fetchone("SELECT COUNT(*) c FROM song_requests WHERE status='new'")["c"]

    # --- حذف کامل اطلاعات کاربر ---
    def delete_all(self, uid: int) -> None:
        with self.db._lock:
            for table in ("user_interests", "song_likes", "song_requests"):
                self.db._conn.execute(f"DELETE FROM {table} WHERE telegram_user_id=?", (uid,))
            self.db._conn.execute("UPDATE users SET consent_at=NULL, username=NULL, first_name=NULL WHERE telegram_user_id=?", (uid,))
            self.db._conn.commit()


class PlaylistRepo:
    MAX_PLAYLISTS = 30

    def __init__(self, db: Database):
        self.db = db

    def create(self, name: str) -> int:
        if self.db.fetchone("SELECT COUNT(*) c FROM playlists")["c"] >= self.MAX_PLAYLISTS:
            raise ValueError("limit")
        return self.db.execute("INSERT INTO playlists(name) VALUES (?)", (name,)).lastrowid

    def set_premium(self, pid: int, premium: bool) -> None:
        self.db.execute("UPDATE playlists SET is_premium=? WHERE id=?", (1 if premium else 0, pid))

    def rename(self, pid: int, name: str) -> None:
        self.db.execute("UPDATE playlists SET name=? WHERE id=?", (name, pid))

    def delete(self, pid: int) -> None:
        with self.db._lock:
            self.db._conn.execute("DELETE FROM playlist_songs WHERE playlist_id=?", (pid,))
            self.db._conn.execute("DELETE FROM playlists WHERE id=?", (pid,))
            self.db._conn.commit()

    def get(self, pid: int) -> Optional[dict]:
        row = self.db.fetchone(
            "SELECT p.*, (SELECT COUNT(*) FROM playlist_songs x WHERE x.playlist_id=p.id) total, "
            "(SELECT COUNT(*) FROM playlist_songs x JOIN songs s ON s.id=x.song_id WHERE x.playlist_id=p.id AND s.status='published') public "
            "FROM playlists p WHERE p.id=?", (pid,))
        return dict(row) if row else None

    def list(self, public_only: bool = False) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT p.*, (SELECT COUNT(*) FROM playlist_songs x WHERE x.playlist_id=p.id) total, "
            "(SELECT COUNT(*) FROM playlist_songs x JOIN songs s ON s.id=x.song_id WHERE x.playlist_id=p.id AND s.status='published') public "
            "FROM playlists p ORDER BY p.id")
        out = [dict(r) for r in rows]
        return [p for p in out if p["public"] > 0] if public_only else out

    def add_song(self, pid: int, song_id: int) -> bool:
        with self.db._lock:
            if self.db._conn.execute("SELECT 1 FROM playlist_songs WHERE playlist_id=? AND song_id=?", (pid, song_id)).fetchone():
                return False
            pos = self.db._conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM playlist_songs WHERE playlist_id=?", (pid,)).fetchone()[0]
            self.db._conn.execute("INSERT INTO playlist_songs(playlist_id,song_id,position) VALUES (?,?,?)", (pid, song_id, pos))
            self.db._conn.commit()
            return True

    def remove_song(self, pid: int, song_id: int) -> None:
        self.db.execute("DELETE FROM playlist_songs WHERE playlist_id=? AND song_id=?", (pid, song_id))

    def has_song(self, pid: int, song_id: int) -> bool:
        return self.db.fetchone("SELECT 1 FROM playlist_songs WHERE playlist_id=? AND song_id=?", (pid, song_id)) is not None

    def songs(self, pid: int, published_only: bool, limit: int, offset: int) -> list[dict]:
        cond = " AND s.status='published'" if published_only else ""
        rows = self.db.fetchall(
            _SONG_SELECT + f" JOIN playlist_songs x ON x.song_id=s.id WHERE x.playlist_id=?{cond} ORDER BY x.position LIMIT ? OFFSET ?",
            (pid, limit, offset))
        return [dict(r) for r in rows]

    def count_songs(self, pid: int, published_only: bool) -> int:
        cond = " AND s.status='published'" if published_only else ""
        return self.db.fetchone(
            f"SELECT COUNT(*) c FROM playlist_songs x JOIN songs s ON s.id=x.song_id WHERE x.playlist_id=?{cond}", (pid,))["c"]


class MetricsRepo:
    """شمارنده‌های روزانه بدون هیچ هویتی + عکس روزانه‌ی تعداد اعضا + واکنش پست‌ها."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def today() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def incr(self, metric: str, n: int = 1, day: Optional[str] = None) -> None:
        self.db.execute(
            "INSERT INTO daily_metrics(day,metric,value) VALUES (?,?,?) ON CONFLICT(day,metric) DO UPDATE SET value=value+excluded.value",
            (day or self.today(), metric, n))

    def totals(self, days: int) -> dict[str, int]:
        rows = self.db.fetchall(
            "SELECT metric, SUM(value) v FROM daily_metrics WHERE day>=date('now', ?) GROUP BY metric", (f"-{int(days) - 1} day",))
        return {r["metric"]: r["v"] for r in rows}

    def series(self, metric: str, days: int) -> list[int]:
        """مقدار روزانه برای days روز اخیر (قدیمی‌ترین اول)."""
        rows = {r["day"]: r["value"] for r in self.db.fetchall(
            "SELECT day, value FROM daily_metrics WHERE metric=? AND day>=date('now', ?)", (metric, f"-{int(days) - 1} day"))}
        return [rows.get(r["d"], 0) for r in self.db.fetchall(
            "WITH RECURSIVE d(n) AS (SELECT 0 UNION ALL SELECT n+1 FROM d WHERE n<?) SELECT date('now', '-'||(?-n)||' day') d FROM d",
            (int(days) - 1, int(days) - 1))]

    # --- اعضا ---
    def snapshot_members(self, members: int, day: Optional[str] = None) -> None:
        self.db.execute("INSERT INTO member_snapshots(day,members) VALUES (?,?) ON CONFLICT(day) DO UPDATE SET members=excluded.members",
                        (day or self.today(), members))

    def has_snapshot(self, day: Optional[str] = None) -> bool:
        return self.db.fetchone("SELECT 1 FROM member_snapshots WHERE day=?", (day or self.today(),)) is not None

    def snapshots(self, limit: int = 30) -> list[dict]:
        rows = self.db.fetchall("SELECT day, members FROM member_snapshots ORDER BY day DESC LIMIT ?", (limit,))
        return [dict(r) for r in reversed(rows)]

    def members_change(self, days: int) -> Optional[int]:
        """اختلاف آخرین عکس با نزدیک‌ترین عکس حداقل days روز قبل (None اگر داده کافی نیست)."""
        last = self.db.fetchone("SELECT day, members FROM member_snapshots ORDER BY day DESC LIMIT 1")
        if not last:
            return None
        old = self.db.fetchone("SELECT members FROM member_snapshots WHERE day<=date(?, ?) ORDER BY day DESC LIMIT 1",
                               (last["day"], f"-{int(days)} day"))
        return last["members"] - old["members"] if old else None

    # --- واکنش پست‌ها ---
    def set_reactions(self, message_id: int, total: int) -> None:
        self.db.execute(
            "INSERT INTO post_stats(channel_message_id,reactions) VALUES (?,?) ON CONFLICT(channel_message_id) DO UPDATE SET "
            "reactions=excluded.reactions, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')", (message_id, total))

    def top_posts(self, limit: int = 5) -> list[dict]:
        rows = self.db.fetchall(
            "SELECT p.channel_message_id mid, p.reactions, s.id song_id, s.title, s.artist, s.post_url FROM post_stats p "
            "LEFT JOIN songs s ON s.channel_message_id=p.channel_message_id ORDER BY p.reactions DESC, p.channel_message_id DESC LIMIT ?",
            (limit,))
        return [dict(r) for r in rows]


class CampaignRepo:
    EDITABLE = {"title", "partner_link", "notes", "price", "post_text", "button_label", "button_url", "starts_at", "ends_at"}

    def __init__(self, db: Database):
        self.db = db

    def create(self, kind: str, title: str) -> int:
        if kind not in ("ad", "collab"):
            raise ValueError("kind")
        return self.db.execute("INSERT INTO campaigns(kind,title) VALUES (?,?)", (kind, title)).lastrowid

    def get(self, cid: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM campaigns WHERE id=?", (cid,))
        return dict(row) if row else None

    def update(self, cid: int, **fields) -> None:
        bad = set(fields) - self.EDITABLE
        if bad:
            raise ValueError(f"فیلد غیرمجاز: {bad}")
        sets = ", ".join(f"{c}=?" for c in fields)
        self.db.execute(f"UPDATE campaigns SET {sets}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (*fields.values(), cid))

    def list(self, kind: str, limit: int = 20) -> list[dict]:
        rows = self.db.fetchall("SELECT * FROM campaigns WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit))
        return [dict(r) for r in rows]

    def delete(self, cid: int) -> bool:
        """فقط پیش‌نویس/تمام‌شده/لغوشده حذف می‌شود."""
        cur = self.db.execute("DELETE FROM campaigns WHERE id=? AND status IN ('draft','done','cancelled')", (cid,))
        return cur.rowcount > 0

    # --- وضعیت‌ها ---
    def claim_publishing(self, cid: int) -> bool:
        with self.db._lock:
            cur = self.db._conn.execute("UPDATE campaigns SET status='publishing' WHERE id=? AND status='draft' AND channel_message_id IS NULL", (cid,))
            self.db._conn.commit()
            return cur.rowcount == 1

    def release_claim(self, cid: int) -> None:
        self.db.execute("UPDATE campaigns SET status='draft' WHERE id=? AND status='publishing'", (cid,))

    def mark_published(self, cid: int, message_id: int, members: Optional[int]) -> None:
        self.db.execute(
            "UPDATE campaigns SET status='active', channel_message_id=?, members_start=COALESCE(?, members_start), "
            "starts_at=COALESCE(starts_at, strftime('%Y-%m-%dT%H:%M:%SZ','now')), updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
            (message_id, members, cid))

    def start(self, cid: int, members: Optional[int]) -> bool:
        cur = self.db.execute("UPDATE campaigns SET status='active', members_start=?, starts_at=COALESCE(starts_at, strftime('%Y-%m-%dT%H:%M:%SZ','now')) "
                              "WHERE id=? AND status='draft'", (members, cid))
        return cur.rowcount == 1

    def finish(self, cid: int, members: Optional[int]) -> bool:
        cur = self.db.execute("UPDATE campaigns SET status='done', members_end=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                              "WHERE id=? AND status='active'", (members, cid))
        return cur.rowcount == 1

    def cancel(self, cid: int) -> bool:
        cur = self.db.execute("UPDATE campaigns SET status='cancelled' WHERE id=? AND status IN ('draft','active')", (cid,))
        return cur.rowcount == 1

    def due_endings(self, now_iso: str) -> list[dict]:
        rows = self.db.fetchall("SELECT * FROM campaigns WHERE status='active' AND ends_at IS NOT NULL AND ends_at<=? AND reminder_sent=0", (now_iso,))
        return [dict(r) for r in rows]

    def mark_reminded(self, cid: int) -> None:
        self.db.execute("UPDATE campaigns SET reminder_sent=1 WHERE id=?", (cid,))

    def snooze_end(self, cid: int, new_end_iso: str) -> None:
        self.db.execute("UPDATE campaigns SET ends_at=?, reminder_sent=0 WHERE id=? AND status='active'", (new_end_iso, cid))

    def income(self) -> dict:
        """جمع مبلغ تبلیغ‌های فعال/تمام‌شده (به واحدی که مدیر وارد کرده؛ معمولاً تومان)."""
        row = self.db.fetchone("SELECT COALESCE(SUM(price),0) t, COUNT(*) n FROM campaigns WHERE kind='ad' AND status IN ('active','done') AND price IS NOT NULL")
        last = self.db.fetchone("SELECT COALESCE(SUM(price),0) t FROM campaigns WHERE kind='ad' AND status IN ('active','done') AND price IS NOT NULL "
                                "AND created_at>=strftime('%Y-%m-%dT%H:%M:%SZ','now','-30 day')")
        return {"total": row["t"], "count": row["n"], "last_30d": last["t"]}


class PaymentRepo:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _now_iso() -> str:
        from musicbot.publishing.timeutil import to_iso, utc_now

        return to_iso(utc_now())

    def premium_until(self, uid: int) -> Optional[str]:
        row = self.db.fetchone("SELECT premium_until FROM users WHERE telegram_user_id=?", (uid,))
        return row["premium_until"] if row else None

    def is_premium(self, uid: int) -> bool:
        until = self.premium_until(uid)
        return bool(until and until > self._now_iso())

    def grant(self, uid: int, days: int) -> str:
        """از بزرگ‌ترِ «اکنون» و «پایان فعلی» دیرتر می‌شود (تمدید). ValueError اگر کاربر ثبت نشده باشد."""
        from datetime import timedelta

        from musicbot.publishing.timeutil import from_iso, to_iso, utc_now

        if not self.db.fetchone("SELECT 1 FROM users WHERE telegram_user_id=?", (uid,)):
            raise ValueError("user")
        cur = self.premium_until(uid)
        base = max(utc_now(), from_iso(cur)) if cur else utc_now()
        new = to_iso(base + timedelta(days=days))
        self.db.execute("UPDATE users SET premium_until=? WHERE telegram_user_id=?", (new, uid))
        return new

    def revoke(self, uid: int) -> None:
        self.db.execute("UPDATE users SET premium_until=NULL WHERE telegram_user_id=?", (uid,))

    def record(self, uid: int, stars: int, days: int, charge_id: str, payload: Optional[str]) -> Optional[str]:
        """ثبت پرداخت و تمدید اشتراک. اگر charge_id قبلاً ثبت شده باشد None (تکراری) برمی‌گرداند."""
        with self.db._lock:
            if self.db._conn.execute("SELECT 1 FROM payments WHERE charge_id=?", (charge_id,)).fetchone():
                return None
            self.db._conn.execute("INSERT INTO payments(telegram_user_id,stars,days,charge_id,payload) VALUES (?,?,?,?,?)",
                                  (uid, stars, days, charge_id, payload))
            self.db._conn.commit()
        return self.grant(uid, days)

    def get(self, payment_id: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT p.*, u.username, u.first_name FROM payments p LEFT JOIN users u ON u.telegram_user_id=p.telegram_user_id WHERE p.id=?", (payment_id,))
        return dict(row) if row else None

    def recent(self, limit: int = 10) -> list[dict]:
        rows = self.db.fetchall("SELECT p.*, u.username, u.first_name FROM payments p LEFT JOIN users u ON u.telegram_user_id=p.telegram_user_id "
                                "ORDER BY p.id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def mark_refunded(self, payment_id: int) -> bool:
        """پس از بازپرداخت موفق: وضعیت را عوض و روزهای همان پرداخت را از اشتراک کم می‌کند."""
        from datetime import timedelta

        from musicbot.publishing.timeutil import from_iso, to_iso

        p = self.get(payment_id)
        if not p or p["status"] != "paid":
            return False
        self.db.execute("UPDATE payments SET status='refunded' WHERE id=?", (payment_id,))
        cur = self.premium_until(p["telegram_user_id"])
        if cur:
            new = from_iso(cur) - timedelta(days=p["days"])
            self.db.execute("UPDATE users SET premium_until=? WHERE telegram_user_id=?", (to_iso(new), p["telegram_user_id"]))
        return True

    def revenue(self) -> dict:
        row = self.db.fetchone("SELECT COALESCE(SUM(stars),0) s, COUNT(*) n FROM payments WHERE status='paid'")
        last = self.db.fetchone("SELECT COALESCE(SUM(stars),0) s FROM payments WHERE status='paid' AND created_at>=strftime('%Y-%m-%dT%H:%M:%SZ','now','-30 day')")
        active = self.db.fetchone("SELECT COUNT(*) c FROM users WHERE premium_until>?", (self._now_iso(),))["c"]
        return {"stars": row["s"], "count": row["n"], "stars_30d": last["s"], "active": active}


class GrowthRepo:
    """کمپین‌های جذب مخاطب و شمارنده‌های روزانه‌ی ورود/خروج. هیچ شناسه یا نام عضوی ذخیره نمی‌شود
    (به‌جز هش نمکی اختیاری که با خروج عضو حذف می‌شود)."""

    KINDS = {
        "instagram": ("📸", "اینستاگرام"), "whatsapp": ("💬", "واتساپ"), "friends": ("👫", "دوستان و آشنایان"),
        "partner": ("🤝", "کانال همکار"), "groups": ("🎶", "گروه‌های موسیقی"), "ads": ("📢", "تبلیغات"), "other": ("🔗", "سایر منابع"),
    }
    MAX_CAMPAIGNS = 50

    def __init__(self, db: Database):
        self.db = db

    # --- کمپین ---
    def create_campaign(self, kind: str, name: str, invite_link: Optional[str], link_name: Optional[str]) -> int:
        if kind not in self.KINDS:
            raise ValueError("kind")
        if self.db.fetchone("SELECT COUNT(*) c FROM growth_campaigns")["c"] >= self.MAX_CAMPAIGNS:
            raise ValueError("limit")
        return self.db.execute("INSERT INTO growth_campaigns(kind,name,invite_link,link_name) VALUES (?,?,?,?)",
                               (kind, name, invite_link, link_name)).lastrowid

    def get_campaign(self, cid: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM growth_campaigns WHERE id=?", (cid,))
        return dict(row) if row else None

    def campaign_by_link(self, link: Optional[str]) -> Optional[dict]:
        if not link:
            return None
        row = self.db.fetchone("SELECT * FROM growth_campaigns WHERE invite_link=?", (link,))
        return dict(row) if row else None

    def list_campaigns(self) -> list[dict]:
        rows = self.db.fetchall("SELECT * FROM growth_campaigns ORDER BY (status='active') DESC, id DESC")
        return [dict(r) for r in rows]

    def mark_revoked(self, cid: int) -> bool:
        cur = self.db.execute("UPDATE growth_campaigns SET status='revoked', revoked_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                              "WHERE id=? AND status='active'", (cid,))
        return cur.rowcount == 1

    def delete_campaign(self, cid: int) -> bool:
        """فقط کمپین ابطال‌شده؛ آمار روزانه‌ی آن به «نامشخص» منتقل می‌شود تا جمع کل عضویت‌ها حفظ شود."""
        with self.db._lock:
            row = self.db._conn.execute("SELECT status FROM growth_campaigns WHERE id=?", (cid,)).fetchone()
            if not row or row["status"] != "revoked":
                return False
            for r in self.db._conn.execute("SELECT day, joins, leaves FROM member_events_daily WHERE campaign_id=?", (cid,)).fetchall():
                self.db._conn.execute(
                    "INSERT INTO member_events_daily(day,campaign_id,joins,leaves) VALUES (?,0,?,?) "
                    "ON CONFLICT(day,campaign_id) DO UPDATE SET joins=joins+excluded.joins, leaves=leaves+excluded.leaves",
                    (r["day"], r["joins"], r["leaves"]))
            self.db._conn.execute("DELETE FROM member_events_daily WHERE campaign_id=?", (cid,))
            self.db._conn.execute("DELETE FROM member_hashes WHERE campaign_id=?", (cid,))
            self.db._conn.execute("DELETE FROM growth_campaigns WHERE id=?", (cid,))
            self.db._conn.commit()
            return True

    # --- رویدادها ---
    def record(self, day: str, campaign_id: int = 0, joins: int = 0, leaves: int = 0) -> None:
        self.db.execute(
            "INSERT INTO member_events_daily(day,campaign_id,joins,leaves) VALUES (?,?,?,?) "
            "ON CONFLICT(day,campaign_id) DO UPDATE SET joins=joins+excluded.joins, leaves=leaves+excluded.leaves",
            (day, campaign_id, joins, leaves))

    def totals(self, days: Optional[int] = None) -> dict:
        cond, params = ("", ()) if days is None else (" WHERE day>=date('now', ?)", (f"-{int(days) - 1} day",))
        row = self.db.fetchone(f"SELECT COALESCE(SUM(joins),0) j, COALESCE(SUM(leaves),0) l FROM member_events_daily{cond}", params)
        return {"joins": row["j"], "leaves": row["l"]}

    def per_campaign(self, days: Optional[int] = None) -> dict[int, dict]:
        cond, params = ("", ()) if days is None else (" WHERE day>=date('now', ?)", (f"-{int(days) - 1} day",))
        rows = self.db.fetchall(f"SELECT campaign_id, SUM(joins) j, SUM(leaves) l FROM member_events_daily{cond} GROUP BY campaign_id", params)
        return {r["campaign_id"]: {"joins": r["j"], "leaves": r["l"]} for r in rows}

    def daily(self, days: int) -> list[dict]:
        """به ازای هر یک از days روز اخیر (قدیمی‌ترین اول): {day, joins, leaves}."""
        have = {r["day"]: (r["j"], r["l"]) for r in self.db.fetchall(
            "SELECT day, SUM(joins) j, SUM(leaves) l FROM member_events_daily WHERE day>=date('now', ?) GROUP BY day",
            (f"-{int(days) - 1} day",))}
        days_list = [r["d"] for r in self.db.fetchall(
            "WITH RECURSIVE d(n) AS (SELECT 0 UNION ALL SELECT n+1 FROM d WHERE n<?) SELECT date('now', '-'||(?-n)||' day') d FROM d",
            (int(days) - 1, int(days) - 1))]
        return [{"day": d, "joins": have.get(d, (0, 0))[0], "leaves": have.get(d, (0, 0))[1]} for d in days_list]

    # --- هش اختیاری برای نسبت‌دادن خروج به کمپین ---
    def remember_hash(self, h: str, campaign_id: int, day: str) -> None:
        self.db.execute("INSERT INTO member_hashes(hash,campaign_id,joined_day) VALUES (?,?,?) "
                        "ON CONFLICT(hash) DO UPDATE SET campaign_id=excluded.campaign_id, joined_day=excluded.joined_day", (h, campaign_id, day))

    def pop_hash(self, h: str) -> Optional[int]:
        with self.db._lock:
            row = self.db._conn.execute("SELECT campaign_id FROM member_hashes WHERE hash=?", (h,)).fetchone()
            if row:
                self.db._conn.execute("DELETE FROM member_hashes WHERE hash=?", (h,))
                self.db._conn.commit()
            return row["campaign_id"] if row else None

    def clear_hashes(self) -> None:
        self.db.execute("DELETE FROM member_hashes")


class GrowthContentRepo:
    """متن‌های تبلیغ، برنامه‌های هفتگی و نقاط عطف."""

    MAX_TEXTS = 60
    MAX_MILESTONES = 12

    def __init__(self, db: Database):
        self.db = db

    # --- متن‌ها ---
    def add_text(self, kind: str, variant: int, campaign_id: int, text: str) -> int:
        with self.db._lock:
            cur = self.db._conn.execute("INSERT INTO growth_texts(kind,variant,campaign_id,text) VALUES (?,?,?,?)", (kind, variant, campaign_id, text))
            self.db._conn.execute("DELETE FROM growth_texts WHERE id NOT IN (SELECT id FROM growth_texts ORDER BY id DESC LIMIT ?)", (self.MAX_TEXTS,))
            self.db._conn.commit()
            return cur.lastrowid

    def get_text(self, tid: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM growth_texts WHERE id=?", (tid,))
        return dict(row) if row else None

    def list_texts(self, limit: int = 10) -> list[dict]:
        return [dict(r) for r in self.db.fetchall("SELECT * FROM growth_texts ORDER BY id DESC LIMIT ?", (limit,))]

    def edit_text(self, tid: int, text: str) -> None:
        self.db.execute("UPDATE growth_texts SET text=?, edited=1, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (text, tid))

    def regenerate_text(self, tid: int, variant: int, text: str) -> None:
        self.db.execute("UPDATE growth_texts SET variant=?, text=?, edited=0, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                        (variant, text, tid))

    def delete_text(self, tid: int) -> None:
        self.db.execute("DELETE FROM growth_texts WHERE id=?", (tid,))

    # --- برنامه‌ی هفتگی ---
    def get_plan(self, week: str) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM growth_plans WHERE week=?", (week,))
        return dict(row) if row else None

    def save_plan(self, week: str, text: str) -> None:
        with self.db._lock:
            self.db._conn.execute("INSERT INTO growth_plans(week,text) VALUES (?,?) ON CONFLICT(week) DO UPDATE SET text=excluded.text, "
                                  "created_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')", (week, text))
            self.db._conn.execute("DELETE FROM growth_plans WHERE week NOT IN (SELECT week FROM growth_plans ORDER BY week DESC LIMIT 12)")
            self.db._conn.commit()

    # --- نقاط عطف ---
    def milestones(self) -> list[dict]:
        return [dict(r) for r in self.db.fetchall("SELECT * FROM milestones ORDER BY members")]

    def get_milestone(self, mid: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM milestones WHERE id=?", (mid,))
        return dict(row) if row else None

    def add_milestone(self, members: int, title: str, note: Optional[str]) -> int:
        if members < 1 or members > 100_000_000:
            raise ValueError("members")
        if len(self.milestones()) >= self.MAX_MILESTONES:
            raise ValueError("limit")
        return self.db.execute("INSERT INTO milestones(members,title,note) VALUES (?,?,?)", (members, title, note)).lastrowid

    def update_milestone(self, mid: int, **fields) -> None:
        bad = set(fields) - {"members", "title", "note"}
        if bad:
            raise ValueError("field")
        if "members" in fields and not 1 <= fields["members"] <= 100_000_000:
            raise ValueError("members")
        sets = ", ".join(f"{c}=?" for c in fields)
        self.db.execute(f"UPDATE milestones SET {sets} WHERE id=?", (*fields.values(), mid))

    def delete_milestone(self, mid: int) -> bool:
        if len(self.milestones()) <= 1:
            return False                         # حداقل یک نقطه باقی بماند
        return self.db.execute("DELETE FROM milestones WHERE id=?", (mid,)).rowcount > 0

    def stage(self, members: Optional[int]) -> dict:
        """مرحله‌ی فعلی: بالاترین نقطه‌ی عطفِ رسیده‌شده. tier = شماره‌ی مرحله (اولین نقطه = مرحله‌ی ۰، حداکثر ۴)."""
        ms = self.milestones()
        reached = [m for m in ms if members is not None and m["members"] <= members]
        upcoming = [m for m in ms if members is None or m["members"] > members]
        return {"current": reached[-1] if reached else None, "next": upcoming[0] if upcoming else None,
                "tier": min(max(len(reached) - 1, 0), 4)}


class RadarRepo:
    """وضعیت منابع رادار، عکس‌های کش‌شده‌ی نمودارها و ثبت دستی. هیچ فایل صوتی‌ای اینجا نیست؛ فقط متادیتا و لینک."""

    KEEP_SNAPSHOTS = 10

    def __init__(self, db: Database):
        self.db = db

    # --- وضعیت منبع ---
    def state(self, source_id: str) -> dict:
        row = self.db.fetchone("SELECT * FROM radar_sources WHERE source_id=?", (source_id,))
        return dict(row) if row else {"source_id": source_id, "enabled": 0, "approved_at": None, "regions": None, "last_fetch_at": None,
                                       "last_ok_at": None, "last_status": None, "last_error": None}

    def _ensure(self, source_id: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO radar_sources(source_id) VALUES (?)", (source_id,))

    def set_enabled(self, source_id: str, enabled: bool) -> None:
        self._ensure(source_id)
        if enabled:
            self.db.execute("UPDATE radar_sources SET enabled=1, approved_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE source_id=?", (source_id,))
        else:
            self.db.execute("UPDATE radar_sources SET enabled=0 WHERE source_id=?", (source_id,))

    def set_regions(self, source_id: str, regions: Optional[str]) -> None:
        self._ensure(source_id)
        self.db.execute("UPDATE radar_sources SET regions=? WHERE source_id=?", (regions, source_id))

    def record_fetch(self, source_id: str, status: str, error: Optional[str], ok: bool, at: Optional[str] = None) -> None:
        """at: زمان به‌صورت ISO UTC (سرویس تنها منبع زمان است تا کش و ثبت هماهنگ بمانند)."""
        self._ensure(source_id)
        at = at or self.db.fetchone("SELECT strftime('%Y-%m-%dT%H:%M:%SZ','now') t")["t"]
        self.db.execute(
            "UPDATE radar_sources SET last_fetch_at=?, last_status=?, last_error=?, last_ok_at=CASE WHEN ? THEN ? ELSE last_ok_at END WHERE source_id=?",
            (at, status, error, 1 if ok else 0, at, source_id))

    # --- عکس‌ها ---
    def add_snapshot(self, source_id: str, region: str, entries: list[dict], ok: bool, error: Optional[str] = None,
                     at: Optional[str] = None) -> int:
        from musicbot.songs.textutils import normalize

        with self.db._lock:
            at = at or self.db._conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%SZ','now')").fetchone()[0]
            cur = self.db._conn.execute("INSERT INTO radar_snapshots(source_id,region,fetched_at,ok,entry_count,error) VALUES (?,?,?,?,?,?)",
                                        (source_id, region, at, 1 if ok else 0, len(entries), error))
            sid = cur.lastrowid
            for e in entries:
                self.db._conn.execute(
                    "INSERT OR REPLACE INTO radar_entries(snapshot_id,rank,ext_id,title,artist,url,native_score,native_label,published_at,genre,title_norm,artist_norm) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, e["rank"], e.get("ext_id"), e["title"], e.get("artist"), e.get("url"), e.get("native_score"), e.get("native_label"),
                     e.get("published_at"), e.get("genre"), normalize(e["title"]) or None, normalize(e.get("artist")) or None))
            self.db._conn.execute(
                "DELETE FROM radar_snapshots WHERE source_id=? AND region=? AND id NOT IN "
                "(SELECT id FROM radar_snapshots WHERE source_id=? AND region=? ORDER BY id DESC LIMIT ?)",
                (source_id, region, source_id, region, self.KEEP_SNAPSHOTS))
            self.db._conn.commit()
            return sid

    def latest_snapshot(self, source_id: str, region: str, ok_only: bool = True) -> Optional[dict]:
        cond = " AND ok=1" if ok_only else ""
        row = self.db.fetchone(f"SELECT * FROM radar_snapshots WHERE source_id=? AND region=?{cond} ORDER BY id DESC LIMIT 1", (source_id, region))
        return dict(row) if row else None

    def previous_snapshot(self, source_id: str, region: str, before_id: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM radar_snapshots WHERE source_id=? AND region=? AND ok=1 AND id<? ORDER BY id DESC LIMIT 1",
                               (source_id, region, before_id))
        return dict(row) if row else None

    def entries(self, snapshot_id: int) -> list[dict]:
        return [dict(r) for r in self.db.fetchall("SELECT * FROM radar_entries WHERE snapshot_id=? ORDER BY rank", (snapshot_id,))]

    def regions_with_data(self, source_id: str) -> list[str]:
        return [r["region"] for r in self.db.fetchall("SELECT DISTINCT region FROM radar_snapshots WHERE source_id=? AND ok=1 ORDER BY region", (source_id,))]

    # --- ثبت دستی ---
    def add_manual(self, title: str, artist: Optional[str], url: Optional[str], note: Optional[str]) -> int:
        if self.db.fetchone("SELECT COUNT(*) c FROM radar_manual")["c"] >= 500:
            raise ValueError("limit")
        return self.db.execute("INSERT INTO radar_manual(title,artist,url,source_note) VALUES (?,?,?,?)", (title, artist, url, note)).lastrowid

    def manual_list(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.db.fetchall("SELECT * FROM radar_manual ORDER BY id DESC LIMIT ?", (limit,))]

    def delete_manual(self, mid: int) -> bool:
        return self.db.execute("DELETE FROM radar_manual WHERE id=?", (mid,)).rowcount > 0


    # --- پیشنهادهای رادار ---
    SUG_FIELDS = {"status", "kind", "kind_override", "license_status", "license_note", "song_id", "reported_at"}

    def upsert_suggestion(self, key: str, title: str, artist: Optional[str], kind: str, source_id: Optional[str], region: Optional[str],
                          best_rank: Optional[int], url: Optional[str], native_label: Optional[str], published_at: Optional[str],
                          genre: Optional[str], license_status: str = "unknown") -> dict:
        """پیشنهاد یکتا بر اساس کلید نرمال‌شده؛ وضعیت/مجوز/انتخاب دستی مدیر هرگز بازنویسی نمی‌شود."""
        with self.db._lock:
            row = self.db._conn.execute("SELECT * FROM radar_suggestions WHERE key_norm=?", (key,)).fetchone()
            if row is None:
                cur = self.db._conn.execute(
                    "INSERT INTO radar_suggestions(key_norm,title,artist,kind,source_id,region,best_rank,url,native_label,published_at,genre,license_status,last_seen_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                    (key, title, artist, kind, source_id, region, best_rank, url, native_label, published_at, genre, license_status))
                sid = cur.lastrowid
            else:
                sid = row["id"]
                keep_kind = row["kind"] if row["kind_override"] else kind
                self.db._conn.execute(
                    "UPDATE radar_suggestions SET kind=?, source_id=?, region=?, best_rank=?, url=COALESCE(?,url), native_label=?, "
                    "published_at=COALESCE(?,published_at), genre=COALESCE(?,genre), last_seen_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                    (keep_kind, source_id, region, best_rank, url, native_label, published_at, genre, sid))
            self.db._conn.commit()
            return dict(self.db._conn.execute("SELECT * FROM radar_suggestions WHERE id=?", (sid,)).fetchone())

    def get_suggestion_by_key(self, key: str) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM radar_suggestions WHERE key_norm=?", (key,))
        return dict(row) if row else None

    def get_suggestion(self, sid: int) -> Optional[dict]:
        row = self.db.fetchone("SELECT * FROM radar_suggestions WHERE id=?", (sid,))
        return dict(row) if row else None

    def set_suggestion(self, sid: int, **fields) -> None:
        bad = set(fields) - self.SUG_FIELDS
        if bad:
            raise ValueError(f"فیلد غیرمجاز: {bad}")
        sets = ", ".join(f"{c}=?" for c in fields)
        self.db.execute(f"UPDATE radar_suggestions SET {sets} WHERE id=?", (*fields.values(), sid))

    def suggestions_by_status(self, status: str, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.db.fetchall("SELECT * FROM radar_suggestions WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))]

    def mark_reported(self, ids: list[int], at: str) -> None:
        if ids:
            self.db.execute(f"UPDATE radar_suggestions SET reported_at=? WHERE id IN ({','.join('?' * len(ids))})", (at, *ids))

    def suggestion_counts(self) -> dict:
        return {r["status"]: r["c"] for r in self.db.fetchall("SELECT status, COUNT(*) c FROM radar_suggestions GROUP BY status")}


class CategoryRepo:
    """زبان‌ها، سبک‌ها و حال‌وهواها (قابل ویرایش در آینده)."""

    def __init__(self, db: Database):
        self.db = db

    def list(self, table: str) -> list[dict]:
        if table not in _CATEGORY_TABLES:
            raise ValueError("جدول نامعتبر")
        key = _CATEGORY_TABLES[table]
        rows = self.db.fetchall(f"SELECT {key} AS key, name_fa FROM {table} WHERE is_active=1 ORDER BY sort_order")
        return [dict(r) for r in rows]

    def exists(self, table: str, key) -> bool:
        if table not in _CATEGORY_TABLES:
            return False
        col = _CATEGORY_TABLES[table]
        return self.db.fetchone(f"SELECT 1 FROM {table} WHERE {col}=? AND is_active=1", (key,)) is not None


class Repositories:
    def __init__(self, db: Database):
        self.db = db
        self.logs = ActivityLogRepo(db)
        self.admins = AdminRepo(db)
        self.users = UserRepo(db)
        self.channel = ChannelSettingsRepo(db)
        self.ai = AISettingsRepo(db)
        self.songs = SongRepo(db)
        self.categories = CategoryRepo(db)
        self.queue = QueueRepo(db)
        self.settings = BotSettingsRepo(db)
        self.userdata = UserDataRepo(db)
        self.playlists = PlaylistRepo(db)
        self.metrics = MetricsRepo(db)
        self.campaigns = CampaignRepo(db)
        self.payments = PaymentRepo(db)
        self.growth = GrowthRepo(db)
        self.gcontent = GrowthContentRepo(db)
        self.radar = RadarRepo(db)
