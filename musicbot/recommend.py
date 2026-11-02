"""پیشنهاد آهنگ: امتیازدهی ساده و شفاف (بدون AI). بر اساس علایقی که خود کاربر انتخاب کرده و پسندهایش."""
from __future__ import annotations

import random
from typing import Iterable, Optional

from musicbot.db import Repositories

W_GENRE, W_MOOD, W_LANG = 2.0, 2.0, 1.0


def score_song(song: dict, interests: Iterable[tuple[str, str]]) -> float:
    score = 0.0
    for kind, ref in interests:
        if kind == "genre" and str(song.get("genre_id")) == ref:
            score += W_GENRE
        elif kind == "mood" and str(song.get("mood_id")) == ref:
            score += W_MOOD
        elif kind == "language" and song.get("language_code") == ref:
            score += W_LANG
    return score


def suggest_for_user(repos: Repositories, user_id: int, k: int = 3, exclude: Iterable[int] = (),
                     rng: Optional[random.Random] = None) -> list[dict]:
    """علایق فقط در صورت رضایت کاربر خوانده می‌شود. بدون علایق، ترکیبی از محبوب‌ترین‌ها و تازه‌ترین‌ها."""
    rng = rng or random.Random()
    excluded = set(exclude)
    songs = [s for s in repos.songs.all_published() if s["id"] not in excluded]
    if not songs:
        return []
    interests = repos.userdata.interests(user_id) if repos.userdata.has_consent(user_id) else set()
    liked = repos.userdata.liked_ids(user_id) if interests or repos.userdata.has_consent(user_id) else set()
    pool = [s for s in songs if s["id"] not in liked] or songs
    all_likes = repos.userdata.like_counts()
    likes = {s["id"]: all_likes.get(s["id"], 0) for s in pool}
    # امتیاز = تطبیق با علایق + کمی محبوبیت + کمی تصادف تا هر بار یکسان نباشد
    ranked = sorted(pool, key=lambda s: score_song(s, interests) + 0.3 * likes[s["id"]] + rng.random() * 0.9, reverse=True)
    return ranked[:k]


def audience_rank(repos: Repositories, songs: list[dict]) -> list[tuple[dict, float]]:
    """برای مدیر: آهنگ‌های آماده را بر اساس تطابق با علایق تجمیعی مخاطبان مرتب می‌کند."""
    agg = repos.userdata.aggregate()
    weights = {("genre", ref): c for ref, c in agg["genre"].items()}
    weights.update({("mood", ref): c for ref, c in agg["mood"].items()})
    weights.update({("language", ref): c for ref, c in agg["language"].items()})
    out = []
    for s in songs:
        sc = 0.0
        for (kind, ref), c in weights.items():
            sc += score_song(s, [(kind, ref)]) * c
        out.append((s, sc))
    return sorted(out, key=lambda x: (-x[1], -x[0]["id"]))
