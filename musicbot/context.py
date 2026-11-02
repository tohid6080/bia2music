from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from telegram.ext import Application

from musicbot.ai import AIProvider, MusicRecognizer
from musicbot.channel import ChannelService
from musicbot.config import Settings
from musicbot.db import Repositories
from musicbot.ratelimit import RateLimiter

KEY = "app_ctx"


@dataclass
class AppContext:
    settings: Settings
    repos: Repositories
    ai_provider: AIProvider
    recognizer: MusicRecognizer
    channel: ChannelService
    bot_username: str | None = None
    limiter: RateLimiter = field(default_factory=RateLimiter)
    radar: Any = None

    def effective_channel_ref(self) -> str | None:
        """تنظیم ذخیره‌شده در دیتابیس بر CHANNEL_ID محیطی اولویت دارد (تغییر کانال بدون تغییر کد)."""
        active = self.repos.channel.get_active()
        return active.channel_ref if active else self.settings.channel_id


def get_ctx(application: Application) -> AppContext:
    return application.bot_data[KEY]


def _post_options(self):
    from musicbot.publishing.captions import PostOptions

    if not self.bot_username:
        return PostOptions()
    st = self.repos.settings
    return PostOptions(
        footer=f"🤖 @{self.bot_username}" if st.get("promo_footer", "0") == "1" else None,
        button_url=f"https://t.me/{self.bot_username}" if st.get("promo_button", "1") == "1" else None,
    )


AppContext.post_options = _post_options


def _ai_daily_limit(self) -> int:
    try:
        return max(0, int(self.repos.settings.get("ai_daily_limit", "100")))
    except ValueError:
        return 100


def _caption_provider(self):
    """AI واقعی فقط تا سقف روزانه‌ی تماس؛ بعد از آن (یا اگر AI خاموش است) قالب و قوانین."""
    from musicbot.ai.rule_based import RuleBasedProvider

    if self.ai_provider.is_real_ai and self.repos.metrics.totals(1).get("ai_calls", 0) < self.ai_daily_limit():
        return self.ai_provider
    return RuleBasedProvider()


def _record_ai_usage(self, input_tokens: int, output_tokens: int) -> None:
    m = self.repos.metrics
    m.incr("ai_calls")
    m.incr("ai_in", input_tokens)
    m.incr("ai_out", output_tokens)


AppContext.ai_daily_limit = _ai_daily_limit
AppContext.caption_provider = _caption_provider
AppContext.record_ai_usage = _record_ai_usage


def _radar_service(self):
    """سرویس رادار (ساخت تنبل: تا وقتی لازم نباشد هیچ اتصال شبکه‌ای ساخته نمی‌شود)."""
    if self.radar is None:
        from musicbot.radar.service import RadarService

        self.radar = RadarService(self.settings, self.repos)
    return self.radar


AppContext.radar_service = _radar_service
