"""Tests for automation_file.utils.deduplicate."""

from __future__ import annotations

from pathlib import Path

from automation_file.utils.deduplicate import find_duplicates


def _write(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


def test_finds_simple_duplicates(tmp_path: Path) -> None:
    _write(tmp_path / "a.bin", b"same-content")
    _write(tmp_path / "b.bin", b"same-content")
    _write(tmp_path / "c.bin", b"unique")

    groups = find_duplicates(tmp_path)
    assert len(groups) == 1
    names = sorted(Path(p).name for p in groups[0])
    assert names == ["a.bin", "b.bin"]


def test_ignores_unique_sizes(tmp_path: Path) -> None:
    _write(tmp_path / "a.bin", b"x")
    _write(tmp_path / "b.bin", b"yy")
    _write(tmp_path / "c.bin", b"zzz")
    assert find_duplicates(tmp_path) == []


def test_same_size_different_content_not_grouped(tmp_path: Path) -> None:
    _write(tmp_path / "a.bin", b"aaaaaaaa")
    _write(tmp_path / "b.bin", b"bbbbbbbb")
    assert find_duplicates(tmp_path) == []


def test_nested_tree(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    _write(tmp_path / "a.bin", b"dup")
    _write(sub / "b.bin", b"dup")
    groups = find_duplicates(tmp_path)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_three_way_duplicate(tmp_path: Path) -> None:
    payload = b"triple-match"
    _write(tmp_path / "a", payload)
    _write(tmp_path / "b", payload)
    _write(tmp_path / "c", payload)
    groups = find_duplicates(tmp_path)
    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_min_size_skips_small_files(tmp_path: Path) -> None:
    _write(tmp_path / "a.bin", b"ab")
    _write(tmp_path / "b.bin", b"ab")
    assert find_duplicates(tmp_path, min_size=10) == []


def test_partial_hash_rules_out_with_matching_size(tmp_path: Path) -> None:
    # Same size, different content across the whole file, different first bytes
    size = 200_000
    a = b"A" * size
    b = b"B" * size
    _write(tmp_path / "a.bin", a)
    _write(tmp_path / "b.bin", b)
    assert find_duplicates(tmp_path, sample_bytes=16) == []


def test_full_hash_needed_when_prefix_matches(tmp_path: Path) -> None:
    prefix = b"X" * 64
    _write(tmp_path / "a.bin", prefix + b"tail-a")
    _write(tmp_path / "b.bin", prefix + b"tail-b")
    assert find_duplicates(tmp_path, sample_bytes=64) == []


def test_returns_groups_largest_first(tmp_path: Path) -> None:
    big = b"X" * 1024
    small = b"Y" * 32
    _write(tmp_path / "big-1.bin", big)
    _write(tmp_path / "big-2.bin", big)
    _write(tmp_path / "small-1.bin", small)
    _write(tmp_path / "small-2.bin", small)
    groups = find_duplicates(tmp_path)
    assert len(groups) == 2
    assert Path(groups[0][0]).name.startswith("big")


def test_returns_absolute_paths(tmp_path: Path) -> None:
    _write(tmp_path / "a.bin", b"dup")
    _write(tmp_path / "b.bin", b"dup")
    groups = find_duplicates(tmp_path)
    assert all(Path(p).is_absolute() for group in groups for p in group)


def test_missing_root_returns_empty(tmp_path: Path) -> None:
    assert find_duplicates(tmp_path / "nope") == []


def test_find_duplicates_registered_in_registry() -> None:
    from automation_file.core.action_registry import build_default_registry

    assert "FA_find_duplicates" in build_default_registry()
