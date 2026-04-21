"""Tests for the config hot-reload watcher."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from automation_file import AutomationConfig, ConfigException, ConfigWatcher

_INITIAL = """
[defaults]
dedup_seconds = 30
"""

_UPDATED = """
[defaults]
dedup_seconds = 99
"""


def test_start_returns_initial_config(tmp_path: Path) -> None:
    config_path = tmp_path / "automation_file.toml"
    config_path.write_text(_INITIAL, encoding="utf-8")
    seen: list[AutomationConfig] = []
    watcher = ConfigWatcher(config_path, seen.append, interval=1.0)
    try:
        initial = watcher.start()
        assert initial.section("defaults")["dedup_seconds"] == 30
    finally:
        watcher.stop()


def test_check_once_detects_mtime_change(tmp_path: Path) -> None:
    config_path = tmp_path / "automation_file.toml"
    config_path.write_text(_INITIAL, encoding="utf-8")
    seen: list[AutomationConfig] = []
    watcher = ConfigWatcher(config_path, seen.append, interval=60.0)
    try:
        watcher.start()
        # Force a fingerprint delta: rewrite with different content + push mtime forward
        time.sleep(0.01)
        config_path.write_text(_UPDATED, encoding="utf-8")
        assert watcher.check_once() is True
        assert seen and seen[-1].section("defaults")["dedup_seconds"] == 99
    finally:
        watcher.stop()


def test_check_once_returns_false_when_unchanged(tmp_path: Path) -> None:
    config_path = tmp_path / "automation_file.toml"
    config_path.write_text(_INITIAL, encoding="utf-8")
    watcher = ConfigWatcher(config_path, lambda _cfg: None, interval=60.0)
    try:
        watcher.start()
        assert watcher.check_once() is False
    finally:
        watcher.stop()


def test_zero_interval_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigException):
        ConfigWatcher(tmp_path / "x.toml", lambda _cfg: None, interval=0)


def test_reload_failure_logged_but_not_fatal(tmp_path: Path) -> None:
    config_path = tmp_path / "automation_file.toml"
    config_path.write_text(_INITIAL, encoding="utf-8")
    seen: list[AutomationConfig] = []
    watcher = ConfigWatcher(config_path, seen.append, interval=60.0)
    try:
        watcher.start()
        time.sleep(0.01)
        config_path.write_text("not = [valid", encoding="utf-8")
        # Reload raises ConfigException internally; watcher just logs and returns False.
        assert watcher.check_once() is False
        # Fix the file and verify we pick back up.
        time.sleep(0.01)
        config_path.write_text(_UPDATED, encoding="utf-8")
        assert watcher.check_once() is True
    finally:
        watcher.stop()
