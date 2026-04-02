"""In-memory sliding window rate limiter — zero dependencies."""
from __future__ import annotations

import time
import threading
from collections import defaultdict
from typing import Dict, List


class RateLimiter:
    def __init__(self, requests_per_minute: int = 120, burst: int = 20):
        self.requests_per_minute = requests_per_minute
        self.burst = burst
        self._window: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 60.0

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        cutoff = now - 60.0
        stale = [ip for ip, ts in self._window.items() if not ts or ts[-1] < cutoff]
        for ip in stale:
            del self._window[ip]

    def is_allowed(self, client_ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            cutoff = now - 60.0
            timestamps = self._window[client_ip]
            # prune old entries for this IP
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)
            limit = self.requests_per_minute + self.burst
            if len(timestamps) >= limit:
                return False
            timestamps.append(now)
            return True

    def remaining(self, client_ip: str) -> int:
        now = time.monotonic()
        with self._lock:
            cutoff = now - 60.0
            timestamps = self._window[client_ip]
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)
            limit = self.requests_per_minute + self.burst
            return max(0, limit - len(timestamps))

    def get_retry_after(self, client_ip: str) -> int:
        now = time.monotonic()
        with self._lock:
            cutoff = now - 60.0
            timestamps = self._window[client_ip]
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)
            if not timestamps:
                return 0
            oldest = timestamps[0]
            wait = 60.0 - (now - oldest)
            return max(1, int(wait) + 1)
