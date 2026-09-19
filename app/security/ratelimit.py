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

    # Failures dicts never grow without bound: a periodic sweep drops keys
    # whose tracking window has fully elapsed (mass username scans would
    # otherwise accumulate one entry per (ip, username) pair forever).
    MAX_FAILURE_KEYS = 10_000

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

    def _sweep(self) -> None:
        """Drop keys whose failure lists are empty (window fully elapsed)."""
        if len(self._failures) <= self.MAX_FAILURE_KEYS:
            return
        self._failures = {key: value for key, value in self._failures.items() if value}

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
            self._sweep()

    def reset(self, ip: str, username: str) -> None:
        with self._lock:
            self._failures.pop((ip, ""), None)
            self._failures.pop((ip, username.lower()), None)


def effective_client_ip(request, settings) -> str:
    """The client IP for rate limiting, honoring X-Forwarded-For from proxies.

    ``X-Forwarded-For`` is only consulted when the request's direct peer is in
    ``settings.trusted_proxy_ips``; the rightmost entry not produced by a
    trusted proxy is used, so a directly-connected client can never rotate its
    own bucket by sending the header itself.
    """
    direct = request.client.host if request.client else "unknown"
    trusted = settings.trusted_proxy_ips_list
    if direct not in trusted:
        return direct
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")
    for candidate in reversed(forwarded):
        candidate = candidate.strip()
        if not candidate:
            continue
        if candidate in trusted:
            continue
        return candidate
    return direct
