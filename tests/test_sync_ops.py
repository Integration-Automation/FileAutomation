"""Tests for automation_file.local.sync_ops."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from automation_file.exceptions import DirNotExistsException
from automation_file.local.sync_ops import SyncException, sync_dir


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_sync_copies_new_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "one")
    _touch(src / "nested" / "b.txt", "two")

    result = sync_dir(src, dst)

    assert set(result["copied"]) == {"a.txt", "nested/b.txt"}
    assert result["skipped"] == []
    assert (dst / "a.txt").read_text(encoding="utf-8") == "one"
    assert (dst / "nested" / "b.txt").read_text(encoding="utf-8") == "two"


def test_sync_skips_unchanged_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "same")

    sync_dir(src, dst)
    # mtime tolerance means a second pass is a no-op.
    result = sync_dir(src, dst)
    assert result["copied"] == []
    assert result["skipped"] == ["a.txt"]


def test_sync_detects_size_change(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "short")
    sync_dir(src, dst)

    _touch(src / "a.txt", "much longer content than before")
    result = sync_dir(src, dst)

    assert result["copied"] == ["a.txt"]
    assert (dst / "a.txt").read_text(encoding="utf-8") == "much longer content than before"


def test_sync_detects_checksum_change_when_size_matches(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "aaa")
    sync_dir(src, dst)

    # Same size, different content, same mtime.
    (src / "a.txt").write_text("bbb", encoding="utf-8")
    stat = (dst / "a.txt").stat()
    os.utime(src / "a.txt", (stat.st_atime, stat.st_mtime))

    size_result = sync_dir(src, dst, compare="size_mtime")
    assert size_result["copied"] == []

    checksum_result = sync_dir(src, dst, compare="checksum")
    assert checksum_result["copied"] == ["a.txt"]
    assert (dst / "a.txt").read_text(encoding="utf-8") == "bbb"


def test_sync_rejects_unknown_compare_mode(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    with pytest.raises(SyncException, match="compare"):
        sync_dir(src, tmp_path / "dst", compare="bogus")


def test_sync_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(DirNotExistsException):
        sync_dir(tmp_path / "missing", tmp_path / "dst")


def test_sync_delete_removes_extras(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "keep")
    _touch(dst / "a.txt", "keep")
    _touch(dst / "old.txt", "remove")
    _touch(dst / "nested" / "stale.txt", "remove")

    result = sync_dir(src, dst, delete=True)

    assert set(result["deleted"]) == {"old.txt", "nested/stale.txt"}
    assert not (dst / "old.txt").exists()
    assert not (dst / "nested" / "stale.txt").exists()
    # Empty nested dir should be pruned.
    assert not (dst / "nested").exists()


def test_sync_delete_disabled_by_default(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "keep")
    _touch(dst / "old.txt", "remove")

    result = sync_dir(src, dst)
    assert result["deleted"] == []
    assert (dst / "old.txt").exists()


def test_sync_dry_run_makes_no_changes(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "one")
    _touch(dst / "extra.txt", "stale")

    result = sync_dir(src, dst, delete=True, dry_run=True)

    assert result["dry_run"] is True
    assert result["copied"] == ["a.txt"]
    assert result["deleted"] == ["extra.txt"]
    assert not (dst / "a.txt").exists()
    assert (dst / "extra.txt").exists()


def test_sync_mtime_tolerance_absorbs_small_drift(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "same")
    sync_dir(src, dst)

    # Nudge src's mtime by 1s — inside the 2s tolerance, should still skip.
    stat = (src / "a.txt").stat()
    os.utime(src / "a.txt", (stat.st_atime, stat.st_mtime + 1.0))
    result = sync_dir(src, dst)
    assert result["copied"] == []


def test_sync_fa_action_registered() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    assert "FA_sync_dir" in registry


def test_sync_error_recorded_per_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "good.txt", "ok")
    _touch(src / "bad.txt", "will-fail")

    import shutil as _shutil

    original_copy2 = _shutil.copy2

    def _fake_copy2(source: str, target: str, *args: object, **kwargs: object) -> str:
        if str(source).endswith("bad.txt"):
            raise OSError("simulated copy failure")
        return original_copy2(source, target, *args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr("automation_file.local.sync_ops.shutil.copy2", _fake_copy2)

    result = sync_dir(src, dst)
    # The good file should have made it; the bad one should be reported.
    assert "good.txt" in result["copied"]
    assert any(name == "bad.txt" for name, _err in result["errors"])


def test_sync_copies_into_existing_dst(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    dst.mkdir()
    _touch(dst / "keep.txt", "kept")
    _touch(src / "new.txt", "fresh")

    result = sync_dir(src, dst)

    assert (dst / "keep.txt").exists()
    assert (dst / "new.txt").read_text(encoding="utf-8") == "fresh"
    assert result["copied"] == ["new.txt"]


def test_sync_preserves_mtime(tmp_path: Path) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _touch(src / "a.txt", "t")
    past = time.time() - 10_000
    os.utime(src / "a.txt", (past, past))

    sync_dir(src, dst)

    assert abs((dst / "a.txt").stat().st_mtime - past) < 2.0
