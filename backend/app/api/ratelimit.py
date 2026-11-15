"""Small in-process sliding-window rate limiter (per API process).

Used to slow down credential guessing on login/registration. It is best-effort: with several
API processes each keeps its own window. A shared limiter is part of production hardening.
"""

import time
from collections import defaultdict, deque

from app.services.errors import DomainError


class TooManyRequestsError(DomainError):
    status_code = 429
    title = "Too many requests"


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_s: float) -> None:
        self.max_events = max_events
        self.window_s = window_s
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> None:
        """Record an attempt; raise 429 if the key exceeded its budget in the window."""
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > self.window_s:
            events.popleft()
        if len(events) >= self.max_events:
            retry = int(self.window_s - (now - events[0])) + 1
            raise TooManyRequestsError(f"Too many attempts; try again in {retry}s")
        events.append(now)
        if len(self._events) > 10_000:  # bound memory: drop idle keys
            for k in [k for k, v in self._events.items() if not v or now - v[-1] > self.window_s]:
                del self._events[k]
