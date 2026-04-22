"""Tests for automation_file.local.diff_ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import DiffException, PathTraversalException
from automation_file.local.diff_ops import (
    DirDiff,
    apply_dir_diff,
    diff_dirs,
    diff_text_files,
    iter_dir_diff,
)


def _populate(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_diff_dirs_empty_for_identical(tmp_path: Path) -> None:
    left = tmp_path / "a"
    right = tmp_path / "b"
    _populate(left, {"same.txt": "x", "sub/y.txt": "y"})
    _populate(right, {"same.txt": "x", "sub/y.txt": "y"})
    result = diff_dirs(left, right)
    assert result.is_empty()


def test_diff_dirs_detects_added_removed_changed(tmp_path: Path) -> None:
    left = tmp_path / "a"
    right = tmp_path / "b"
    _populate(left, {"keep.txt": "same", "change.txt": "v1", "remove.txt": "bye"})
    _populate(right, {"keep.txt": "same", "change.txt": "v2", "add.txt": "hi"})
    result = diff_dirs(left, right)
    assert result.added == ("add.txt",)
    assert result.removed == ("remove.txt",)
    assert result.changed == ("change.txt",)


def test_apply_dir_diff_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _populate(src, {"a.txt": "alpha", "sub/b.txt": "beta"})
    _populate(dst, {"old.txt": "gone", "sub/b.txt": "old-beta"})
    diff = diff_dirs(dst, src)
    apply_dir_diff(diff, dst, src)
    # Now dst should mirror src
    reverse = diff_dirs(dst, src)
    assert reverse.is_empty()


def test_apply_dir_diff_rejects_traversal(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    bad_diff = DirDiff(added=("../escape.txt",))
    target = tmp_path / "dst"
    target.mkdir()
    with pytest.raises(PathTraversalException):
        apply_dir_diff(bad_diff, target, src)


def test_diff_text_files_unified_output(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    b.write_text("alpha\nBETA\ngamma\n", encoding="utf-8")
    patch = diff_text_files(a, b)
    assert "-beta" in patch
    assert "+BETA" in patch


def test_diff_dirs_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(DiffException):
        diff_dirs(tmp_path / "nope", tmp_path)


def test_iter_dir_diff_labels_entries() -> None:
    diff = DirDiff(added=("a",), removed=("b",), changed=("c",))
    entries = list(iter_dir_diff(diff))
    assert ("added", "a") in entries
    assert ("removed", "b") in entries
    assert ("changed", "c") in entries
