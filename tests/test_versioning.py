"""Tests for automation_file.local.versioning."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import VersioningException
from automation_file.local import versioning
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


def _long_source(tmp_path: Path, leaf: str = "data.txt") -> Path:
    directory = tmp_path / ("d" * 40) / ("e" * 40)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / leaf


def test_a_long_source_path_gets_a_short_directory(tmp_path: Path) -> None:
    src = _long_source(tmp_path)
    src.write_text("one", encoding="utf-8")
    versioner = FileVersioner(tmp_path / "v")
    entry = versioner.save_version(src)
    bucket = entry.path.parent
    assert len(bucket.name) <= 80
    assert bucket.name.rsplit("__", 1)[0].endswith("data.txt")
    assert [e.version for e in versioner.list_versions(src)] == [1]
    src.write_text("two", encoding="utf-8")
    assert versioner.save_version(src).path.parent == bucket
    versioner.restore(src, 1)
    assert src.read_text(encoding="utf-8") == "one"
    assert versioner.prune(src, keep=1) == 1


def test_long_paths_with_the_same_tail_do_not_share_a_directory(tmp_path: Path) -> None:
    first = _long_source(tmp_path / "a")
    second = _long_source(tmp_path / "b")
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    versioner = FileVersioner(tmp_path / "v")
    one = versioner.save_version(first)
    two = versioner.save_version(second)
    assert one.path.parent != two.path.parent
    assert [e.path.read_text(encoding="utf-8") for e in versioner.list_versions(first)] == ["first"]
    assert [e.path.read_text(encoding="utf-8") for e in versioner.list_versions(second)] == [
        "second"
    ]


def test_a_short_source_path_keeps_the_readable_directory_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(versioning, "_MAX_BUCKET_NAME", 10_000)
    src = tmp_path / "data.txt"
    src.write_text("one", encoding="utf-8")
    try:
        entry = FileVersioner(tmp_path / "v").save_version(src)
    except OSError:
        pytest.skip("this temp path is too long for the readable directory name")
    assert entry.path.parent.name.endswith("__sep__data.txt")


def test_a_directory_created_under_the_long_name_keeps_being_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "data.txt"
    src.write_text("old", encoding="utf-8")
    versioner = FileVersioner(tmp_path / "v")
    monkeypatch.setattr(versioning, "_MAX_BUCKET_NAME", 10_000)
    try:
        legacy = versioner.save_version(src)
    except OSError:
        pytest.skip("this temp path is too long for the readable directory name")
    monkeypatch.setattr(versioning, "_MAX_BUCKET_NAME", 1)
    src.write_text("new", encoding="utf-8")
    again = versioner.save_version(src)
    assert again.path.parent == legacy.path.parent
    assert [e.version for e in versioner.list_versions(src)] == [1, 2]
