from datetime import datetime, timezone

from b2m.api import services as svc
from b2m.db import models as M, seed
from tests.conftest import login


def test_empty_home_is_honest(client):
    _, h = login(client)
    d = client.get("/api/home", headers=h).json()
    assert d["song_of_day"] is None and d["suggested"] == [] and d["trending"] == [] and d["trending_available"] is False
    assert d["daily_challenge"] is None and d["has_demo_data"] is False
    assert [f["key"] for f in d["features"]] == ["music_dna", "mood", "roulette", "battle", "quiz", "match", "mixtape", "trend_radar"]
    assert not any(f["available"] for f in d["features"])                       # هیچ قابلیتِ پیاده‌نشده‌ای «در دسترس» اعلام نمی‌شود


def test_home_with_songs_and_demo_flag(client, db):
    seed.seed_demo(db)
    _, h = login(client, lang="en")
    d = client.get("/api/home", headers=h).json()
    assert d["song_of_day"]["is_demo"] is True and d["has_demo_data"] is True and len(d["suggested"]) == 5
    assert d["suggested"][0]["genre"] in ("Pop", "Rock", "Traditional", "Electronic") and d["suggested_basis"] == "recent_in_archive"


def test_drafts_never_shown_and_song_of_day_rotates(client, db):
    seed.seed_demo(db)
    first = db.query(M.Song).first()
    first.status = "draft"
    db.commit()
    _, h = login(client)
    ids = {s["id"] for s in client.get("/api/home", headers=h).json()["suggested"]}
    assert first.id not in ids
    user = db.query(M.User).first()
    seen = {svc.build_home(db, user, datetime(2026, 11, d, tzinfo=timezone.utc))["song_of_day"]["id"] for d in range(1, 5)}
    assert len(seen) == 4 and first.id not in seen


def test_favorites_excluded_from_suggestions(client, db):
    seed.seed_demo(db)
    b, h = login(client)
    sid = db.query(M.Song).first().id
    db.add(M.Favorite(user_id=b["user"]["id"], song_id=sid))
    db.commit()
    assert sid not in {s["id"] for s in client.get("/api/home", headers=h).json()["suggested"]}


def test_trending_only_from_real_rows(client, db):
    now = datetime.now(timezone.utc)
    src = M.TrendSource(slug="x", name="Src X", kind="api", enabled=True)
    db.add(src)
    db.flush()
    db.add_all([M.TrendingTrack(source_id=src.id, region="GLOBAL", rank=1, title="T1", artist_name="A", fetched_at=now, external_url="https://x.test/1"),
                M.TrendingTrack(source_id=src.id, region="GLOBAL", rank=2, title="T2", fetched_at=now, review_status="rejected")])
    db.commit()
    _, h = login(client)
    d = client.get("/api/home", headers=h).json()
    assert d["trending_available"] and [t["title"] for t in d["trending"]] == ["T1"] and d["trending"][0]["source"] == "Src X"


def test_points_reflected_in_profile(client, db):
    b, h = login(client)
    db.add_all([M.UserPoint(user_id=b["user"]["id"], points=10, reason="a", ref_key="1"), M.UserPoint(user_id=b["user"]["id"], points=5, reason="b", ref_key="2")])
    db.commit()
    assert client.get("/api/me", headers=h).json()["points"] == 15
