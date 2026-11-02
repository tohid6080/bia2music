"""رابط‌های لایه AI Provider. بقیه برنامه فقط به این رابط‌ها وابسته است، نه به سرویس خاصی."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CaptionRequest:
    title: Optional[str] = None
    artist: Optional[str] = None
    language: Optional[str] = None   # نام فارسی یا کد
    genre: Optional[str] = None
    mood: Optional[str] = None


@dataclass
class CaptionResult:
    caption: str
    hashtags: list[str] = field(default_factory=list)
    generated_by: str = ""
    is_real_ai: bool = False


class AIProvider(ABC):
    """ارائه‌دهنده تولید متن. نسخه‌های واقعی (Claude/OpenAI/...) در آینده این کلاس را پیاده می‌کنند."""

    name: str = "base"
    is_real_ai: bool = False
    supports_classification: bool = False

    @abstractmethod
    async def generate_caption(self, request: CaptionRequest) -> CaptionResult: ...

    @abstractmethod
    async def generate_hashtags(self, request: CaptionRequest) -> list[str]: ...


@dataclass
class RecognitionResult:
    title: Optional[str]
    artist: Optional[str]
    confidence: float = 0.0
    source: str = ""


class MusicRecognizer(ABC):
    """شناسایی آهنگ از روی فایل صوتی؛ باید سرویس تخصصی (مثل fingerprint) باشد نه مدل متنی."""

    name: str = "none"
    is_available: bool = False

    @abstractmethod
    async def identify(self, audio_path: Path) -> Optional[RecognitionResult]: ...


@dataclass(frozen=True)
class AIStatus:
    """وضعیتی که در پنل ربات نمایش داده می‌شود."""

    requested_provider: str
    real_ai_active: bool
    active_provider: str
    content_mode_fa: str
    reason_fa: str
    recognizer_active: bool
    recognizer_name: str
    model: Optional[str] = None
