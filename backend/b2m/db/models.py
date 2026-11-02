"""مدل داده‌ی Bia2Music. همه‌ی ۲۴ موجودیت از ابتدا تعریف شده‌اند تا مراحل بعد مهاجرت بزرگی نخواهند؛ مرحله‌ی ۱ فقط
users / admins / songs / artists / genres / moods / user_preferences / user_points / activity_logs / app_settings /
trending_tracks (خواندن) را به‌کار می‌گیرد. محدودیت‌ها (یکتایی، CHECK، کلید خارجی) تا حد ممکن در خود دیتابیس‌اند.

حذف حساب: جداول شخصی ON DELETE CASCADE؛ activity_logs ON DELETE SET NULL (بدون داده‌ی شخصی).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from b2m.core.timeutil import utcnow
from b2m.db.base import Base, UTCDateTime

PK = dict(primary_key=True, autoincrement=True)
CASCADE = dict(ondelete="CASCADE")


def _now():
    return mapped_column(UTCDateTime, default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, **PK)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    language: Mapped[str] = mapped_column(String(2), default="fa", nullable=False)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("language IN ('fa','en')", name="language_valid"),)


class Admin(Base):
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(Integer, **PK)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="admin", nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("role IN ('owner','admin')", name="role_valid"),)


class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), primary_key=True)
    content_languages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    profile_visibility: Mapped[str] = mapped_column(String(10), default="hidden", nullable=False)     # Music Match: پیش‌فرض پنهان
    match_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)                 # فقط با رضایت صریح
    updated_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("profile_visibility IN ('hidden','limited','public')", name="visibility_valid"),)


class Artist(Base):
    __tablename__ = "artists"
    id: Mapped[int] = mapped_column(Integer, **PK)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(2))


class Genre(Base):
    __tablename__ = "genres"
    id: Mapped[int] = mapped_column(Integer, **PK)
    slug: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name_fa: Mapped[str] = mapped_column(String(80), nullable=False)
    name_en: Mapped[str] = mapped_column(String(80), nullable=False)


class Mood(Base):
    __tablename__ = "moods"
    id: Mapped[int] = mapped_column(Integer, **PK)
    slug: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name_fa: Mapped[str] = mapped_column(String(80), nullable=False)
    name_en: Mapped[str] = mapped_column(String(80), nullable=False)


class Song(Base):
    __tablename__ = "songs"
    id: Mapped[int] = mapped_column(Integer, **PK)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    title_norm: Mapped[str] = mapped_column(String(300), nullable=False)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"), nullable=False)
    genre_id: Mapped[Optional[int]] = mapped_column(ForeignKey("genres.id", ondelete="SET NULL"))
    mood_id: Mapped[Optional[int]] = mapped_column(ForeignKey("moods.id", ondelete="SET NULL"))
    language_code: Mapped[Optional[str]] = mapped_column(String(8))
    release_year: Mapped[Optional[int]] = mapped_column(Integer)
    cover_url: Mapped[Optional[str]] = mapped_column(String(500))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))                 # لینک رسمی/مرجع
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(300))           # فقط اگر مجوز انتشار فایل هست
    license_status: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)    # داده‌ی نمونه‌ی توسعه؛ در production ممنوع
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        UniqueConstraint("artist_id", "title_norm", name="uq_songs_artist_title"),
        CheckConstraint("license_status IN ('unknown','official_link','licensed')", name="license_valid"),
        CheckConstraint("status IN ('draft','published','archived')", name="status_valid"),
        CheckConstraint("telegram_file_id IS NULL OR license_status = 'licensed'", name="file_requires_license"),
        Index("ix_songs_status_created", "status", "created_at"),
        Index("ix_songs_genre", "genre_id"), Index("ix_songs_mood", "mood_id"),
    )


class MusicDnaProfile(Base):
    __tablename__ = "music_dna_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), primary_key=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    scores: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = _now()


class Favorite(Base):
    __tablename__ = "favorites"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", **CASCADE), primary_key=True)
    created_at: Mapped[datetime] = _now()


class Battle(Base):
    __tablename__ = "battles"
    id: Mapped[int] = mapped_column(Integer, **PK)
    song_a_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="RESTRICT"), nullable=False)
    song_b_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), default="daily", nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="scheduled", nullable=False)
    winner_song_id: Mapped[Optional[int]] = mapped_column(ForeignKey("songs.id", ondelete="SET NULL"))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    __table_args__ = (
        CheckConstraint("song_a_id <> song_b_id", name="distinct_songs"), CheckConstraint("ends_at > starts_at", name="time_order"),
        CheckConstraint("kind IN ('daily','weekly','custom')", name="kind_valid"),
        CheckConstraint("status IN ('scheduled','open','closed','cancelled')", name="status_valid"),
        Index("ix_battles_status_time", "status", "starts_at"),
    )


class BattleVote(Base):
    __tablename__ = "battle_votes"
    id: Mapped[int] = mapped_column(Integer, **PK)
    battle_id: Mapped[int] = mapped_column(ForeignKey("battles.id", **CASCADE), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), nullable=False)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("battle_id", "user_id", name="uq_battle_votes_once"), Index("ix_battle_votes_battle_song", "battle_id", "song_id"))


class Quiz(Base):
    __tablename__ = "quizzes"
    id: Mapped[int] = mapped_column(Integer, **PK)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), default="daily", nullable=False)
    starts_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    ends_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    __table_args__ = (CheckConstraint("kind IN ('daily','weekly','custom')", name="kind_valid"),
                      CheckConstraint("status IN ('draft','open','closed')", name="status_valid"))


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    id: Mapped[int] = mapped_column(Integer, **PK)
    quiz_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quizzes.id", ondelete="SET NULL"))
    topic: Mapped[str] = mapped_column(String(20), default="artist", nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, nullable=False)                    # دقیقاً ۴ گزینه (در سرویس اعتبارسنجی می‌شود)
    correct_index: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text)
    source_note: Mapped[Optional[str]] = mapped_column(String(300))                # منبع قابل تأیید؛ بدون آن سؤال منتشر نمی‌شود
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    __table_args__ = (CheckConstraint("correct_index BETWEEN 0 AND 3", name="correct_range"),
                      CheckConstraint("status IN ('draft','approved','retired')", name="status_valid"),
                      CheckConstraint("status <> 'approved' OR source_note IS NOT NULL", name="approved_needs_source"))


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id: Mapped[int] = mapped_column(Integer, **PK)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), nullable=False)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", **CASCADE), nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    answers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    __table_args__ = (UniqueConstraint("user_id", "quiz_id", name="uq_quiz_attempts_once"), CheckConstraint("score >= 0", name="score_nonneg"),
                      Index("ix_quiz_attempts_quiz_score", "quiz_id", "score"))


class UserPoint(Base):
    """دفتر امتیاز (Bia Points). ref_key هر رویداد را یکتا می‌کند تا امتیاز تکراری ثبت نشود."""
    __tablename__ = "user_points"
    id: Mapped[int] = mapped_column(Integer, **PK)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    ref_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("user_id", "ref_key", name="uq_user_points_ref"), CheckConstraint("points <> 0", name="points_nonzero"),
                      Index("ix_user_points_user_time", "user_id", "created_at"))


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    earned_at: Mapped[datetime] = _now()


class Mixtape(Base):
    __tablename__ = "mixtapes"
    id: Mapped[int] = mapped_column(Integer, **PK)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    cover_url: Mapped[Optional[str]] = mapped_column(String(500))
    visibility: Mapped[str] = mapped_column(String(10), default="private", nullable=False)
    share_slug: Mapped[Optional[str]] = mapped_column(String(32), unique=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("visibility IN ('private','unlisted','public')", name="visibility_valid"), Index("ix_mixtapes_owner", "owner_id"))


class MixtapeSong(Base):
    __tablename__ = "mixtape_songs"
    mixtape_id: Mapped[int] = mapped_column(ForeignKey("mixtapes.id", **CASCADE), primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", **CASCADE), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("mixtape_id", "position", name="uq_mixtape_songs_position"), CheckConstraint("position >= 0", name="position_nonneg"))


class MusicMatch(Base):
    __tablename__ = "music_matches"
    id: Mapped[int] = mapped_column(Integer, **PK)
    user_low_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), nullable=False)      # همیشه کوچک‌تر ← یک جفت = یک ردیف
    user_high_id: Mapped[int] = mapped_column(ForeignKey("users.id", **CASCADE), nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    shared: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="suggested", nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("user_low_id", "user_high_id", name="uq_music_matches_pair"),
                      CheckConstraint("user_low_id < user_high_id", name="pair_order"),
                      CheckConstraint("similarity BETWEEN 0 AND 1", name="similarity_range"),
                      CheckConstraint("status IN ('suggested','accepted','declined','blocked')", name="status_valid"))


class TrendSource(Base):
    __tablename__ = "trend_sources"
    id: Mapped[int] = mapped_column(Integer, **PK)
    slug: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), default="link", nullable=False)
    terms_url: Mapped[Optional[str]] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)      # هیچ منبعی بدون تأیید مدیر فعال نمی‌شود
    last_fetch_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    last_status: Mapped[Optional[str]] = mapped_column(String(20))
    __table_args__ = (CheckConstraint("kind IN ('api','link')", name="kind_valid"),)


class TrendingTrack(Base):
    __tablename__ = "trending_tracks"
    id: Mapped[int] = mapped_column(Integer, **PK)
    source_id: Mapped[int] = mapped_column(ForeignKey("trend_sources.id", **CASCADE), nullable=False)
    region: Mapped[str] = mapped_column(String(16), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    artist_name: Mapped[Optional[str]] = mapped_column(String(200))
    external_url: Mapped[Optional[str]] = mapped_column(String(500))
    published_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    song_id: Mapped[Optional[int]] = mapped_column(ForeignKey("songs.id", ondelete="SET NULL"))
    review_status: Mapped[str] = mapped_column(String(10), default="new", nullable=False)
    __table_args__ = (UniqueConstraint("source_id", "region", "fetched_at", "rank", name="uq_trending_snapshot_rank"),
                      CheckConstraint("rank >= 1", name="rank_positive"),
                      CheckConstraint("review_status IN ('new','saved','approved','rejected')", name="review_valid"),
                      Index("ix_trending_fetched", "fetched_at"))


class PublicationQueue(Base):
    __tablename__ = "publication_queue"
    id: Mapped[int] = mapped_column(Integer, **PK)
    song_id: Mapped[Optional[int]] = mapped_column(ForeignKey("songs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(12), default="song", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    published_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    channel_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        CheckConstraint("status IN ('draft','approved','published','cancelled','failed')", name="status_valid"),
        # انتشار بدون تأییدِ ثبت‌شده‌ی مدیر در خود دیتابیس ممکن نیست
        CheckConstraint("status NOT IN ('approved','published') OR (approved_at IS NOT NULL)", name="publish_needs_approval"),
        Index("ix_publication_status", "status", "scheduled_at"),
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id: Mapped[int] = mapped_column(Integer, **PK)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor: Mapped[str] = mapped_column(String(10), default="user", nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)       # هرگز initData/توکن/اطلاعات شخصی
    created_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("actor IN ('user','admin','system','bot')", name="actor_valid"), Index("ix_activity_action_time", "action", "created_at"))


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = _now()
    updated_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
