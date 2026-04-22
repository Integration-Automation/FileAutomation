"""Recoverable-delete / trash helpers.

Moves files or directories into a caller-supplied trash directory instead of
permanent removal. Each trash entry keeps a JSON sidecar recording the
original path, so :func:`restore_from_trash` can return the content to its
source location.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from automation_file.exceptions import VersioningException

_META_SUFFIX = ".trashmeta.json"


@dataclass(frozen=True)
class TrashEntry:
    """An item present in a trash directory."""

    trash_id: str
    original: Path
    trashed_at: float
    path: Path
    is_dir: bool


def send_to_trash(
    path: str | os.PathLike[str],
    trash_dir: str | os.PathLike[str],
) -> TrashEntry:
    """Move ``path`` into ``trash_dir``; returns the new :class:`TrashEntry`."""
    source = Path(path)
    if not source.exists():
        raise VersioningException(f"source does not exist: {source}")
    bin_dir = Path(trash_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    trash_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    target = bin_dir / f"{trash_id}__{source.name}"
    original_absolute = str(source.resolve())
    shutil.move(str(source), target)
    trashed_at = time.time()
    is_dir = target.is_dir()
    meta: dict[str, object] = {
        "trash_id": trash_id,
        "original": original_absolute,
        "trashed_at": trashed_at,
        "is_dir": is_dir,
    }
    meta_path = bin_dir / f"{trash_id}{_META_SUFFIX}"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return TrashEntry(
        trash_id=trash_id,
        original=Path(original_absolute),
        trashed_at=trashed_at,
        path=target,
        is_dir=is_dir,
    )


def list_trash(trash_dir: str | os.PathLike[str]) -> list[TrashEntry]:
    """Return every item currently present in ``trash_dir``."""
    bin_dir = Path(trash_dir)
    if not bin_dir.is_dir():
        return []
    entries: list[TrashEntry] = []
    for meta in bin_dir.glob(f"*{_META_SUFFIX}"):
        entry = _read_meta(meta)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda item: item.trashed_at)
    return entries


def restore_from_trash(
    trash_id: str,
    trash_dir: str | os.PathLike[str],
    *,
    destination: str | os.PathLike[str] | None = None,
) -> Path:
    """Move a trashed item back to its original location (or ``destination``)."""
    bin_dir = Path(trash_dir)
    meta_path = bin_dir / f"{trash_id}{_META_SUFFIX}"
    entry = _read_meta(meta_path) if meta_path.is_file() else None
    if entry is None:
        raise VersioningException(f"no trash entry with id {trash_id!r}")
    target = Path(destination) if destination is not None else entry.original
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise VersioningException(f"restore target already exists: {target}")
    shutil.move(str(entry.path), target)
    meta_path.unlink(missing_ok=True)
    return target


def empty_trash(trash_dir: str | os.PathLike[str]) -> int:
    """Permanently delete everything in ``trash_dir``. Returns items removed."""
    bin_dir = Path(trash_dir)
    if not bin_dir.is_dir():
        return 0
    removed = 0
    for child in bin_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def _read_meta(meta_path: Path) -> TrashEntry | None:
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    trash_id = payload.get("trash_id")
    original = payload.get("original")
    if not trash_id or not original:
        return None
    bin_dir = meta_path.parent
    matches = [
        p
        for p in bin_dir.iterdir()
        if p.name.startswith(f"{trash_id}__") and not p.name.endswith(_META_SUFFIX)
    ]
    if not matches:
        return None
    return TrashEntry(
        trash_id=str(trash_id),
        original=Path(str(original)),
        trashed_at=float(payload.get("trashed_at", 0.0)),
        path=matches[0],
        is_dir=bool(payload.get("is_dir", matches[0].is_dir())),
    )
