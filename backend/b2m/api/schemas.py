from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    init_data: str = Field(min_length=1, max_length=8192)


class UserOut(BaseModel):
    id: int
    first_name: str
    username: Optional[str]
    language: Literal["fa", "en"]
    is_admin: bool
    points: int
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class MeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["fa", "en"]


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: Literal[True]


class SongOut(BaseModel):
    id: int
    title: str
    artist: str
    genre: Optional[str]
    mood: Optional[str]
    language_code: Optional[str]
    cover_url: Optional[str]
    source_url: Optional[str]
    is_demo: bool


class FeatureOut(BaseModel):
    key: str
    stage: int
    available: bool


class HomeOut(BaseModel):
    song_of_day: Optional[SongOut]
    song_of_day_basis: str
    trending: list[dict]
    trending_available: bool
    daily_challenge: Optional[dict]
    suggested: list[SongOut]
    suggested_basis: str
    features: list[FeatureOut]
    has_demo_data: bool
