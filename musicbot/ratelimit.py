"""محدودیت نرخ ساده در حافظه: جلوگیری از سوءاستفاده/اسپم کاربران عادی."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable


class RateLimiter:
    def __init__(self, max_events: int = 20, window: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self.max_events, self.window, self._clock = max_events, window, clock
        self._events: dict[int, deque] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = self._clock()
        q = self._events[user_id]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        if len(self._events) > 5000:  # جلوگیری از رشد بی‌پایان حافظه
            for uid in [u for u, d in self._events.items() if not d or now - d[-1] > self.window]:
                self._events.pop(uid, None)
        return True
