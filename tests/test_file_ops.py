"""Tests for automation_file.local.file_ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import DirNotExistsException, FileNotExistsException
from automation_file.local import file_ops


def test_copy_file_success(tmp_path: Path, sample_file: Path) -> None:
    target = tmp_path / "copy.txt"
    assert file_ops.copy_file(str(sample_file), str(target)) is True
    assert target.read_text(encoding="utf-8") == "hello world"


def test_copy_file_missing_source(tmp_path: Path) -> None:
    missing = tmp_path / "missing.txt"
    with pytest.raises(FileNotExistsException):
        file_ops.copy_file(str(missing), str(tmp_path / "out.txt"))


def test_copy_file_no_metadata(tmp_path: Path, sample_file: Path) -> None:
    target = tmp_path / "plain.txt"
    assert file_ops.copy_file(str(sample_file), str(target), copy_metadata=False) is True
    assert target.is_file()


def test_copy_specify_extension_file(tmp_path: Path, sample_dir: Path) -> None:
    out_dir = tmp_path / "collected"
    out_dir.mkdir()
    file_ops.copy_specify_extension_file(str(sample_dir), "txt", str(out_dir))
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == ["a.txt", "b.txt", "d.txt"]


def test_copy_specify_extension_file_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(DirNotExistsException):
        file_ops.copy_specify_extension_file(str(tmp_path / "nope"), "txt", str(tmp_path))


def test_copy_all_file_to_dir(tmp_path: Path, sample_dir: Path) -> None:
    destination = tmp_path / "inbox"
    destination.mkdir()
    assert file_ops.copy_all_file_to_dir(str(sample_dir), str(destination)) is True
    assert (destination / "sample_dir" / "a.txt").is_file()


def test_copy_all_file_to_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(DirNotExistsException):
        file_ops.copy_all_file_to_dir(str(tmp_path / "missing"), str(tmp_path))


def test_rename_file_unique_names(sample_dir: Path) -> None:
    """Regression: original impl renamed every match to the same name, overwriting."""
    assert file_ops.rename_file(str(sample_dir), "renamed", file_extension="txt") is True
    root_names = sorted(p.name for p in sample_dir.iterdir() if p.is_file())
    nested_names = sorted(p.name for p in (sample_dir / "nested").iterdir())
    # a.txt + b.txt renamed in place; nested/d.txt renamed inside its own folder.
    assert root_names == ["c.log", "renamed_0.txt", "renamed_1.txt"]
    assert nested_names == ["renamed_2.txt"]


def test_rename_file_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(DirNotExistsException):
        file_ops.rename_file(str(tmp_path / "nope"), "x")


def test_remove_file(sample_file: Path) -> None:
    assert file_ops.remove_file(str(sample_file)) is True
    assert not sample_file.exists()


def test_remove_file_missing(tmp_path: Path) -> None:
    assert file_ops.remove_file(str(tmp_path / "nope")) is False


def test_create_file_writes_content(tmp_path: Path) -> None:
    path = tmp_path / "new.txt"
    file_ops.create_file(str(path), "payload")
    assert path.read_text(encoding="utf-8") == "payload"
