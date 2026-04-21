"""Text content search (``FA_grep``).

A streaming grep over a directory tree. Uses ``os.scandir`` for traversal and
reads files line-by-line so multi-gigabyte logs never land in RAM all at
once. Pattern is a literal substring by default; pass ``regex=True`` to
treat it as a :mod:`re` pattern.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

_DEFAULT_MAX_MATCHES = 1000
_DEFAULT_MAX_LINE_LEN = 4096


class GrepException(FileAutomationException):
    """Raised when :func:`grep_files` receives invalid arguments."""


def grep_files(
    root: str,
    pattern: str,
    *,
    glob: str | None = None,
    regex: bool = False,
    ignore_case: bool = False,
    max_matches: int = _DEFAULT_MAX_MATCHES,
    max_line_len: int = _DEFAULT_MAX_LINE_LEN,
) -> list[dict[str, object]]:
    """Return matches of ``pattern`` under ``root``.

    Each hit is ``{"path": str, "line": int, "text": str}``. Traversal stops
    after ``max_matches``. Files with glob filter ``glob`` (matched against
    filename only) are considered; everything else is skipped. Decoding
    errors are ignored so binary files don't abort the walk.
    """
    if not pattern:
        raise GrepException("pattern must not be empty")
    if max_matches <= 0:
        raise GrepException("max_matches must be positive")
    root_path = Path(root)
    if not root_path.is_dir():
        raise GrepException(f"root is not a directory: {root}")

    matcher = _build_matcher(pattern, regex=regex, ignore_case=ignore_case)
    matches: list[dict[str, object]] = []
    for path in _walk(root_path, glob):
        try:
            _scan_file(path, matcher, matches, max_matches, max_line_len)
        except OSError as err:
            file_automation_logger.debug("grep: skip %s: %r", path, err)
            continue
        if len(matches) >= max_matches:
            break
    return matches


def _build_matcher(pattern: str, *, regex: bool, ignore_case: bool):
    flags = re.IGNORECASE if ignore_case else 0
    if regex:
        try:
            return re.compile(pattern, flags).search
        except re.error as err:
            raise GrepException(f"invalid regex: {err}") from err
    return re.compile(re.escape(pattern), flags).search


def _walk(root: Path, glob: str | None) -> Iterator[Path]:
    stack: list[str] = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError as err:
            file_automation_logger.debug("grep: scandir %s: %r", current, err)
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if glob and not fnmatch.fnmatch(entry.name, glob):
                continue
            yield Path(entry.path)


def _scan_file(
    path: Path,
    matcher,
    matches: list[dict[str, object]],
    max_matches: int,
    max_line_len: int,
) -> None:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for lineno, line in enumerate(handle, start=1):
            if matcher(line) is None:
                continue
            text = line.rstrip("\n")
            if len(text) > max_line_len:
                text = text[:max_line_len] + "…"
            matches.append({"path": str(path), "line": lineno, "text": text})
            if len(matches) >= max_matches:
                return


def iter_grep(
    root: str,
    pattern: str,
    *,
    glob: str | None = None,
    regex: bool = False,
    ignore_case: bool = False,
    max_line_len: int = _DEFAULT_MAX_LINE_LEN,
) -> Iterable[dict[str, object]]:
    """Streaming variant of :func:`grep_files` — yields hits without buffering."""
    if not pattern:
        raise GrepException("pattern must not be empty")
    root_path = Path(root)
    if not root_path.is_dir():
        raise GrepException(f"root is not a directory: {root}")
    matcher = _build_matcher(pattern, regex=regex, ignore_case=ignore_case)
    for path in _walk(root_path, glob):
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for lineno, line in enumerate(handle, start=1):
                    if matcher(line) is None:
                        continue
                    text = line.rstrip("\n")
                    if len(text) > max_line_len:
                        text = text[:max_line_len] + "…"
                    yield {"path": str(path), "line": lineno, "text": text}
        except OSError as err:
            file_automation_logger.debug("grep: skip %s: %r", path, err)
            continue
