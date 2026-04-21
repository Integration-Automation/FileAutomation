from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from automation_file import RotateException, build_default_registry, rotate_backups


def _make_file(path: Path, days_ago: int) -> None:
    path.write_text("data", encoding="utf-8")
    when = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).timestamp()
    os.utime(path, (when, when))


@pytest.fixture
def backup_dir(tmp_path: Path) -> Path:
    # Create 30 daily backups
    for day in range(30):
        _make_file(tmp_path / f"backup-{day:02d}.zip", days_ago=day)
    return tmp_path


def test_rotate_keeps_daily(backup_dir: Path) -> None:
    result = rotate_backups(
        str(backup_dir),
        "backup-*.zip",
        keep_daily=5,
        keep_weekly=0,
        keep_monthly=0,
    )
    assert len(result["kept"]) == 5


def test_rotate_dry_run_deletes_nothing(backup_dir: Path) -> None:
    result = rotate_backups(
        str(backup_dir),
        "backup-*.zip",
        keep_daily=3,
        keep_weekly=0,
        keep_monthly=0,
        dry_run=True,
    )
    assert result["dry_run"] is True
    # All 30 files still exist
    assert sum(1 for p in backup_dir.iterdir() if p.is_file()) == 30


def test_rotate_deletes_unkept(backup_dir: Path) -> None:
    rotate_backups(
        str(backup_dir),
        "backup-*.zip",
        keep_daily=5,
        keep_weekly=0,
        keep_monthly=0,
    )
    # Only 5 remain
    assert sum(1 for p in backup_dir.iterdir() if p.is_file()) == 5


def test_rotate_combines_buckets(backup_dir: Path) -> None:
    result = rotate_backups(
        str(backup_dir),
        "backup-*.zip",
        keep_daily=3,
        keep_weekly=2,
        keep_monthly=0,
    )
    # At least 3 daily slots are filled; weekly buckets may overlap the same newest files
    assert 3 <= len(result["kept"]) <= 5


def test_rotate_respects_pattern(tmp_path: Path) -> None:
    _make_file(tmp_path / "keep.log", 0)
    _make_file(tmp_path / "ignore.bin", 0)
    result = rotate_backups(
        str(tmp_path),
        "*.log",
        keep_daily=0,
        keep_weekly=0,
        keep_monthly=0,
        keep_yearly=0,
    )
    assert any(p.endswith("keep.log") for p in result["deleted"])
    assert (tmp_path / "ignore.bin").is_file()


def test_rotate_rejects_negative(backup_dir: Path) -> None:
    with pytest.raises(RotateException):
        rotate_backups(str(backup_dir), keep_daily=-1)


def test_rotate_rejects_non_directory(tmp_path: Path) -> None:
    with pytest.raises(RotateException):
        rotate_backups(str(tmp_path / "nope"))


def test_rotate_registered() -> None:
    registry = build_default_registry()
    assert "FA_rotate_backups" in registry


def test_rotate_monthly_bucket(tmp_path: Path) -> None:
    # 60 daily files across multiple months
    for day in range(60):
        _make_file(tmp_path / f"m-{day:02d}.zip", days_ago=day)
    result = rotate_backups(
        str(tmp_path),
        "m-*.zip",
        keep_daily=0,
        keep_weekly=0,
        keep_monthly=2,
    )
    assert len(result["kept"]) == 2


def test_rotate_skips_subdirectories(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inside.zip").write_text("x", encoding="utf-8")
    _make_file(tmp_path / "top.zip", 0)
    rotate_backups(str(tmp_path), "*.zip", keep_daily=0, keep_weekly=0, keep_monthly=0)
    # Subdir remains untouched
    assert (tmp_path / "sub" / "inside.zip").is_file()
