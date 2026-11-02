"""محدودکننده‌ی نرخ ساده‌ی درون‌حافظه (پنجره‌ی لغزان). برای یک پردازش کافی است؛ با چند پردازش باید Redis جایگزین شود."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock
        self._ops = 0

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = self._clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            self._ops += 1
            if self._ops % 500 == 0:                     # پاک‌سازی کلیدهای قدیمی تا حافظه رشد نکند
                for k in [k for k, d in self._hits.items() if not d or now - d[-1] >= window]:
                    self._hits.pop(k, None)
            return True
