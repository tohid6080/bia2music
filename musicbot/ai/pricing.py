"""قیمت‌ها به دلار برای هر یک میلیون توکن (ورودی، خروجی) تا هزینه‌ی تقریبی نشان داده شود.
اگر مدل در این جدول نبود، هزینه «نامشخص» اعلام می‌شود (حدس زده نمی‌شود)."""
from __future__ import annotations

from typing import Optional

PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.0, 50.0),
}
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    price = PRICES.get(model)
    if not price:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
