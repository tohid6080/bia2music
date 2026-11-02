"""دریافت فایل صوتی: استخراج اطلاعات، تشخیص تکراری، ساخت پیش‌نویس. هیچ‌چیزی منتشر نمی‌شود."""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from musicbot.db import Repositories
from musicbot.songs.textutils import AUDIO_EXTS, clean_text, parse_filename

log = logging.getLogger(__name__)
MAX_HASH_BYTES = 20 * 1024 * 1024  # سقف دانلود Bot API


@dataclass
class AudioMeta:
    file_id: str
    file_unique_id: str
    file_size: Optional[int] = None
    duration: Optional[int] = None
    performer: Optional[str] = None
    title: Optional[str] = None
    file_name: Optional[str] = None


@dataclass
class IngestResult:
    duplicate: bool
    song: dict
    reason: Optional[str] = None  # file_unique_id | file_hash
    attached: bool = False        # فایل به آهنگِ بدون‌فایلِ آماده‌شده از رادار وصل شد


def extract_meta(message) -> Optional[AudioMeta]:
    audio = getattr(message, "audio", None)
    if audio:
        return AudioMeta(audio.file_id, audio.file_unique_id, audio.file_size, audio.duration,
                         audio.performer, audio.title, audio.file_name)
    doc = getattr(message, "document", None)
    if doc:
        name = (doc.file_name or "").lower()
        if (doc.mime_type or "").startswith("audio/") or name.endswith(AUDIO_EXTS):
            return AudioMeta(doc.file_id, doc.file_unique_id, doc.file_size, None, None, None, doc.file_name)
    return None


async def ingest_audio(
    repos: Repositories,
    meta: AudioMeta,
    admin_id: int,
    downloader: Optional[Callable[[], Awaitable[Optional[bytes]]]] = None,
) -> IngestResult:
    existing = repos.songs.find_by_unique_id(meta.file_unique_id)
    if existing:
        return IngestResult(True, existing, "file_unique_id")

    file_hash = None
    if downloader is not None and (meta.file_size or 0) <= MAX_HASH_BYTES:
        try:
            data = await downloader()
            if data:
                file_hash = hashlib.sha256(data).hexdigest()
        except Exception:  # noqa: BLE001 - هش اختیاری است؛ خطا نباید ثبت را متوقف کند
            log.warning("hash download failed")
    if file_hash:
        existing = repos.songs.find_by_hash(file_hash)
        if existing:
            return IngestResult(True, existing, "file_hash")

    title, artist = clean_text(meta.title), clean_text(meta.performer)
    f_artist, f_title = parse_filename(meta.file_name)
    title = title or f_title
    artist = artist or f_artist

    from musicbot.songs.textutils import normalize

    match = repos.songs.find_fileless_match(normalize(title), normalize(artist))
    if match:                                         # همان آهنگی که از رادار به پیش‌نویس/آرشیو برده بودید
        repos.songs.attach_file(match["id"], meta.file_id, meta.file_unique_id, file_hash, meta.duration, meta.file_size)
        repos.logs.add("song_file_attached", admin_id, f"id={match['id']}")
        return IngestResult(False, repos.songs.get(match["id"]), attached=True)
    try:
        song_id = repos.songs.create(
            title=title, artist=artist, telegram_file_id=meta.file_id, file_unique_id=meta.file_unique_id,
            file_hash=file_hash, duration_seconds=meta.duration, file_size=meta.file_size, created_by=admin_id,
        )
    except sqlite3.IntegrityError:  # دو ارسال همزمان همان فایل
        existing = repos.songs.find_by_unique_id(meta.file_unique_id)
        return IngestResult(True, existing, "file_unique_id")
    repos.logs.add("song_added", admin_id, f"id={song_id}")
    return IngestResult(False, repos.songs.get(song_id))
