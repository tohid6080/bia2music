"""منطق کسب‌وکار مرحله‌ی ۱ (کاربر، ادمین، امتیاز، لاگ، خانه). روترها فقط HTTP را می‌شناسند."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from b2m.core.config import Settings
from b2m.core.initdata import TelegramUser
from b2m.core.timeutil import utcnow
from b2m.db import models as M

log = logging.getLogger("b2m.services")
# امکانات هشت‌گانه و مرحله‌ی ساخت‌شان؛ available فقط وقتی True می‌شود که واقعاً پیاده شده باشد.
FEATURES = [("music_dna", 2, False), ("mood", 2, False), ("roulette", 2, False), ("battle", 3, False), ("quiz", 3, False),
            ("match", 4, False), ("mixtape", 4, False), ("trend_radar", 5, False)]


def log_activity(db: Session, action: str, *, user_id: Optional[int] = None, actor: str = "user", detail: Optional[dict] = None) -> None:
    db.add(M.ActivityLog(user_id=user_id, actor=actor, action=action[:60], detail=detail or {}))


def is_admin(settings: Settings, db: Session, user: M.User) -> bool:
    if settings.admin_user_id is not None and user.telegram_id == settings.admin_user_id:
        return True
    return db.scalar(select(M.Admin.id).where(M.Admin.user_id == user.id)) is not None


def points_total(db: Session, user_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(M.UserPoint.points), 0)).where(M.UserPoint.user_id == user_id)) or 0)


def pick_language(tg_lang: Optional[str], default: str) -> str:
    return "fa" if (tg_lang or "").lower().startswith("fa") else ("en" if tg_lang else default)


def upsert_user(db: Session, settings: Settings, tg: TelegramUser) -> tuple[M.User, bool]:
    """کاربر را می‌سازد یا به‌روز می‌کند. زبان فقط هنگام ساخت از زبان تلگرام تعیین می‌شود (انتخاب بعدی کاربر حفظ می‌شود)."""
    now = utcnow()
    for _ in range(2):                                          # رقابت دو درخواست هم‌زمان ← بار دوم کاربر موجود را می‌خواند
        user = db.scalar(select(M.User).where(M.User.telegram_id == tg.id))
        created = user is None
        if created:
            user = M.User(telegram_id=tg.id, username=tg.username, first_name=tg.first_name, language=pick_language(tg.language_code, settings.default_language))
            db.add(user)
        else:
            user.username, user.first_name, user.last_seen_at = tg.username, tg.first_name, now
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            continue
        if created:
            db.add(M.UserPreference(user_id=user.id))
        if settings.admin_user_id is not None and tg.id == settings.admin_user_id and not db.scalar(select(M.Admin.id).where(M.Admin.user_id == user.id)):
            db.add(M.Admin(user_id=user.id, role="owner"))
        db.commit()
        return user, created
    raise RuntimeError("upsert_user failed")


def delete_account(db: Session, user: M.User) -> None:
    """حذف کامل داده‌ی کاربر (کلیدهای خارجی CASCADE). فقط شناسه‌ی داخلی در لاگ می‌ماند (بدون هویت)."""
    uid = user.id
    db.execute(delete(M.User).where(M.User.id == uid))
    log_activity(db, "account_deleted", user_id=None, detail={"internal_id": uid})
    db.commit()


def song_out(s: M.Song, artist: str, genre: Optional[M.Genre], mood: Optional[M.Mood], lang: str) -> dict:
    g = (genre.name_fa if lang == "fa" else genre.name_en) if genre else None
    m = (mood.name_fa if lang == "fa" else mood.name_en) if mood else None
    return dict(id=s.id, title=s.title, artist=artist, genre=g, mood=m, language_code=s.language_code, cover_url=s.cover_url, source_url=s.source_url, is_demo=s.is_demo)


def _published(db: Session, lang: str, q_extra=None, limit: int = 10, order=None):
    q = (select(M.Song, M.Artist.name, M.Genre, M.Mood).join(M.Artist, M.Artist.id == M.Song.artist_id)
         .outerjoin(M.Genre, M.Genre.id == M.Song.genre_id).outerjoin(M.Mood, M.Mood.id == M.Song.mood_id).where(M.Song.status == "published"))
    if q_extra is not None:
        q = q.where(q_extra)
    q = q.order_by(order if order is not None else M.Song.id.desc()).limit(limit)
    return [song_out(s, a, g, m, lang) for s, a, g, m in db.execute(q).all()]


def build_home(db: Session, user: M.User, today: Optional[datetime] = None) -> dict:
    """همه‌ی بخش‌ها از داده‌ی واقعی دیتابیس‌اند. چیزی که داده ندارد خالی برمی‌گردد؛ هرگز ساختگی تولید نمی‌شود."""
    lang = user.language
    day = (today or utcnow()).date()
    total = db.scalar(select(func.count()).select_from(M.Song).where(M.Song.status == "published")) or 0
    sod = None
    if total:
        idx = day.toordinal() % total                           # انتخاب روزانه‌ی قطعی و بدون تصادف: همه امروز یک آهنگ را می‌بینند
        sid = db.scalar(select(M.Song.id).where(M.Song.status == "published").order_by(M.Song.id).offset(idx).limit(1))
        sod = _published(db, lang, M.Song.id == sid, 1)[0]
    fav_ids = select(M.Favorite.song_id).where(M.Favorite.user_id == user.id)
    suggested = _published(db, lang, M.Song.id.not_in(fav_ids), 10)
    last = db.scalar(select(func.max(M.TrendingTrack.fetched_at)))
    trending, avail = [], False
    if last:
        rows = db.scalars(select(M.TrendingTrack).where(M.TrendingTrack.fetched_at == last, M.TrendingTrack.review_status != "rejected")
                          .order_by(M.TrendingTrack.rank).limit(10)).all()
        trending = [dict(rank=r.rank, title=r.title, artist=r.artist_name, region=r.region, url=r.external_url,
                         source=db.scalar(select(M.TrendSource.name).where(M.TrendSource.id == r.source_id))) for r in rows]
        avail = bool(trending)
    return dict(song_of_day=sod, song_of_day_basis="daily_rotation_of_archive", trending=trending, trending_available=avail, daily_challenge=None,
                suggested=suggested, suggested_basis="recent_in_archive",
                features=[dict(key=k, stage=s, available=a) for k, s, a in FEATURES],
                has_demo_data=bool(db.scalar(select(M.Song.id).where(M.Song.is_demo.is_(True)).limit(1))))
