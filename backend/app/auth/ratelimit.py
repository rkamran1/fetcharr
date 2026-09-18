"""Login rate limiting: 5 attempts per minute per client IP (requirements §9).

In memory on purpose: fetcharr runs as a single process (requirements §6.1).
"""

import math
import time
from collections import deque

LOGIN_ATTEMPTS = 5
WINDOW_SECONDS = 60.0


class LoginRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[float]] = {}

    def hit(self, key: str) -> int | None:
        """Record an attempt. Returns ``None`` if allowed, else the seconds to wait."""
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        for stale in [k for k, a in self._attempts.items() if a[-1] <= cutoff]:
            del self._attempts[stale]
        attempts = self._attempts.setdefault(key, deque())
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= LOGIN_ATTEMPTS:
            return max(1, math.ceil(attempts[0] - cutoff))
        attempts.append(now)
        return None
