"""In-memory login rate limiting.

Per (IP, username) and per-IP failure counters with a sliding window and a
cooldown after repeated failures. Deliberately in-memory: InfraMP is a
single-process SQLite app; state resets on restart, which is acceptable for a
brute-force backoff.
"""

from __future__ import annotations

import threading

from app.models.mixins import utcnow


class LoginRateLimiter:
    """Tracks login failures and blocks offenders for a cooldown window."""

    def __init__(self, max_attempts: int, window_seconds: int, cooldown_seconds: int):
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._cooldown = cooldown_seconds
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _now(self) -> float:
        # Monotonic clock would drift from wall-clock semantics across restarts
        # but is immune to clock jumps; wall-clock keeps semantics simple.
        return utcnow().timestamp()

    def _prune(self, key: tuple[str, str], now: float) -> list[float]:
        failures = self._failures.get(key, [])
        cutoff = now - self._window
        while failures and failures[0] < cutoff:
            failures.pop(0)
        return failures

    def is_blocked(self, ip: str, username: str) -> bool:
        now = self._now()
        with self._lock:
            for key in ((ip, ""), (ip, username.lower())):
                failures = self._prune(key, now)
                if len(failures) >= self._max_attempts and now - failures[-1] < self._cooldown:
                    return True
        return False

    def register_failure(self, ip: str, username: str) -> None:
        now = self._now()
        with self._lock:
            for key in ((ip, ""), (ip, username.lower())):
                failures = self._prune(key, now)
                failures.append(now)
                self._failures[key] = failures

    def reset(self, ip: str, username: str) -> None:
        with self._lock:
            self._failures.pop((ip, ""), None)
            self._failures.pop((ip, username.lower()), None)
