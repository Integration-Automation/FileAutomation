"""Tests for automation_file.local.trash."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import VersioningException
from automation_file.local.trash import (
    empty_trash,
    list_trash,
    restore_from_trash,
    send_to_trash,
)


def test_send_and_list(tmp_path: Path) -> None:
    src = tmp_path / "doomed.txt"
    src.write_text("bye", encoding="utf-8")
    bin_dir = tmp_path / ".trash"
    entry = send_to_trash(src, bin_dir)
    assert not src.exists()
    assert entry.path.exists()
    listing = list_trash(bin_dir)
    assert len(listing) == 1
    assert listing[0].trash_id == entry.trash_id


def test_restore_returns_to_origin(tmp_path: Path) -> None:
    src = tmp_path / "dir" / "file.txt"
    src.parent.mkdir()
    src.write_text("hi", encoding="utf-8")
    bin_dir = tmp_path / ".trash"
    entry = send_to_trash(src, bin_dir)
    restored = restore_from_trash(entry.trash_id, bin_dir)
    assert restored == src
    assert restored.read_text(encoding="utf-8") == "hi"


def test_restore_rejects_existing_target(tmp_path: Path) -> None:
    src = tmp_path / "collide.txt"
    src.write_text("a", encoding="utf-8")
    bin_dir = tmp_path / ".trash"
    entry = send_to_trash(src, bin_dir)
    src.write_text("occupant", encoding="utf-8")
    with pytest.raises(VersioningException):
        restore_from_trash(entry.trash_id, bin_dir)


def test_restore_to_alt_destination(tmp_path: Path) -> None:
    src = tmp_path / "orig.txt"
    src.write_text("hello", encoding="utf-8")
    bin_dir = tmp_path / ".trash"
    entry = send_to_trash(src, bin_dir)
    dest = tmp_path / "elsewhere" / "new.txt"
    restored = restore_from_trash(entry.trash_id, bin_dir, destination=dest)
    assert restored == dest
    assert dest.read_text(encoding="utf-8") == "hello"


def test_empty_trash_removes_everything(tmp_path: Path) -> None:
    bin_dir = tmp_path / ".trash"
    for i in range(3):
        f = tmp_path / f"f{i}.txt"
        f.write_text("x", encoding="utf-8")
        send_to_trash(f, bin_dir)
    removed = empty_trash(bin_dir)
    assert removed > 0
    assert not list_trash(bin_dir)


def test_send_nonexistent_raises(tmp_path: Path) -> None:
    with pytest.raises(VersioningException):
        send_to_trash(tmp_path / "nothing", tmp_path / ".trash")


def test_restore_unknown_id_raises(tmp_path: Path) -> None:
    bin_dir = tmp_path / ".trash"
    bin_dir.mkdir()
    with pytest.raises(VersioningException):
        restore_from_trash("missing-id", bin_dir)


def test_send_directory(tmp_path: Path) -> None:
    src = tmp_path / "subdir"
    src.mkdir()
    (src / "inner.txt").write_text("hi", encoding="utf-8")
    bin_dir = tmp_path / ".trash"
    entry = send_to_trash(src, bin_dir)
    assert entry.is_dir is True
    assert (entry.path / "inner.txt").read_text(encoding="utf-8") == "hi"
