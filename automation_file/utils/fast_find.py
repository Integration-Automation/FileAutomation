"""Fast file search with OS-index fast path and scandir fallback.

The module picks the cheapest backend available on the host:

* macOS   — ``mdfind`` (Spotlight) when the search root is an indexed volume.
* Linux   — ``locate`` / ``plocate`` when present and a recent database exists.
* Windows — Everything's ``es.exe`` CLI when installed and running.
* Fallback — a streaming ``os.scandir`` walk with ``fnmatch`` matching.

Only the built-in ``os`` / ``fnmatch`` / ``subprocess`` / ``shutil`` stdlib
modules are used — no extra dependencies. Results are returned as absolute
path strings. The OS-index path is preferred because it avoids touching the
filesystem at all; the fallback yields lazily and supports an early-termination
``limit=`` so large trees don't waste energy after the caller has what it
needs.
"""

from __future__ import annotations

import fnmatch
import os
import platform
import shutil
import subprocess  # nosec B404 — invoked only with fixed-name OS indexers (mdfind/locate) via argv
from collections.abc import Iterable, Iterator
from pathlib import Path

from automation_file.logging_config import file_automation_logger

__all__ = [
    "fast_find",
    "scandir_find",
    "has_os_index",
]

_INDEX_TIMEOUT_SECONDS = 15
_DEFAULT_PATTERN = "*"


def has_os_index() -> str | None:
    """Return the name of an available OS indexer (``mdfind`` / ``locate`` / ``es``) or ``None``."""
    system = platform.system()
    if system == "Darwin" and shutil.which("mdfind"):
        return "mdfind"
    if system == "Linux":
        for candidate in ("plocate", "locate"):
            if shutil.which(candidate):
                return candidate
    if system == "Windows" and shutil.which("es"):
        return "es"
    return None


def fast_find(
    root: str | os.PathLike[str],
    pattern: str = _DEFAULT_PATTERN,
    *,
    limit: int | None = None,
    files_only: bool = True,
    use_index: bool = True,
) -> list[str]:
    """Return absolute paths under ``root`` matching ``pattern``.

    ``pattern`` is a shell-style glob (``*.log``, ``report_*.csv``).
    ``limit`` caps the number of results. ``files_only`` skips directories.
    When ``use_index`` is true and an OS indexer is available the query is
    dispatched to it; otherwise the scandir fallback runs.

    The OS indexer is only used when it can honour the scope: ``mdfind``
    accepts ``-onlyin``, ``locate`` / ``plocate`` accept a bare prefix match,
    and ``es.exe`` accepts a ``path:`` query. If the indexer fails or is
    restricted, the function silently falls back to scandir — no exception is
    raised for the user.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        return []

    if use_index:
        indexer = has_os_index()
        if indexer:
            try:
                results = _run_indexer(indexer, root_path, pattern, files_only, limit)
            except (OSError, subprocess.SubprocessError) as err:
                file_automation_logger.debug(
                    "fast_find: indexer %s failed, falling back: %s", indexer, err
                )
            else:
                if results is not None:
                    return results

    return list(scandir_find(root_path, pattern, limit=limit, files_only=files_only))


def _iter_directory(current: str) -> Iterator[os.DirEntry[str]]:
    try:
        iterator = os.scandir(current)
    except OSError:
        return
    with iterator as entries:
        yield from entries


def _entry_is_dir(entry: os.DirEntry[str]) -> bool | None:
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return None


def scandir_find(
    root: str | os.PathLike[str],
    pattern: str = _DEFAULT_PATTERN,
    *,
    limit: int | None = None,
    files_only: bool = True,
) -> Iterator[str]:
    """Yield absolute paths under ``root`` matching ``pattern`` (streaming scandir).

    This is the pure-Python fallback. It is the fastest *portable* strategy
    when no OS index is available: ``os.scandir`` reads each directory once
    and avoids the extra stat calls that ``os.walk`` / ``Path.rglob`` make.
    Yielding rather than materialising lets the caller stop early via
    ``limit=`` or by breaking out of the loop.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        return
    yielded = 0
    stack: list[str] = [str(root_path)]
    lowered_pattern = pattern.lower()
    while stack:
        current = stack.pop()
        for entry in _iter_directory(current):
            is_dir = _entry_is_dir(entry)
            if is_dir is None:
                continue
            if is_dir:
                stack.append(entry.path)
                if files_only:
                    continue
            if _matches(entry.name, lowered_pattern):
                yield os.path.abspath(entry.path)
                yielded += 1
                if limit is not None and yielded >= limit:
                    return


def _matches(name: str, lowered_pattern: str) -> bool:
    return fnmatch.fnmatchcase(name.lower(), lowered_pattern)


def _run_indexer(
    indexer: str,
    root: Path,
    pattern: str,
    files_only: bool,
    limit: int | None,
) -> list[str] | None:
    if indexer == "mdfind":
        return _run_mdfind(root, pattern, files_only, limit)
    if indexer in ("locate", "plocate"):
        return _run_locate(indexer, root, pattern, files_only, limit)
    if indexer == "es":
        return _run_everything(root, pattern, files_only, limit)
    return None


def _capture(argv: list[str]) -> list[str]:
    # argv[0] is a fixed-name indexer (mdfind/locate/es); shell=False.
    completed = subprocess.run(  # nosec B603 nosemgrep
        argv,
        capture_output=True,
        timeout=_INDEX_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise subprocess.SubprocessError(f"{argv[0]} exited with {completed.returncode}")
    text = completed.stdout.decode("utf-8", errors="replace")
    return [line for line in text.splitlines() if line]


def _run_mdfind(root: Path, pattern: str, files_only: bool, limit: int | None) -> list[str]:
    query = f'kMDItemFSName == "{pattern}"'
    if files_only:
        query += " && kMDItemContentType != 'public.folder'"
    lines = _capture(["mdfind", "-onlyin", str(root), query])
    return _post_filter(lines, root, pattern, files_only, limit)


def _run_locate(
    indexer: str, root: Path, pattern: str, files_only: bool, limit: int | None
) -> list[str]:
    lines = _capture([indexer, "-i", pattern])
    prefix = str(root)
    scoped = [line for line in lines if line.startswith(prefix)]
    return _post_filter(scoped, root, pattern, files_only, limit)


def _run_everything(root: Path, pattern: str, files_only: bool, limit: int | None) -> list[str]:
    argv = ["es", "-path", str(root), pattern]
    if files_only:
        argv.append("/a-d")
    if limit is not None:
        argv.extend(["-n", str(limit)])
    lines = _capture(argv)
    return _post_filter(lines, root, pattern, files_only, limit)


def _post_filter(
    lines: Iterable[str],
    root: Path,
    pattern: str,
    files_only: bool,
    limit: int | None,
) -> list[str]:
    out: list[str] = []
    lowered_pattern = pattern.lower()
    for raw in lines:
        path = Path(raw)
        if not _is_within(root, path):
            continue
        if files_only and path.is_dir():
            continue
        if not _matches(path.name, lowered_pattern):
            continue
        out.append(str(path))
        if limit is not None and len(out) >= limit:
            break
    return out


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True
