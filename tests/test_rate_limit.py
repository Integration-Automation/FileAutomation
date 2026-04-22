"""Tests for automation_file.core.rate_limit."""

from __future__ import annotations

import threading
import time

import pytest

from automation_file.core.rate_limit import RateLimiter
from automation_file.exceptions import RateLimitExceededException


def test_try_acquire_succeeds_within_capacity() -> None:
    limiter = RateLimiter(rate=10, burst=5)
    for _ in range(5):
        assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False


def test_acquire_blocks_until_refill() -> None:
    limiter = RateLimiter(rate=50, burst=1)
    limiter.acquire()  # drain the bucket
    start = time.monotonic()
    limiter.acquire(timeout=1.0)
    elapsed = time.monotonic() - start
    # refill cadence is 50 tokens/sec -> ~20ms; allow generous upper bound
    assert 0.010 <= elapsed <= 0.5


def test_acquire_timeout_raises() -> None:
    limiter = RateLimiter(rate=1, burst=1)
    limiter.acquire()  # empty
    with pytest.raises(RateLimitExceededException):
        limiter.acquire(timeout=0.05)


def test_acquire_more_than_capacity_rejected() -> None:
    limiter = RateLimiter(rate=10, burst=2)
    with pytest.raises(ValueError):
        limiter.acquire(tokens=5)


def test_rate_below_zero_rejected() -> None:
    with pytest.raises(ValueError):
        RateLimiter(rate=0)


def test_wraps_decorator_counts_invocations() -> None:
    limiter = RateLimiter(rate=1000, burst=3)
    calls: list[int] = []

    @limiter.wraps(tokens=1)
    def step(x: int) -> int:
        calls.append(x)
        return x * 2

    assert [step(i) for i in range(3)] == [0, 2, 4]
    assert calls == [0, 1, 2]


def test_concurrent_acquires_serialize() -> None:
    limiter = RateLimiter(rate=20, burst=2)
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        ok = limiter.try_acquire()
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 2  # burst size
    assert results.count(False) == 8
