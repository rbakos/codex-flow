import time
from collections import defaultdict, deque
from typing import Deque


class SlidingWindowRateLimiter:
    def __init__(self, max_per_minute: int = 1000):
        self.max = max_per_minute
        self.events: dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.time()
        window_start = now - 60
        q = self.events[key]
        while q and q[0] < window_start:
            q.popleft()
        if len(q) < self.max:
            q.append(now)
            remaining = self.max - len(q)
            return True, remaining
        return False, 0

