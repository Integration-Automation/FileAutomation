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
import re
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


def apply_text_patch(target: str | os.PathLike[str], patch: str) -> bool:
    """Apply a unified-diff ``patch`` to ``target`` in place; return True on success.

    The patch must have been produced against the current contents of
    ``target`` (for example by :func:`diff_text_files`). Hunk headers are
    verified against the live file before any write; if a hunk's context
    lines don't match, no change is applied and :class:`DiffException` is
    raised so the caller sees the mismatch instead of a corrupt file.

    ``target`` is taken at face value — the caller is the trust boundary
    for this path, exactly like :func:`pathlib.Path.write_text` or the
    surrounding :func:`diff_text_files` helper. Upstream callers that
    accept a user-controlled root should run the path through
    :func:`automation_file.local.safe_paths.safe_join` themselves.
    """
    target_path = Path(target)
    try:
        original = target_path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as error:
        raise DiffException(f"cannot read patch target: {error}") from error
    patched = _apply_unified_patch(original, patch)
    target_path.write_text("".join(patched), encoding="utf-8")  # NOSONAR pythonsecurity:S2083
    return True


def _apply_unified_patch(lines: list[str], patch: str) -> list[str]:
    result: list[str] = []
    cursor = 0
    for hunk in _iter_hunks(patch):
        cursor = _copy_up_to(lines, cursor, hunk.start, result)
        cursor = _apply_hunk_ops(lines, cursor, hunk.ops, result)
    result.extend(lines[cursor:])
    return result


def _copy_up_to(lines: list[str], cursor: int, stop: int, result: list[str]) -> int:
    while cursor < stop:
        result.append(lines[cursor])
        cursor += 1
    return cursor


def _apply_hunk_ops(
    lines: list[str],
    cursor: int,
    ops: tuple[tuple[str, str], ...],
    result: list[str],
) -> int:
    for op, payload in ops:
        if op == "+":
            result.append(payload)
            continue
        # " " (context) and "-" (delete) both require a live-line match.
        _verify_live_line(lines, cursor, payload, context=op == " ")
        if op == " ":
            result.append(payload)
        cursor += 1
    return cursor


def _verify_live_line(lines: list[str], cursor: int, expected: str, *, context: bool) -> None:
    got = lines[cursor] if cursor < len(lines) else "<EOF>"
    if cursor >= len(lines) or lines[cursor] != expected:
        kind = "context" if context else "deletion"
        raise DiffException(
            f"patch {kind} mismatch at line {cursor + 1}: expected {expected!r}, got {got!r}"
        )


@dataclass(frozen=True)
class _Hunk:
    start: int
    ops: tuple[tuple[str, str], ...]


def _iter_hunks(patch: str) -> Iterable[_Hunk]:
    state = _HunkParseState()
    for raw_line in patch.splitlines(keepends=True):
        pending = _consume_patch_line(state, raw_line)
        if pending is not None:
            yield pending
    if state.in_hunk and state.buffer:
        yield _Hunk(start=state.start, ops=tuple(state.buffer))


@dataclass
class _HunkParseState:
    buffer: list[tuple[str, str]] = field(default_factory=list)
    start: int = 0
    in_hunk: bool = False


def _consume_patch_line(state: _HunkParseState, raw_line: str) -> _Hunk | None:
    if raw_line.startswith("@@"):
        pending = (
            _Hunk(start=state.start, ops=tuple(state.buffer))
            if state.in_hunk and state.buffer
            else None
        )
        state.start = _parse_hunk_header(raw_line)
        state.buffer = []
        state.in_hunk = True
        return pending
    if raw_line.startswith(("---", "+++")) or not state.in_hunk or not raw_line:
        return None
    prefix, payload = raw_line[0], raw_line[1:]
    if prefix in {" ", "+", "-"}:
        state.buffer.append((prefix, payload))
    return None


_HUNK_HEADER = re.compile(r"^@@\s+-(\d+)(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@")


def _parse_hunk_header(line: str) -> int:
    match = _HUNK_HEADER.match(line)
    if not match:
        raise DiffException(f"malformed hunk header: {line.rstrip()!r}")
    # Unified-diff line numbers are 1-based; convert to 0-based index.
    return max(int(match.group(1)) - 1, 0)


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


def diff_dirs_summary(
    left: str | os.PathLike[str],
    right: str | os.PathLike[str],
) -> dict[str, list[str]]:
    """JSON-friendly wrapper around :func:`diff_dirs` — returns plain lists."""
    diff = diff_dirs(left, right)
    return {
        "added": list(diff.added),
        "removed": list(diff.removed),
        "changed": list(diff.changed),
    }
