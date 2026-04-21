"""Tests for automation_file.utils.fast_find."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.utils import fast_find as ff
from automation_file.utils.fast_find import fast_find, has_os_index, scandir_find


def _seed(tmp_path: Path) -> None:
    (tmp_path / "a.log").write_text("a", encoding="utf-8")
    (tmp_path / "b.log").write_text("b", encoding="utf-8")
    (tmp_path / "c.txt").write_text("c", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "d.log").write_text("d", encoding="utf-8")
    (nested / "e.txt").write_text("e", encoding="utf-8")
    deep = nested / "deep"
    deep.mkdir()
    (deep / "f.log").write_text("f", encoding="utf-8")


def test_scandir_find_lists_all_files_by_default(tmp_path: Path) -> None:
    _seed(tmp_path)
    names = sorted(Path(p).name for p in scandir_find(tmp_path))
    assert names == ["a.log", "b.log", "c.txt", "d.log", "e.txt", "f.log"]


def test_scandir_find_glob_pattern(tmp_path: Path) -> None:
    _seed(tmp_path)
    names = sorted(Path(p).name for p in scandir_find(tmp_path, "*.log"))
    assert names == ["a.log", "b.log", "d.log", "f.log"]


def test_scandir_find_is_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "X.LOG").write_text("x", encoding="utf-8")
    names = [Path(p).name for p in scandir_find(tmp_path, "*.log")]
    assert names == ["X.LOG"]


def test_scandir_find_respects_limit(tmp_path: Path) -> None:
    _seed(tmp_path)
    results = list(scandir_find(tmp_path, "*.log", limit=2))
    assert len(results) == 2


def test_scandir_find_streams_lazily(tmp_path: Path) -> None:
    _seed(tmp_path)
    iterator = scandir_find(tmp_path, "*.log")
    first = next(iterator)
    assert first.endswith(".log")


def test_scandir_find_includes_dirs_when_requested(tmp_path: Path) -> None:
    _seed(tmp_path)
    names = {Path(p).name for p in scandir_find(tmp_path, "*", files_only=False)}
    assert "nested" in names
    assert "deep" in names
    assert "a.log" in names


def test_scandir_find_returns_absolute_paths(tmp_path: Path) -> None:
    _seed(tmp_path)
    for path in scandir_find(tmp_path, "*.log"):
        assert Path(path).is_absolute()


def test_scandir_find_handles_missing_root(tmp_path: Path) -> None:
    assert list(scandir_find(tmp_path / "does-not-exist")) == []


def test_fast_find_falls_back_to_scandir_when_index_disabled(tmp_path: Path) -> None:
    _seed(tmp_path)
    names = sorted(Path(p).name for p in fast_find(tmp_path, "*.log", use_index=False))
    assert names == ["a.log", "b.log", "d.log", "f.log"]


def test_fast_find_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert fast_find(tmp_path / "missing") == []


def test_fast_find_respects_limit(tmp_path: Path) -> None:
    _seed(tmp_path)
    results = fast_find(tmp_path, "*.log", limit=1, use_index=False)
    assert len(results) == 1


def test_fast_find_files_only_excludes_dirs(tmp_path: Path) -> None:
    _seed(tmp_path)
    results = fast_find(tmp_path, "*", use_index=False, files_only=True)
    assert all(Path(p).is_file() for p in results)


def test_has_os_index_returns_str_or_none() -> None:
    result = has_os_index()
    assert result is None or isinstance(result, str)


def test_fast_find_skips_unreadable_dirs(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path)
    original_scandir = ff.os.scandir

    def guarded(path: str):
        if path.endswith("deep"):
            raise PermissionError("denied")
        return original_scandir(path)

    monkeypatch.setattr(ff.os, "scandir", guarded)
    names = sorted(Path(p).name for p in scandir_find(tmp_path, "*.log"))
    assert "f.log" not in names
    assert "a.log" in names


def test_fast_find_registered_in_default_registry() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    assert "FA_fast_find" in registry


def test_fast_find_falls_back_when_indexer_raises(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path)
    monkeypatch.setattr(ff, "has_os_index", lambda: "mdfind")

    def boom(*_args, **_kwargs):
        raise OSError("indexer not allowed")

    monkeypatch.setattr(ff, "_run_indexer", boom)
    results = fast_find(tmp_path, "*.log")
    assert sorted(Path(p).name for p in results) == ["a.log", "b.log", "d.log", "f.log"]


def test_fast_find_uses_indexer_when_available(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path)
    monkeypatch.setattr(ff, "has_os_index", lambda: "locate")
    canned = [str(tmp_path / "a.log"), str(tmp_path / "nested" / "d.log")]
    monkeypatch.setattr(ff, "_run_indexer", lambda *_a, **_kw: canned)
    results = fast_find(tmp_path, "*.log")
    assert results == canned


@pytest.mark.parametrize("indexer", ["mdfind", "plocate", "locate", "es"])
def test_run_indexer_dispatches(tmp_path: Path, monkeypatch, indexer: str) -> None:
    captured: dict[str, object] = {}

    def fake_capture(argv: list[str]) -> list[str]:
        captured["argv"] = argv
        return [str(tmp_path / "a.log")]

    (tmp_path / "a.log").write_text("a", encoding="utf-8")
    monkeypatch.setattr(ff, "_capture", fake_capture)
    result = ff._run_indexer(indexer, tmp_path, "*.log", True, None)
    assert result == [str(tmp_path / "a.log")]
    assert captured["argv"][0] == indexer
