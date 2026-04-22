"""Tests for automation_file.local.versioning."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import VersioningException
from automation_file.local.versioning import FileVersioner


def test_save_and_list_versions(tmp_path: Path) -> None:
    src = tmp_path / "data.txt"
    src.write_text("one", encoding="utf-8")
    versioner = FileVersioner(tmp_path / "versions")
    versioner.save_version(src)
    src.write_text("two", encoding="utf-8")
    versioner.save_version(src)
    entries = versioner.list_versions(src)
    assert [e.version for e in entries] == [1, 2]
    assert entries[0].path.read_text(encoding="utf-8") == "one"
    assert entries[1].path.read_text(encoding="utf-8") == "two"


def test_restore_older_version(tmp_path: Path) -> None:
    src = tmp_path / "data.txt"
    src.write_text("v1", encoding="utf-8")
    versioner = FileVersioner(tmp_path / "versions")
    versioner.save_version(src)
    src.write_text("v2", encoding="utf-8")
    versioner.save_version(src)
    src.write_text("current", encoding="utf-8")
    versioner.restore(src, 1)
    assert src.read_text(encoding="utf-8") == "v1"


def test_prune_keeps_most_recent(tmp_path: Path) -> None:
    src = tmp_path / "data.txt"
    versioner = FileVersioner(tmp_path / "versions")
    for i in range(5):
        src.write_text(f"v{i}", encoding="utf-8")
        versioner.save_version(src)
    removed = versioner.prune(src, keep=2)
    assert removed == 3
    remaining = versioner.list_versions(src)
    assert [e.version for e in remaining] == [4, 5]


def test_save_missing_source_raises(tmp_path: Path) -> None:
    versioner = FileVersioner(tmp_path / "versions")
    with pytest.raises(VersioningException):
        versioner.save_version(tmp_path / "missing.txt")


def test_restore_missing_version_raises(tmp_path: Path) -> None:
    src = tmp_path / "x.txt"
    src.write_text("hi", encoding="utf-8")
    versioner = FileVersioner(tmp_path / "versions")
    versioner.save_version(src)
    with pytest.raises(VersioningException):
        versioner.restore(src, 99)


def test_list_for_unknown_file_is_empty(tmp_path: Path) -> None:
    versioner = FileVersioner(tmp_path / "versions")
    assert not versioner.list_versions(tmp_path / "unseen.txt")


def test_prune_negative_keep_rejected(tmp_path: Path) -> None:
    src = tmp_path / "x.txt"
    src.write_text("x", encoding="utf-8")
    versioner = FileVersioner(tmp_path / "versions")
    versioner.save_version(src)
    with pytest.raises(VersioningException):
        versioner.prune(src, keep=-1)
