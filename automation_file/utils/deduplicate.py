"""Find duplicate files with a three-stage size-then-hash pipeline.

Brute-force content hashing every file in a tree is wasteful: most files
have a unique size and can be ruled out instantly. This module runs three
cheap-to-expensive stages:

1. **Group by size** — one ``stat()`` per file; unique sizes are skipped.
2. **Partial hash** — hash the first ``sample_bytes`` of each size collision.
3. **Full hash** — only for paths whose partial hash matches another.

The result is a list of duplicate groups, where each group is a list of
absolute paths that share the same content.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

from automation_file.logging_config import file_automation_logger

__all__ = ["find_duplicates"]

_DEFAULT_SAMPLE_BYTES = 64 * 1024
_DEFAULT_ALGO = "sha256"


def find_duplicates(
    root: str | os.PathLike[str],
    *,
    min_size: int = 1,
    sample_bytes: int = _DEFAULT_SAMPLE_BYTES,
    algorithm: str = _DEFAULT_ALGO,
) -> list[list[str]]:
    """Return duplicate groups under ``root``.

    ``min_size`` skips zero-byte or tiny files (default 1 — so empty files
    are excluded). ``sample_bytes`` controls the partial-hash window; a
    larger sample catches more mismatches on stage two at the cost of more
    I/O. ``algorithm`` is any name :func:`hashlib.new` understands.

    Groups are returned sorted by size descending, then each group's paths
    are sorted for stable output.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        return []

    by_size = _group_by_size(root_path, min_size)
    by_partial = _refine(by_size, lambda p: _hash_head(p, sample_bytes, algorithm))
    by_full = _refine(by_partial, lambda p: _hash_full(p, algorithm))

    groups = [sorted(paths) for paths in by_full.values() if len(paths) > 1]
    groups.sort(key=lambda g: (-_safe_size(g[0]), g[0]))
    return groups


def _classify_entry(entry: os.DirEntry[str]) -> tuple[str, int | None]:
    """Return ``("dir", None)``, ``("file", size)``, or ``("skip", None)``."""
    try:
        if entry.is_dir(follow_symlinks=False):
            return "dir", None
        if not entry.is_file(follow_symlinks=False):
            return "skip", None
        return "file", entry.stat(follow_symlinks=False).st_size
    except OSError:
        return "skip", None


def _group_by_size(root: Path, min_size: int) -> dict[int, list[str]]:
    buckets: dict[int, list[str]] = defaultdict(list)
    stack: list[str] = [str(root)]
    while stack:
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError:
            continue
        with iterator as entries:
            for entry in entries:
                kind, size = _classify_entry(entry)
                if kind == "dir":
                    stack.append(entry.path)
                elif kind == "file" and size is not None and size >= min_size:
                    buckets[size].append(os.path.abspath(entry.path))
    return {size: paths for size, paths in buckets.items() if len(paths) > 1}


def _refine(groups: dict, hash_fn) -> dict[tuple, list[str]]:
    refined: dict[tuple, list[str]] = defaultdict(list)
    for key, paths in groups.items():
        if len(paths) < 2:
            continue
        for path in paths:
            digest = hash_fn(path)
            if digest is None:
                continue
            refined[(key, digest)].append(path)
    return {k: v for k, v in refined.items() if len(v) > 1}


def _hash_head(path: str, sample_bytes: int, algorithm: str) -> str | None:
    try:
        digest = hashlib.new(algorithm)
        with open(path, "rb") as handle:
            digest.update(handle.read(sample_bytes))
    except OSError as err:
        file_automation_logger.debug("dedup head-hash skipped %s: %r", path, err)
        return None
    return digest.hexdigest()


def _hash_full(path: str, algorithm: str) -> str | None:
    try:
        digest = hashlib.new(algorithm)
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as err:
        file_automation_logger.debug("dedup full-hash skipped %s: %r", path, err)
        return None
    return digest.hexdigest()


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
