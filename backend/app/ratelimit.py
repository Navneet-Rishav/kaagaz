"""Per-user sliding-window rate limits for endpoints that cost money (OCR, LLM, speech).

In-memory, so limits reset on restart and are per process. That is fine for one free-tier instance;
several instances would need a shared store (Postgres or Redis).
"""

import time
from collections import defaultdict, deque
from threading import Lock

from app.errors import ApiError


class RateLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._clock = clock

    def hit(self, bucket: str, user_id: str, limit: int, window_s: float = 3600) -> None:
        now = self._clock()
        with self._lock:
            q = self._hits[(bucket, user_id)]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                retry = int(q[0] + window_s - now) + 1
                raise ApiError(
                    429, "rate_limited", f"Too many requests. Try again in {retry // 60 + 1} min.", {"retry_after_s": retry}
                )
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
