"""Token-bucket rate limiter.

:class:`RateLimiter` refills at ``rate`` tokens/second up to a burst capacity.
Callers acquire N tokens before issuing a protected call; when empty, the
limiter either blocks (up to ``timeout``) or raises
:class:`RateLimitExceededException`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from automation_file.exceptions import RateLimitExceededException

F = TypeVar("F", bound=Callable[..., Any])


class RateLimiter:
    """Thread-safe token bucket."""

    def __init__(self, rate: float, burst: float | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        cap = float(burst) if burst is not None else float(rate)
        if cap <= 0:
            raise ValueError("burst must be > 0")
        self._rate = float(rate)
        self._capacity = cap
        self._tokens = cap
        self._updated = time.monotonic()
        self._cv = threading.Condition()

    @property
    def capacity(self) -> float:
        return self._capacity

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._updated = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Take ``tokens`` without blocking. Return True on success."""
        if tokens <= 0:
            raise ValueError("tokens must be > 0")
        with self._cv:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def acquire(self, tokens: float = 1.0, timeout: float | None = None) -> None:
        """Block until ``tokens`` are available.

        Raises :class:`RateLimitExceededException` if ``timeout`` elapses first.
        ``timeout=None`` waits indefinitely; ``timeout=0`` fails immediately.
        """
        if tokens <= 0:
            raise ValueError("tokens must be > 0")
        if tokens > self._capacity:
            raise ValueError(f"tokens {tokens} exceeds capacity {self._capacity}")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while True:
                self._refill_locked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                needed = tokens - self._tokens
                wait_for = needed / self._rate
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RateLimitExceededException(
                            f"rate limit: could not acquire {tokens} tokens within timeout"
                        )
                    wait_for = min(wait_for, remaining)
                self._cv.wait(timeout=wait_for)

    def wraps(self, tokens: float = 1.0, timeout: float | None = None) -> Callable[[F], F]:
        """Return a decorator that acquires ``tokens`` before each call."""

        def decorator(func: F) -> F:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                self.acquire(tokens=tokens, timeout=timeout)
                return func(*args, **kwargs)

            return wrapper  # type: ignore[return-value]

        return decorator
