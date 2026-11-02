import sqlite3

import pytest

EXPECTED = {"admins", "users", "songs", "genres", "moods", "publication_queue", "channel_settings",
            "playlists", "activity_logs", "ai_settings", "languages", "playlist_songs"}


def test_tables_and_seed(db):
    names = {r["name"] for r in db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED <= names
    assert db.fetchone("SELECT COUNT(*) c FROM languages")["c"] == 5
    assert db.fetchone("SELECT COUNT(*) c FROM genres")["c"] == 8
    assert db.fetchone("SELECT COUNT(*) c FROM moods")["c"] == 9


def test_migrate_idempotent_and_keeps_edits(db):
    db.execute("UPDATE genres SET name_fa='ویرایش' WHERE code='pop'")
    db.migrate()
    assert db.fetchone("SELECT name_fa FROM genres WHERE code='pop'")["name_fa"] == "ویرایش"
    assert db.fetchone("SELECT COUNT(*) c FROM genres")["c"] == 8


def test_unique_file_unique_id(db):
    db.execute("INSERT INTO songs(title,file_unique_id) VALUES ('a','U1')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO songs(title,file_unique_id) VALUES ('b','U1')")


def test_db_refuses_published_without_approval(db):
    db.execute("INSERT INTO songs(title) VALUES ('a')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO publication_queue(song_id,channel_ref,status) VALUES (1,'@c','published')")
    db.execute("INSERT INTO publication_queue(song_id,channel_ref,status,approved_by,approved_at) "
               "VALUES (1,'@c','published',1,'2026-01-01T00:00:00Z')")


def test_channel_active_switch(repos):
    repos.channel.set_active("@a", "A")
    repos.channel.set_active("@b", "B")
    assert repos.channel.get_active().channel_ref == "@b"
    assert repos.db.fetchone("SELECT COUNT(*) c FROM channel_settings WHERE is_active=1")["c"] == 1


def test_logs_and_ai_settings(repos):
    repos.logs.add("x", 1, "d")
    assert repos.logs.recent(1)[0]["action"] == "x"
    repos.ai.set("provider", "none")
    repos.ai.set("provider", "claude")
    assert repos.ai.get("provider") == "claude"


def test_single_owner(repos):
    repos.admins.ensure_owner(2002)
    assert repos.admins.is_active_admin(2002) and not repos.admins.is_active_admin(1001)
