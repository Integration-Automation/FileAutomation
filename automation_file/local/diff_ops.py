"""Directory and file diff / patch helpers.

:func:`diff_dirs` walks two trees and reports files that were added, removed,
or changed by content hash. :func:`apply_dir_diff` replays that diff against a
target tree, copying or deleting as needed. Text-file differences are rendered
as unified diffs with :func:`diff_text_files`.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from automation_file.exceptions import DiffException
from automation_file.local.safe_paths import safe_join

_HASH = "sha256"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class DirDiff:
    """Summary of differences between two directory trees.

    Paths are POSIX-style strings relative to the diff root.
    """

    added: tuple[str, ...] = field(default_factory=tuple)
    removed: tuple[str, ...] = field(default_factory=tuple)
    changed: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff_dirs(left: str | os.PathLike[str], right: str | os.PathLike[str]) -> DirDiff:
    """Compute the content diff going from ``left`` to ``right``."""
    left_path = Path(left)
    right_path = Path(right)
    if not left_path.is_dir():
        raise DiffException(f"left is not a directory: {left_path}")
    if not right_path.is_dir():
        raise DiffException(f"right is not a directory: {right_path}")
    left_files = _relative_files(left_path)
    right_files = _relative_files(right_path)
    added = tuple(sorted(right_files - left_files))
    removed = tuple(sorted(left_files - right_files))
    changed = tuple(
        sorted(
            rel
            for rel in left_files & right_files
            if _hash_file(left_path / rel) != _hash_file(right_path / rel)
        )
    )
    return DirDiff(added=added, removed=removed, changed=changed)


def apply_dir_diff(
    diff: DirDiff,
    target: str | os.PathLike[str],
    source: str | os.PathLike[str],
) -> None:
    """Apply ``diff`` (generated relative to ``source``) onto ``target``.

    Added and changed files are copied from ``source``; removed files are
    deleted from ``target``. All target-side paths are constrained with
    :func:`safe_join` to prevent escape via symlink or ``..`` segments.
    """
    source_path = Path(source)
    target_path = Path(target)
    if not source_path.is_dir():
        raise DiffException(f"source is not a directory: {source_path}")
    target_path.mkdir(parents=True, exist_ok=True)
    for rel in (*diff.added, *diff.changed):
        dest = safe_join(target_path, rel)
        src = source_path / rel
        if not src.is_file():
            raise DiffException(f"patch source missing: {src}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    for rel in diff.removed:
        dest = safe_join(target_path, rel)
        if dest.is_file():
            dest.unlink()


def diff_text_files(
    left: str | os.PathLike[str],
    right: str | os.PathLike[str],
    *,
    context: int = 3,
) -> str:
    """Return a unified diff between two text files."""
    left_path = Path(left)
    right_path = Path(right)
    try:
        left_lines = left_path.read_text(encoding="utf-8").splitlines(keepends=True)
        right_lines = right_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as error:
        raise DiffException(f"cannot read diff inputs: {error}") from error
    diff_lines = difflib.unified_diff(
        left_lines,
        right_lines,
        fromfile=str(left_path),
        tofile=str(right_path),
        n=context,
    )
    return "".join(diff_lines)


def _relative_files(root: Path) -> set[str]:
    collected: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            rel = Path(dirpath, name).relative_to(root)
            collected.add(rel.as_posix())
    return collected


def _hash_file(path: Path) -> str:
    hasher = hashlib.new(_HASH)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def iter_dir_diff(diff: DirDiff) -> Iterable[tuple[str, str]]:
    """Yield ``(kind, rel_path)`` for every change in ``diff``."""
    for rel in diff.added:
        yield "added", rel
    for rel in diff.removed:
        yield "removed", rel
    for rel in diff.changed:
        yield "changed", rel
