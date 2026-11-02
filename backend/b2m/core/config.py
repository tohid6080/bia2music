"""تنظیمات از متغیرهای محیطی (.env). هیچ Secret در کد نیست."""
from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

log = logging.getLogger("b2m.config")
BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class ConfigError(RuntimeError):
    """خطای پیکربندی با پیام قابل‌فهم برای کاربر."""


def _bool(v: Optional[str], default: bool = False) -> bool:
    return default if v is None or v == "" else v.strip().lower() in ("1", "true", "yes", "on")


def _int(v: Optional[str], default: int, name: str) -> int:
    if v is None or v.strip() == "":
        return default
    try:
        return int(v.strip())
    except ValueError:
        raise ConfigError(f"مقدار {name} باید عدد باشد.") from None


@dataclass(frozen=True)
class Settings:
    app_env: str
    bot_token: str
    admin_user_id: Optional[int]
    channel_id: str
    webapp_url: str
    database_url: str
    jwt_secret: str
    jwt_ttl_minutes: int
    initdata_max_age_seconds: int
    cors_origins: tuple
    webapp_dist: Path
    serve_webapp: bool
    trust_proxy_headers: bool
    auth_rate_per_minute: int
    api_rate_per_minute: int
    default_language: str

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    for p in (BACKEND_DIR / ".env", ROOT_DIR / ".env.b2m", Path.cwd() / ".env"):
        if p.is_file():
            load_dotenv(p, override=False)


def load_settings(env: Optional[Mapping[str, str]] = None, *, require_bot_token: bool = True) -> Settings:
    """env=None ← os.environ (پس از خواندن .env). در تست env صریح داده می‌شود."""
    if env is None:
        load_dotenv_files()
        env = os.environ
    g = env.get
    app_env = (g("APP_ENV") or "development").strip().lower()
    if app_env not in ("development", "production", "test"):
        raise ConfigError("APP_ENV باید development یا production باشد.")
    token = (g("BOT_TOKEN") or "").strip()
    if require_bot_token and not token:
        raise ConfigError("BOT_TOKEN خالی است. توکن را از @BotFather بگیرید و در فایل .env بگذارید.")
    admin_raw = (g("ADMIN_USER_ID") or "").strip()
    if admin_raw and not admin_raw.lstrip("-").isdigit():
        raise ConfigError("ADMIN_USER_ID باید شناسه‌ی عددی تلگرام باشد.")
    jwt_secret = (g("JWT_SECRET") or "").strip()
    if not jwt_secret:
        if app_env == "production":
            raise ConfigError("JWT_SECRET در حالت production الزامی است (حداقل ۳۲ نویسه‌ی تصادفی).")
        jwt_secret = secrets.token_urlsafe(48)
        log.warning("JWT_SECRET تنظیم نشده؛ برای این اجرا یک کلید موقت ساخته شد (با ری‌استارت، نشست‌ها باطل می‌شوند).")
    if app_env == "production" and len(jwt_secret) < 32:
        raise ConfigError("JWT_SECRET باید حداقل ۳۲ نویسه باشد.")
    webapp_url = (g("WEBAPP_URL") or "").strip().rstrip("/")
    if webapp_url and not (webapp_url.startswith("https://") or (app_env != "production" and webapp_url.startswith("http://localhost"))):
        raise ConfigError("WEBAPP_URL باید با https:// شروع شود (تلگرام آدرس غیر HTTPS را برای Mini App نمی‌پذیرد).")
    db_url = (g("DATABASE_URL") or f"sqlite:///{BACKEND_DIR / 'data' / 'bia2music.db'}").strip()
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    lang = (g("DEFAULT_LANGUAGE") or "fa").strip().lower()
    if lang not in ("fa", "en"):
        raise ConfigError("DEFAULT_LANGUAGE باید fa یا en باشد.")
    dist = Path(g("WEBAPP_DIST") or ROOT_DIR / "webapp" / "dist")
    return Settings(
        app_env=app_env, bot_token=token, admin_user_id=int(admin_raw) if admin_raw else None,
        channel_id=(g("CHANNEL_ID") or "@bia2music1395").strip(), webapp_url=webapp_url, database_url=db_url,
        jwt_secret=jwt_secret, jwt_ttl_minutes=_int(g("JWT_TTL_MINUTES"), 720, "JWT_TTL_MINUTES"),
        initdata_max_age_seconds=_int(g("INITDATA_MAX_AGE_SECONDS"), 86400, "INITDATA_MAX_AGE_SECONDS"),
        cors_origins=tuple(x.strip() for x in (g("CORS_ORIGINS") or "").split(",") if x.strip()),
        webapp_dist=dist, serve_webapp=_bool(g("SERVE_WEBAPP"), True), trust_proxy_headers=_bool(g("TRUST_PROXY_HEADERS"), False),
        auth_rate_per_minute=_int(g("AUTH_RATE_PER_MINUTE"), 20, "AUTH_RATE_PER_MINUTE"),
        api_rate_per_minute=_int(g("API_RATE_PER_MINUTE"), 240, "API_RATE_PER_MINUTE"), default_language=lang,
    )
