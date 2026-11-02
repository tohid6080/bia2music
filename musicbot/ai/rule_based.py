"""تولید کپشن/هشتگ بر پایه قالب و قوانین. این هوش مصنوعی واقعی نیست و هزینه‌ای ندارد."""
from __future__ import annotations

import random
import re
from typing import Optional

from musicbot.ai.base import AIProvider, CaptionRequest, CaptionResult

_MOOD_LINES = {
    "عاشقانه": ["برای دل‌های عاشق 💕", "یک آهنگ عاشقانه برای امشب"],
    "غمگین": ["برای دل‌های دلتنگ 🖤", "وقتی دلت می‌خواهد فقط گوش کنی"],
    "شاد": ["انرژی بگیر و لذت ببر ✨", "یک آهنگ شاد برای حال خوب"],
    "آرامش‌بخش": ["کمی آرامش با این قطعه 🌿", "چشم ببند و گوش کن"],
    "انگیزشی": ["برای ادامه دادن 💪", "انگیزه‌ات را با این آهنگ بساز"],
    "احساسی": ["آهنگی که حس‌اش را می‌فهمی", "با تمام احساس گوش کن"],
    "نوستالژیک": ["خاطرات قدیمی زنده شد 🕰️", "نوستالژی همیشگی"],
    "مناسب رانندگی": ["همراه جاده‌ی امشب 🚗", "پلی کن و برو"],
    "مناسب ورزش": ["برای تمرین امروز 🏋️", "ریتم تمرینت اینجاست"],
}
_DEFAULT_LINES = ["پیشنهاد امروز Bia2Music 🎧", "یک آهنگ خوب برای شما"]
_BASE_TAGS = ["#موزیک", "#Bia2Music"]
_LANG_TAGS = {"فارسی": "#موزیک_ایرانی", "انگلیسی": "#موزیک_خارجی", "ترکی": "#موزیک_ترکی", "عربی": "#موزیک_عربی"}


def _tag(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = re.sub(r"[^\w‌]+", "_", text.strip(), flags=re.UNICODE).strip("_").replace("‌", "_")
    return f"#{cleaned}" if cleaned else None


class RuleBasedProvider(AIProvider):
    name = "rule_based"
    is_real_ai = False

    def __init__(self, rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()

    async def generate_hashtags(self, request: CaptionRequest) -> list[str]:
        tags: list[str] = []
        for candidate in (
            _tag(request.artist),
            _LANG_TAGS.get(request.language or ""),
            _tag(request.genre),
            _tag(request.mood),
            *_BASE_TAGS,
        ):
            if candidate and candidate not in tags:
                tags.append(candidate)
        return tags

    async def generate_caption(self, request: CaptionRequest) -> CaptionResult:
        lines = _MOOD_LINES.get(request.mood or "", _DEFAULT_LINES)
        head = "🎵 " + " - ".join(p for p in (request.artist, request.title) if p) if (request.artist or request.title) else "🎵 آهنگ جدید"
        caption = f"{head}\n\n{self._rng.choice(lines)}"
        return CaptionResult(
            caption=caption,
            hashtags=await self.generate_hashtags(request),
            generated_by=self.name,
            is_real_ai=False,
        )
