"""Per-user flood protection: at most `limit` actions per `window` seconds (admins are exempt)."""
from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int = 12, window: float = 6.0):
        self.limit, self.window = limit, window
        self.hits: dict[int, deque] = {}
        self.warned: dict[int, float] = {}

    def allow(self, uid: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self.hits.setdefault(uid, deque())
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def should_warn(self, uid: int, now: float | None = None) -> bool:
        """True at most once per window, so a flooder gets one polite message instead of a reply storm."""
        now = time.monotonic() if now is None else now
        if now - self.warned.get(uid, -1e9) > self.window:
            self.warned[uid] = now
            return True
        return False

    def cleanup(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for uid in [u for u, q in self.hits.items() if not q or now - q[-1] > self.window]:
            self.hits.pop(uid, None)
        for uid in [u for u, t in self.warned.items() if now - t > self.window * 4]:
            self.warned.pop(uid, None)


limiter = RateLimiter()
