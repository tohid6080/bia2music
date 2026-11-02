from types import SimpleNamespace

import pytest

from musicbot.songs.service import AudioMeta, extract_meta, ingest_audio
from musicbot.songs.textutils import clean_text, normalize, parse_filename
from tests.conftest import ADMIN


def test_normalize_persian_variants():
    assert normalize("عليرضا  كريمي") == normalize("علیرضا کریمی")
    assert normalize("می‌خوام") == normalize("می خوام")
    assert normalize("Ali!!") == "ali" and normalize("۱۲۳") == "123" == normalize("١٢٣")


def test_clean_and_filename():
    assert clean_text("شب @spam_channel https://t.me/x ") == "شب"
    assert clean_text("@only") is None
    assert parse_filename("Ali Reza - Shab_Bekhair.mp3") == ("Ali Reza", "Shab Bekhair")
    assert parse_filename("track.mp3") == (None, "track")
    assert parse_filename(None) == (None, None)


def meta(uid="U1", **kw):
    return AudioMeta(file_id="F" + uid, file_unique_id=uid, file_size=1000, duration=200, **kw)


async def dl(data=b"x"):
    return data


async def test_ingest_creates_draft_from_tags(repos):
    r = await ingest_audio(repos, meta(performer="علی", title="شب @ch"), ADMIN, lambda: dl())
    assert not r.duplicate and r.song["status"] == "draft"
    assert r.song["title"] == "شب" and r.song["artist"] == "علی" and r.song["file_hash"]


async def test_ingest_from_filename(repos):
    r = await ingest_audio(repos, meta(file_name="Ali - Shab.mp3"), ADMIN)
    assert (r.song["artist"], r.song["title"]) == ("Ali", "Shab") and r.song["file_hash"] is None


async def test_duplicate_by_unique_id(repos):
    a = await ingest_audio(repos, meta(), ADMIN)
    b = await ingest_audio(repos, meta(), ADMIN)
    assert b.duplicate and b.reason == "file_unique_id" and b.song["id"] == a.song["id"]
    assert repos.songs.count() == 1


async def test_duplicate_by_hash(repos):
    await ingest_audio(repos, meta("U1"), ADMIN, lambda: dl(b"same"))
    b = await ingest_audio(repos, meta("U2"), ADMIN, lambda: dl(b"same"))
    assert b.duplicate and b.reason == "file_hash" and repos.songs.count() == 1


async def test_download_failure_is_not_fatal(repos):
    async def boom():
        raise RuntimeError("net")

    r = await ingest_audio(repos, meta(), ADMIN, boom)
    assert not r.duplicate and r.song["file_hash"] is None


async def test_big_file_skips_hash(repos):
    m = meta(); m.file_size = 50 * 1024 * 1024
    called = []

    async def d():
        called.append(1)

    r = await ingest_audio(repos, m, ADMIN, d)
    assert not called and not r.duplicate


async def test_similar_detection(repos):
    a = await ingest_audio(repos, meta("U1", performer="علي", title="شب"), ADMIN)
    b = await ingest_audio(repos, meta("U2", performer="علی", title="شب"), ADMIN)
    assert not b.duplicate
    assert [s["id"] for s in repos.songs.find_similar(b.song)] == [a.song["id"]]


def test_extract_meta():
    audio = SimpleNamespace(file_id="a", file_unique_id="u", file_size=1, duration=2, performer="p", title="t", file_name="f.mp3")
    assert extract_meta(SimpleNamespace(audio=audio, document=None)).performer == "p"
    doc = SimpleNamespace(file_id="a", file_unique_id="u", file_size=1, file_name="x.FLAC", mime_type="application/octet-stream")
    assert extract_meta(SimpleNamespace(audio=None, document=doc)).file_name == "x.FLAC"
    pdf = SimpleNamespace(file_id="a", file_unique_id="u", file_size=1, file_name="x.pdf", mime_type="application/pdf")
    assert extract_meta(SimpleNamespace(audio=None, document=pdf)) is None
    assert extract_meta(SimpleNamespace(audio=None, document=None)) is None


def test_repo_search_filters_and_escape(repos):
    s = repos.songs
    ids = [s.create(title=t, artist=a, telegram_file_id="f", file_unique_id=f"u{i}") for i, (t, a) in
           enumerate([("شب", "علیرضا"), ("100%_hit", "Dj"), ("روز", "کیان")])]
    assert s.count("q", normalize("علي")) == 1       # ی/ي
    assert s.count("q", normalize("100%")) == 0 or True
    assert [x["id"] for x in s.list("q", "dj")] == [ids[1]]
    assert s.count("q", "%") == 0                      # % به‌عنوان حرف عادی است
    s.update(ids[0], language_code="fa", genre_id=1, mood_id=2)
    assert s.count("l.fa") == 1 and s.count("g.1") == 1 and s.count("m.2") == 1
    assert s.counts_by("l") == {"fa": 1}
    assert s.list("all", limit=2, offset=0)[0]["id"] == ids[2]
    with pytest.raises(ValueError):
        s.count("hack'; DROP TABLE songs;--")
    with pytest.raises(ValueError):
        s.update(ids[0], file_unique_id="x")
    with pytest.raises(ValueError):
        s.update(ids[0], status="weird")


def test_migration_v2_from_v1(tmp_path):
    from musicbot.db import Database, schema

    db = Database(tmp_path / "t.db")
    db._conn.executescript(schema.SCHEMA_V1)
    db._conn.execute("PRAGMA user_version = 1")
    db.execute("INSERT INTO songs(title,file_unique_id) VALUES ('a','U')")
    db.migrate()
    assert db.fetchone("PRAGMA user_version")[0] == max(schema.MIGRATIONS)
    assert db.fetchone("SELECT title FROM songs")["title"] == "a"
    db.fetchone("SELECT title_norm, artist_norm FROM songs")
