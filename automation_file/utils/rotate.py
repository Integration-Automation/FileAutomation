"""Backup retention / rotation.

Group files in a directory by their age bucket (daily / weekly / monthly /
yearly) and keep the N newest per bucket. Everything that falls outside
every bucket is deleted.

Files are grouped by their mtime, not by filename — the caller just
controls *which* files are considered via a glob pattern. Perfect for the
output of ``FA_zip_dir`` / ``FA_write_manifest`` / ``FA_create_tar``.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

_Keyer = Callable[[float], str]


class RotateException(FileAutomationException):
    """Raised when rotate_backups receives invalid arguments."""


def rotate_backups(
    directory: str,
    pattern: str = "*",
    *,
    keep_daily: int = 7,
    keep_weekly: int = 4,
    keep_monthly: int = 12,
    keep_yearly: int = 0,
    dry_run: bool = False,
) -> dict[str, object]:
    """Keep newest N per bucket under ``directory``; delete the rest.

    Returns ``{"kept": [...], "deleted": [...], "dry_run": bool}``.

    Buckets are assigned by mtime:

    * daily   — one slot per calendar day
    * weekly  — one slot per ISO week
    * monthly — one slot per (year, month)
    * yearly  — one slot per year

    A file is kept if it is the *newest* file in any of the top-N slots of
    any enabled bucket. ``0`` disables a bucket. No file can appear in
    both ``kept`` and ``deleted``.
    """
    for name, value in (
        ("keep_daily", keep_daily),
        ("keep_weekly", keep_weekly),
        ("keep_monthly", keep_monthly),
        ("keep_yearly", keep_yearly),
    ):
        if value < 0:
            raise RotateException(f"{name} must be >= 0")

    root = Path(directory)
    if not root.is_dir():
        raise RotateException(f"not a directory: {directory}")

    candidates: list[tuple[Path, float]] = []
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        if not fnmatch.fnmatch(entry.name, pattern):
            continue
        candidates.append((entry, entry.stat().st_mtime))
    candidates.sort(key=lambda item: item[1], reverse=True)

    kept = _select_kept(
        candidates,
        keep_daily=keep_daily,
        keep_weekly=keep_weekly,
        keep_monthly=keep_monthly,
        keep_yearly=keep_yearly,
    )
    kept_paths = {path for path, _ in kept}
    deleted: list[str] = []
    for path, _mtime in candidates:
        if path in kept_paths:
            continue
        deleted.append(str(path))
        if dry_run:
            continue
        try:
            path.unlink()
        except OSError as err:
            file_automation_logger.error("rotate_backups: unlink %s failed: %r", path, err)

    file_automation_logger.info(
        "rotate_backups: kept=%d deleted=%d dry_run=%s",
        len(kept_paths),
        len(deleted),
        dry_run,
    )
    return {
        "kept": [str(path) for path in kept_paths],
        "deleted": deleted,
        "dry_run": dry_run,
    }


def _select_kept(
    candidates: list[tuple[Path, float]],
    *,
    keep_daily: int,
    keep_weekly: int,
    keep_monthly: int,
    keep_yearly: int,
) -> list[tuple[Path, float]]:
    buckets: list[tuple[int, _Keyer]] = [
        (keep_daily, _daily_key),
        (keep_weekly, _weekly_key),
        (keep_monthly, _monthly_key),
        (keep_yearly, _yearly_key),
    ]
    kept: dict[Path, float] = {}
    for keep, key in buckets:
        if keep <= 0:
            continue
        seen: dict[object, Path] = {}
        for path, mtime in candidates:
            slot = key(mtime)
            if slot in seen:
                continue
            seen[slot] = path
            if len(seen) >= keep:
                break
        for path in seen.values():
            kept[path] = path.stat().st_mtime
    return list(kept.items())


def _daily_key(mtime: float) -> str:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _weekly_key(mtime: float) -> str:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    year, week, _weekday = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _monthly_key(mtime: float) -> str:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m")


def _yearly_key(mtime: float) -> str:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y")
