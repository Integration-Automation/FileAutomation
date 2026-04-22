"""Rsync-style incremental directory synchronisation.

``sync_dir(src, dst)`` mirrors ``src`` into ``dst`` by copying only files
that are new or changed. Change detection defaults to ``(size, mtime)``,
which is cheap and correct for the common case; pass ``compare="checksum"``
to verify contents via SHA-256 when mtime is unreliable (network shares,
backups restored with reset timestamps, etc.).

Returns a summary dict the caller can log or feed to a notifier::

    {
        "copied": ["a.txt", "nested/b.txt"],
        "skipped": ["c.txt"],
        "deleted": ["old/d.txt"],
        "errors": [("e.txt", "PermissionError(...)")],
    }

By default, extra entries in ``dst`` are left alone — pass ``delete=True``
to prune them. Symlinks in the source tree are not followed; they are
re-created as symlinks at the destination so tree-crossing links can't
blow up the sync into a different subtree.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path
from typing import Any

from automation_file.core.checksum import file_checksum
from automation_file.exceptions import DirNotExistsException, FileAutomationException
from automation_file.logging_config import file_automation_logger

_COMPARE_MODES = frozenset({"size_mtime", "checksum"})
_MTIME_TOLERANCE_SECONDS = 2.0


class SyncException(FileAutomationException):
    """Raised for invalid sync arguments (bad compare mode, missing source)."""


def sync_dir(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    *,
    compare: str = "size_mtime",
    delete: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Mirror ``src`` into ``dst`` incrementally. See module docstring."""
    if compare not in _COMPARE_MODES:
        raise SyncException(f"compare must be one of {sorted(_COMPARE_MODES)}, got {compare!r}")
    source = Path(src)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    destination = Path(dst)
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "copied": [],
        "skipped": [],
        "deleted": [],
        "errors": [],
        "dry_run": dry_run,
    }

    src_entries = _walk_relative(source)
    for rel in src_entries:
        _process_source_entry(source, destination, rel, compare, dry_run=dry_run, summary=summary)

    if delete:
        _delete_extras(destination, src_entries, dry_run, summary)

    file_automation_logger.info(
        "sync_dir %s -> %s: copied=%d skipped=%d deleted=%d errors=%d (dry_run=%s)",
        source,
        destination,
        len(summary["copied"]),
        len(summary["skipped"]),
        len(summary["deleted"]),
        len(summary["errors"]),
        dry_run,
    )
    return summary


def _walk_relative(root: Path) -> list[Path]:
    """Return every entry under ``root`` as a relative ``Path`` (files + symlinks)."""
    entries: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        base = Path(dirpath)
        for name in sorted(filenames):
            entries.append((base / name).relative_to(root))
    return entries


def _process_source_entry(
    source: Path,
    destination: Path,
    rel: Path,
    compare: str,
    *,
    dry_run: bool,
    summary: dict[str, Any],
) -> None:
    src_path = source / rel
    dst_path = destination / rel
    try:
        if _needs_copy(src_path, dst_path, compare):
            if not dry_run:
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                _copy_one(src_path, dst_path)
            summary["copied"].append(str(rel).replace("\\", "/"))
        else:
            summary["skipped"].append(str(rel).replace("\\", "/"))
    except (OSError, FileAutomationException) as err:
        summary["errors"].append((str(rel).replace("\\", "/"), repr(err)))
        file_automation_logger.warning("sync_dir: %s failed: %r", rel, err)


def _needs_copy(src: Path, dst: Path, compare: str) -> bool:
    if not (dst.exists() or dst.is_symlink()):
        return True
    src_is_link = src.is_symlink()
    dst_is_link = dst.is_symlink()
    if src_is_link != dst_is_link:
        return True
    if src_is_link:
        return os.readlink(src) != os.readlink(dst)
    src_stat = src.stat()
    dst_stat = dst.stat()
    if src_stat.st_size != dst_stat.st_size:
        return True
    if compare == "checksum":
        return file_checksum(src) != file_checksum(dst)
    return abs(src_stat.st_mtime - dst_stat.st_mtime) > _MTIME_TOLERANCE_SECONDS


def _copy_one(src: Path, dst: Path) -> None:
    if src.is_symlink():
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        os.symlink(os.readlink(src), dst)
        return
    shutil.copy2(src, dst)


def _delete_extras(
    destination: Path,
    src_entries: list[Path],
    dry_run: bool,
    summary: dict[str, Any],
) -> None:
    expected = {str(rel).replace("\\", "/") for rel in src_entries}
    if not destination.exists():
        return
    for dirpath, _dirnames, filenames in os.walk(destination, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            rel = (base / name).relative_to(destination)
            rel_str = str(rel).replace("\\", "/")
            if rel_str in expected:
                continue
            target = base / name
            try:
                if not dry_run:
                    target.unlink()
                summary["deleted"].append(rel_str)
            except OSError as err:
                summary["errors"].append((rel_str, repr(err)))
                file_automation_logger.warning("sync_dir: delete %s failed: %r", rel, err)
    if not dry_run:
        _prune_empty_dirs(destination)


def _prune_empty_dirs(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        if dirpath == str(root):
            continue
        if not dirnames and not filenames:
            with contextlib.suppress(OSError):
                Path(dirpath).rmdir()
