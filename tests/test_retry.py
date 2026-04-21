"""Tests for the retry_on_transient decorator."""

from __future__ import annotations

import pytest

from automation_file.core.retry import retry_on_transient
from automation_file.exceptions import RetryExhaustedException


def test_retry_returns_first_success() -> None:
    attempts = {"n": 0}

    @retry_on_transient(max_attempts=3, backoff_base=0.0)
    def sometimes_fails() -> int:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ConnectionError("boom")
        return 42

    assert sometimes_fails() == 42
    assert attempts["n"] == 2


def test_retry_exhausted_wraps_cause() -> None:
    @retry_on_transient(max_attempts=2, backoff_base=0.0)
    def always_fails() -> None:
        raise TimeoutError("never")

    with pytest.raises(RetryExhaustedException) as excinfo:
        always_fails()
    assert isinstance(excinfo.value.__cause__, TimeoutError)


def test_retry_does_not_catch_unrelated() -> None:
    @retry_on_transient(max_attempts=3, backoff_base=0.0, retriable=(ConnectionError,))
    def raise_unrelated() -> None:
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        raise_unrelated()


def test_retry_invalid_max_attempts() -> None:
    with pytest.raises(ValueError):
        retry_on_transient(max_attempts=0)
