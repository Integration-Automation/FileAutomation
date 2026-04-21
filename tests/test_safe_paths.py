"""Tests for the path-traversal guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import PathTraversalException
from automation_file.local.safe_paths import is_within, safe_join


def test_safe_join_accepts_child(tmp_path: Path) -> None:
    resolved = safe_join(tmp_path, "inside/file.txt")
    assert resolved.is_relative_to(tmp_path.resolve())


def test_safe_join_rejects_dotdot(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathTraversalException):
        safe_join(root, "../outside.txt")


def test_safe_join_rejects_absolute_outside(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "other.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(PathTraversalException):
        safe_join(root, outside)


def test_is_within_returns_boolean(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    assert is_within(root, "a/b") is True
    assert is_within(root, "../outside") is False
