from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from b2m.db import models as M, seed
from b2m.db.base import Base
from b2m.db.migrate import upgrade
from b2m.db.session import make_engine, make_session_factory

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)
REQUIRED = {"users", "user_preferences", "music_dna_profiles", "songs", "artists", "genres", "moods", "favorites", "battles", "battle_votes", "quizzes",
            "quiz_questions", "quiz_attempts", "user_points", "user_achievements", "mixtapes", "mixtape_songs", "music_matches", "trend_sources",
            "trending_tracks", "publication_queue", "admins", "activity_logs", "app_settings"}


def test_all_required_entities_exist():
    assert REQUIRED == set(Base.metadata.tables)


def test_migration_matches_models(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    url = f"sqlite:///{tmp_path / 'm.db'}"
    upgrade(url)
    upgrade(url)                                               # دوباره اجرا بی‌خطاست
    eng = make_engine(url)
    assert REQUIRED <= set(inspect(eng).get_table_names())
    with eng.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
    assert diff == []


@pytest.fixture
def s():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    with make_session_factory(eng)() as db:
        yield db


def mk_user(db, tid):
    u = M.User(telegram_id=tid, first_name="x")
    db.add(u)
    db.flush()
    return u


def mk_song(db, title="t", artist="a", **kw):
    a = db.scalar(select(M.Artist).where(M.Artist.name_norm == artist)) or M.Artist(name=artist, name_norm=artist)
    db.add(a)
    db.flush()
    so = M.Song(title=title, title_norm=title, artist_id=a.id, **kw)
    db.add(so)
    db.flush()
    return so


def bad(db, obj):
    db.commit()                                     # حالت قبلی حفظ شود؛ rollback فقط شیء بد را برمی‌گرداند
    db.add(obj)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_foreign_keys_enforced(s):
    bad(s, M.Favorite(user_id=999, song_id=999))


def test_uniqueness(s):
    u = mk_user(s, 1)
    bad(s, M.User(telegram_id=1))
    s.add(M.UserPoint(user_id=u.id, points=3, reason="r", ref_key="k"))
    s.flush()
    bad(s, M.UserPoint(user_id=u.id, points=3, reason="r", ref_key="k"))         # امتیاز تکراری
    mk_user(s, 2)
    mk_song(s, "same", "art")
    bad(s, M.Song(title="x", title_norm="same", artist_id=s.scalar(select(M.Artist.id))))


def test_battle_rules(s):
    u1, u2 = mk_user(s, 1), mk_user(s, 2)
    a, b = mk_song(s, "a", "x"), mk_song(s, "b", "y")
    bad(s, M.Battle(song_a_id=a.id, song_b_id=a.id, starts_at=NOW, ends_at=NOW + timedelta(days=1)))
    bad(s, M.Battle(song_a_id=a.id, song_b_id=b.id, starts_at=NOW, ends_at=NOW))
    bt = M.Battle(song_a_id=a.id, song_b_id=b.id, starts_at=NOW, ends_at=NOW + timedelta(days=1))
    s.add(bt)
    s.flush()
    s.add(M.BattleVote(battle_id=bt.id, user_id=u1.id, song_id=a.id))
    s.flush()
    bad(s, M.BattleVote(battle_id=bt.id, user_id=u1.id, song_id=b.id))             # رأی تکراری یک کاربر


def test_song_file_requires_license_and_enums(s):
    a = M.Artist(name="a", name_norm="a")
    s.add(a)
    s.flush()
    bad(s, M.Song(title="t", title_norm="t", artist_id=a.id, telegram_file_id="F", license_status="unknown"))
    bad(s, M.Song(title="t", title_norm="t2", artist_id=a.id, status="weird"))
    s.add(M.Song(title="t", title_norm="t3", artist_id=a.id, telegram_file_id="F", license_status="licensed"))
    s.flush()
    bad(s, M.User(telegram_id=5, language="de"))


def test_publication_requires_approval_in_db(s):
    bad(s, M.PublicationQueue(status="published"))
    bad(s, M.PublicationQueue(status="approved"))
    s.add(M.PublicationQueue(status="draft"))
    s.add(M.PublicationQueue(status="approved", approved_at=NOW))
    s.flush()


def test_quiz_rules(s):
    bad(s, M.QuizQuestion(prompt="q", options=["a", "b", "c", "d"], correct_index=4))
    bad(s, M.QuizQuestion(prompt="q", options=["a", "b", "c", "d"], correct_index=1, status="approved"))     # بدون منبع قابل تأیید
    s.add(M.QuizQuestion(prompt="q", options=["a", "b", "c", "d"], correct_index=1, status="approved", source_note="official"))
    s.flush()


def test_match_pair_order_and_mixtape_positions(s):
    u1, u2 = mk_user(s, 1), mk_user(s, 2)
    bad(s, M.MusicMatch(user_low_id=u2.id, user_high_id=u1.id, similarity=0.5))
    bad(s, M.MusicMatch(user_low_id=u1.id, user_high_id=u2.id, similarity=1.5))
    s.add(M.MusicMatch(user_low_id=u1.id, user_high_id=u2.id, similarity=0.5))
    s.flush()
    bad(s, M.MusicMatch(user_low_id=u1.id, user_high_id=u2.id, similarity=0.6))
    a, b = mk_song(s, "a", "x"), mk_song(s, "b", "y")
    mt = M.Mixtape(owner_id=u1.id, title="m")
    s.add(mt)
    s.flush()
    s.add(M.MixtapeSong(mixtape_id=mt.id, song_id=a.id, position=0))
    s.flush()
    bad(s, M.MixtapeSong(mixtape_id=mt.id, song_id=b.id, position=0))


def test_cascade_on_user_delete_but_logs_kept(s):
    u = mk_user(s, 1)
    s.add_all([M.UserPreference(user_id=u.id), M.ActivityLog(user_id=u.id, action="x")])
    s.flush()
    s.delete(u)
    s.flush()
    assert s.scalar(select(M.UserPreference)) is None
    assert s.scalar(select(M.ActivityLog)).user_id is None


def test_naive_datetime_rejected_and_utc_roundtrip(s):
    with pytest.raises(Exception):
        s.add(M.Battle(song_a_id=1, song_b_id=2, starts_at=datetime(2026, 1, 1), ends_at=datetime(2026, 1, 2)))
        s.flush()
    s.rollback()
    u = mk_user(s, 1)
    s.commit()
    s.expire_all()
    assert s.get(M.User, u.id).created_at.tzinfo is not None


def test_seed_reference_idempotent(s):
    assert seed.seed_reference(s) == {"genres": 10, "moods": 7}
    assert seed.seed_reference(s) == {"genres": 0, "moods": 0}
    assert {m.slug for m in s.scalars(select(M.Mood))} >= {"happy", "calm", "romantic", "sad", "nostalgic", "energetic", "focus"}
