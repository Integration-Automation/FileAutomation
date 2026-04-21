"""Tests for automation_file.local.dir_ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import DirNotExistsException
from automation_file.local import dir_ops


def test_create_dir_new(tmp_path: Path) -> None:
    target = tmp_path / "new_dir"
    assert dir_ops.create_dir(str(target)) is True
    assert target.is_dir()


def test_create_dir_idempotent(tmp_path: Path) -> None:
    dir_ops.create_dir(str(tmp_path / "d"))
    assert dir_ops.create_dir(str(tmp_path / "d")) is True


def test_copy_dir(tmp_path: Path, sample_dir: Path) -> None:
    destination = tmp_path / "copied"
    assert dir_ops.copy_dir(str(sample_dir), str(destination)) is True
    assert (destination / "a.txt").is_file()
    assert (destination / "nested" / "d.txt").is_file()


def test_copy_dir_missing_source(tmp_path: Path) -> None:
    with pytest.raises(DirNotExistsException):
        dir_ops.copy_dir(str(tmp_path / "nope"), str(tmp_path / "out"))


def test_rename_dir(tmp_path: Path, sample_dir: Path) -> None:
    target = tmp_path / "renamed"
    assert dir_ops.rename_dir(str(sample_dir), str(target)) is True
    assert target.is_dir()
    assert not sample_dir.exists()


def test_rename_dir_missing_source(tmp_path: Path) -> None:
    with pytest.raises(DirNotExistsException):
        dir_ops.rename_dir(str(tmp_path / "missing"), str(tmp_path / "out"))


def test_remove_dir_tree(tmp_path: Path, sample_dir: Path) -> None:
    assert dir_ops.remove_dir_tree(str(sample_dir)) is True
    assert not sample_dir.exists()


def test_remove_dir_tree_missing(tmp_path: Path) -> None:
    assert dir_ops.remove_dir_tree(str(tmp_path / "nope")) is False
