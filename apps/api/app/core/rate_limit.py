"""Small single-worker launch throttle; use a shared gateway limiter in production."""

import asyncio
from collections import defaultdict, deque
import time

from fastapi import HTTPException


class LocalRateLimiter:
    def __init__(self, limit: int = 20, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        now = time.monotonic()
        async with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= now - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                raise HTTPException(status_code=429, detail="rate_limit_exceeded")
            bucket.append(now)
            # Avoid retaining inactive IPs indefinitely in the demo worker.
            if len(self._events) > 1000:
                for k, entries in list(self._events.items()):
                    if not entries or entries[-1] < now - self.window_seconds:
                        del self._events[k]
