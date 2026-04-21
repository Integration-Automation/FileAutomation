"""Tests for Quota enforcement."""
from __future__ import annotations

import time

import pytest

from automation_file.core.quota import Quota
from automation_file.exceptions import QuotaExceededException


def test_check_size_passes_under_cap() -> None:
    Quota(max_bytes=100).check_size(50)


def test_check_size_fails_over_cap() -> None:
    with pytest.raises(QuotaExceededException):
        Quota(max_bytes=10).check_size(100)


def test_check_size_zero_disables_cap() -> None:
    Quota(max_bytes=0).check_size(10**12)


def test_time_budget_passes_fast_block() -> None:
    with Quota(max_seconds=1.0).time_budget("fast"):
        pass


def test_time_budget_fails_slow_block() -> None:
    with pytest.raises(QuotaExceededException):
        with Quota(max_seconds=0.05).time_budget("slow"):
            time.sleep(0.1)


def test_time_budget_zero_disables_cap() -> None:
    with Quota(max_seconds=0).time_budget("fast"):
        time.sleep(0.05)
