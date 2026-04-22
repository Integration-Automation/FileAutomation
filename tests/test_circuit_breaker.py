"""Tests for automation_file.core.circuit_breaker."""

from __future__ import annotations

import time

import pytest

from automation_file.core.circuit_breaker import CircuitBreaker
from automation_file.exceptions import CircuitOpenException


def test_closed_passes_through() -> None:
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
    assert cb.call(lambda x: x + 1, 1) == 2
    assert cb.state == "closed"


def test_opens_after_threshold_failures() -> None:
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)

    def boom() -> None:
        raise ConnectionError("nope")

    for _ in range(2):
        with pytest.raises(ConnectionError):
            cb.call(boom)
    assert cb.state == "open"
    with pytest.raises(CircuitOpenException):
        cb.call(lambda: 1)


def test_half_open_allows_probe_and_closes_on_success() -> None:
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError("x")))
    assert cb.state == "open"

    time.sleep(0.08)
    assert cb.state == "half_open"
    assert cb.call(lambda: "ok") == "ok"
    assert cb.state == "closed"


def test_half_open_failure_reopens() -> None:
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError("x")))
    time.sleep(0.08)
    assert cb.state == "half_open"
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError("y")))
    assert cb.state == "open"


def test_non_retriable_exception_does_not_count() -> None:
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0, retriable=(ConnectionError,))
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("v")))
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("v")))
    assert cb.state == "closed"


def test_wraps_decorator_applies_breaker() -> None:
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)

    @cb.wraps()
    def flaky() -> None:
        raise ConnectionError("boom")

    with pytest.raises(ConnectionError):
        flaky()
    with pytest.raises(CircuitOpenException):
        flaky()


def test_reset_restores_closed() -> None:
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError("x")))
    assert cb.state == "open"
    cb.reset()
    assert cb.state == "closed"
    assert cb.call(lambda: 42) == 42


def test_invalid_thresholds_rejected() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0)
    with pytest.raises(ValueError):
        CircuitBreaker(recovery_timeout=0)
