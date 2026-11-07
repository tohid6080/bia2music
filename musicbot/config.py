"""بارگذاری و اعتبارسنجی تنظیمات از متغیرهای محیطی (.env). هیچ رازی در کد نیست."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigError(Exception):
    """خطای تنظیمات؛ پیام آن فارسی و بدون افشای مقدار رازها است."""


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    admin_user_id: int
    channel_id: Optional[str]
    database_path: Path
    log_level: str
    timezone: str
    ai_provider: str = "none"
    ai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = field(default=None, repr=False)
    openai_api_key: Optional[str] = field(default=None, repr=False)
    youtube_api_key: Optional[str] = field(default=None, repr=False)
    lastfm_api_key: Optional[str] = field(default=None, repr=False)
    webhook_url: Optional[str] = None          # آدرس HTTPS عمومی سرویس (حالت وب‌هوک؛ برای میزبان‌هایی که می‌خوابند)
    port: int = 8080
    telegram_backup: bool = False              # پشتیبان خودکار پین‌شده برای مدیر (بازیابی پس از پاک‌شدن دیسک)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _get(env: Mapping[str, str], key: str) -> Optional[str]:
    value = env.get(key)
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_settings(env: Optional[Mapping[str, str]] = None, *, load_dotenv_file: bool = True) -> Settings:
    if env is None:
        if load_dotenv_file:
            from dotenv import load_dotenv

            load_dotenv()
        env = os.environ

    token = _get(env, "TELEGRAM_BOT_TOKEN")
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN تنظیم نشده است. آن را در فایل .env قرار دهید.")
    if not TOKEN_RE.match(token):
        raise ConfigError("فرمت TELEGRAM_BOT_TOKEN نامعتبر است. توکن را دوباره از BotFather کپی کنید.")

    admin_raw = _get(env, "ADMIN_USER_ID")
    if not admin_raw:
        raise ConfigError("ADMIN_USER_ID تنظیم نشده است. شناسه عددی تلگرام خود را در .env بنویسید.")
    try:
        admin_id = int(admin_raw)
    except ValueError:
        raise ConfigError("ADMIN_USER_ID باید فقط عدد باشد.") from None
    if admin_id <= 0:
        raise ConfigError("ADMIN_USER_ID باید یک عدد مثبت باشد.")

    tz = _get(env, "TIMEZONE") or "Asia/Tehran"
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"TIMEZONE نامعتبر است: {tz}") from None

    level = (_get(env, "LOG_LEVEL") or "INFO").upper()
    if level not in VALID_LOG_LEVELS:
        raise ConfigError("LOG_LEVEL نامعتبر است. یکی از DEBUG/INFO/WARNING/ERROR/CRITICAL.")

    ai_provider = (_get(env, "AI_PROVIDER") or "none").lower()
    webhook_url = (_get(env, "WEBHOOK_URL") or "").rstrip("/") or None
    if webhook_url and not webhook_url.startswith("https://"):
        raise ConfigError("WEBHOOK_URL باید با https:// شروع شود.")
    try:
        port = int(_get(env, "PORT") or "8080")
    except ValueError:
        raise ConfigError("PORT باید عدد باشد.") from None
    backup_raw = (_get(env, "TELEGRAM_BACKUP") or ("1" if webhook_url else "0")).lower()

    return Settings(
        bot_token=token,
        admin_user_id=admin_id,
        channel_id=_get(env, "CHANNEL_ID"),
        database_path=Path(_get(env, "DATABASE_PATH") or "data/musicbot.sqlite3"),
        log_level=level,
        timezone=tz,
        ai_provider=ai_provider,
        ai_model=_get(env, "AI_MODEL"),
        anthropic_api_key=_get(env, "ANTHROPIC_API_KEY"),
        openai_api_key=_get(env, "OPENAI_API_KEY"),
        youtube_api_key=_get(env, "YOUTUBE_API_KEY"),
        lastfm_api_key=_get(env, "LASTFM_API_KEY"),
        webhook_url=webhook_url,
        port=port,
        telegram_backup=backup_raw in ("1", "true", "yes", "on"),
    )
