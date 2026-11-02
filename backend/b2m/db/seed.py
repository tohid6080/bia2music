"""داده‌ی مرجع واقعی (سبک‌ها و حال‌وهواها) + داده‌ی نمونه‌ی صریحاً «دمو» فقط برای توسعه."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

GENRES = [("pop", "پاپ", "Pop"), ("rock", "راک", "Rock"), ("rap", "رپ", "Rap / Hip-Hop"), ("traditional", "سنتی", "Traditional"),
          ("electronic", "الکترونیک", "Electronic"), ("rnb", "آر اند بی", "R&B"), ("jazz", "جز", "Jazz"), ("classical", "کلاسیک", "Classical"),
          ("folk", "فولک / محلی", "Folk"), ("indie", "ایندی", "Indie")]
MOODS = [("happy", "شاد", "Happy"), ("calm", "آرام", "Calm"), ("romantic", "عاشقانه", "Romantic"), ("sad", "غمگین", "Sad"),
         ("nostalgic", "نوستالژیک", "Nostalgic"), ("energetic", "پرانرژی", "Energetic"), ("focus", "تمرکزی", "Focus")]


def norm(s: str) -> str:
    s = (s or "").lower().replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"[^\w]+", " ", s, flags=re.UNICODE).strip()


def seed_reference(db: Session) -> dict:
    from b2m.db.models import Genre, Mood

    added = {"genres": 0, "moods": 0}
    for model, rows, key in ((Genre, GENRES, "genres"), (Mood, MOODS, "moods")):
        have = set(db.scalars(select(model.slug)))
        for slug, fa, en in rows:
            if slug not in have:
                db.add(model(slug=slug, name_fa=fa, name_en=en))
                added[key] += 1
    db.commit()
    return added


DEMO = [("Sample Track One", "Demo Artist A", "pop", "happy", "en"), ("Sample Track Two", "Demo Artist B", "rock", "energetic", "en"),
        ("آهنگ نمونه یک", "هنرمند نمونه الف", "pop", "calm", "fa"), ("آهنگ نمونه دو", "هنرمند نمونه ب", "traditional", "nostalgic", "fa"),
        ("Sample Track Three", "Demo Artist C", "electronic", "focus", "en")]


def seed_demo(db: Session) -> int:
    """نمونه‌ی آشکارا ساختگی برای دیدن رابط. is_demo=True و در حالت production ممنوع (در CLI بررسی می‌شود)."""
    from b2m.db.models import Artist, Genre, Mood, Song

    seed_reference(db)
    n = 0
    for title, artist, g, m, lang in DEMO:
        a = db.scalar(select(Artist).where(Artist.name_norm == norm(artist)))
        if not a:
            a = Artist(name=artist, name_norm=norm(artist))
            db.add(a)
            db.flush()
        if db.scalar(select(Song.id).where(Song.artist_id == a.id, Song.title_norm == norm(title))):
            continue
        db.add(Song(title=title, title_norm=norm(title), artist_id=a.id, genre_id=db.scalar(select(Genre.id).where(Genre.slug == g)),
                    mood_id=db.scalar(select(Mood.id).where(Mood.slug == m)), language_code=lang, status="published", is_demo=True))
        n += 1
    db.commit()
    return n
