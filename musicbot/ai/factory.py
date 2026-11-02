"""انتخاب ارائه‌دهنده AI. برای افزودن سرویس واقعی در آینده فقط کافی است یک سازنده به
PROVIDER_FACTORIES اضافه شود؛ بقیه پروژه تغییر نمی‌کند. در مرحله اول هیچ سرویس واقعی وصل نیست."""
from __future__ import annotations

from typing import Callable, Optional

import importlib.util

from musicbot.ai.base import AIProvider, AIStatus, MusicRecognizer
from musicbot.ai.claude import make_claude
from musicbot.ai.pricing import DEFAULT_CLAUDE_MODEL
from musicbot.ai.rule_based import RuleBasedProvider
from musicbot.config import Settings

# نام ارائه‌دهنده -> (نام متغیر محیطی کلید). فقط کلید «بودن» بررسی می‌شود؛ مقدار هرگز نمایش داده نمی‌شود.
KNOWN_PROVIDERS = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}

# مرحله بعد: PROVIDER_FACTORIES["claude"] = lambda settings: ClaudeProvider(...)
PROVIDER_FACTORIES: dict[str, Callable[[Settings], AIProvider]] = {"claude": make_claude}
# بسته‌ی پایتون لازم برای هر سرویس (اختیاری؛ نبودنش در وضعیت گزارش می‌شود)
SDK_MODULES = {"claude": "anthropic"}

# مرحله بعد: سرویس تخصصی تشخیص موسیقی (مثل fingerprint). فعلاً وجود ندارد.
RECOGNIZER_FACTORIES: dict[str, Callable[[Settings], MusicRecognizer]] = {}

_CONTENT_MODE = "قالب و قوانین (هوش مصنوعی واقعی نیست)"


def _key_for(settings: Settings, provider: str) -> Optional[str]:
    return {"claude": settings.anthropic_api_key, "openai": settings.openai_api_key}.get(provider)


def _real_provider_ready(settings: Settings) -> bool:
    p = settings.ai_provider
    return p in PROVIDER_FACTORIES and bool(_key_for(settings, p))


def _sdk_missing(provider: str) -> bool:
    mod = SDK_MODULES.get(provider)
    return bool(mod) and importlib.util.find_spec(mod) is None      # نبودن SDK مانع نیست؛ اتصال مستقیم HTTP جایگزین است


def create_provider(settings: Settings) -> AIProvider:
    """هرگز خطا نمی‌دهد؛ اگر AI واقعی آماده نباشد، ارائه‌دهنده قالب‌محور برگردانده می‌شود."""
    if _real_provider_ready(settings):
        try:
            return PROVIDER_FACTORIES[settings.ai_provider](settings)
        except Exception:  # noqa: BLE001 - بازگشت امن به حالت بدون AI
            pass
    return RuleBasedProvider()


class _NullRecognizer(MusicRecognizer):
    name = "none"
    is_available = False

    async def identify(self, audio_path):  # noqa: ANN001
        return None


def create_recognizer(settings: Settings) -> MusicRecognizer:
    return _NullRecognizer()


def get_ai_status(settings: Settings) -> AIStatus:
    p = settings.ai_provider
    recognizer = create_recognizer(settings)
    common = dict(
        requested_provider=p,
        content_mode_fa=_CONTENT_MODE,
        recognizer_active=recognizer.is_available,
        recognizer_name=recognizer.name,
    )
    if p in ("", "none"):
        return AIStatus(real_ai_active=False, active_provider="rule_based",
                        reason_fa="هوش مصنوعی واقعی غیرفعال است (حالت بدون هزینه).", **common)
    if p not in KNOWN_PROVIDERS:
        return AIStatus(real_ai_active=False, active_provider="rule_based",
                        reason_fa="مقدار AI_PROVIDER ناشناخته است؛ از حالت بدون AI استفاده می‌شود.", **common)
    if not _key_for(settings, p):
        return AIStatus(real_ai_active=False, active_provider="rule_based",
                        reason_fa=f"کلید API ({KNOWN_PROVIDERS[p]}) تنظیم نشده است.", **common)
    if p not in PROVIDER_FACTORIES:
        return AIStatus(real_ai_active=False, active_provider="rule_based",
                        reason_fa="کلید تنظیم شده، اما اتصال به این سرویس هنوز پیاده‌سازی نشده است.", **common)
    model = settings.ai_model or (DEFAULT_CLAUDE_MODEL if p == "claude" else None)
    via = "از اتصال مستقیم HTTP استفاده می‌شود (SDK رسمی نصب نیست)." if _sdk_missing(p) else "از SDK رسمی استفاده می‌شود."
    return AIStatus(real_ai_active=True, active_provider=p, model=model,
                    reason_fa=f"هوش مصنوعی واقعی فعال است. {via}", **{**common, "content_mode_fa": "هوش مصنوعی واقعی"})
