"""Directory trees across backends: copy one, or mirror one into another.

Both functions list the source once, then work file by file through
``File.copy_to``, so the two sides may be any two backends. A file that fails is
recorded in ``TreeResult.errors`` and the others still run, like ``sync_dir``.

``sync_tree`` copies a file when the target lacks it, when the sizes differ, or
when the source is newer; ``checksum=True`` compares SHA-256 digests instead of
times, which costs a read of both sides. ``delete=True`` also removes what the
source does not have. ``dry_run=True`` reports what would happen and changes
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from automation_file.exceptions import StorageException, StorageNotFoundException
from automation_file.logging_config import file_automation_logger
from automation_file.storage.storage import Storage
from automation_file.storage.types import FileInfo


@dataclass
class TreeResult:
    """What a tree copy or sync did, as paths relative to the two roots."""

    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        """True when no file failed."""
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "copied": list(self.copied),
            "skipped": list(self.skipped),
            "deleted": list(self.deleted),
            "errors": dict(self.errors),
            "dry_run": self.dry_run,
        }


def _entries(storage: Storage, *, missing_ok: bool) -> tuple[dict[str, FileInfo], list[str]]:
    """Return the files (by relative path) and the directories below ``storage``."""
    try:
        listing = storage.list_dir(recursive=True)
    except StorageNotFoundException:
        if missing_ok:
            return {}, []
        raise
    files = {info.path: info for info in listing if not info.is_dir}
    return files, [info.path for info in listing if info.is_dir]


def _checked_roots(source: Storage, target: Storage) -> None:
    if source.uri == target.uri:
        raise StorageException(f"{source} is both the source and the target")


def _failure(error: StorageException) -> str:
    return f"{type(error).__name__}: {error}"


def _copy_file(source: Storage, target: Storage, path: str, result: TreeResult) -> None:
    if result.dry_run:
        result.copied.append(path)
        return
    try:
        source.file(path).copy_to(target.file(path))
    except StorageException as error:
        result.errors[path] = _failure(error)
    else:
        result.copied.append(path)


def _make_directories(target: Storage, directories: list[str], result: TreeResult) -> None:
    if result.dry_run:
        return
    for directory in directories:
        try:
            target.mkdir(directory)
        except StorageException as error:
            result.errors[directory] = _failure(error)


def _newer(ours: FileInfo, theirs: FileInfo) -> bool:
    if ours.modified_at is None or theirs.modified_at is None:
        return False
    return ours.modified_at > theirs.modified_at


def _sync_file(
    source: Storage, target: Storage, pair: tuple[FileInfo, FileInfo | None], checksum: bool
) -> bool:
    """Say whether the target lacks the source file or holds another version of it."""
    ours, theirs = pair
    if theirs is None or ours.size != theirs.size:
        return True
    if checksum:
        return not source.checksum(ours.path).matches(target.checksum(ours.path))
    return _newer(ours, theirs)


def _delete_extras(
    target: Storage, extra_files: list[str], extra_directories: list[str], result: TreeResult
) -> None:
    # Deepest directories first, after the files inside them are gone.
    ordered = [*extra_files, *sorted(extra_directories, key=lambda path: -path.count("/"))]
    for path in ordered:
        if result.dry_run:
            result.deleted.append(path)
            continue
        try:
            target.delete(path, missing_ok=True)
        except StorageException as error:
            result.errors[path] = _failure(error)
        else:
            result.deleted.append(path)


def _log(action: str, source: Storage, target: Storage, result: TreeResult) -> None:
    file_automation_logger.info(
        "%s %s -> %s: copied=%d skipped=%d deleted=%d errors=%d (dry_run=%s)",
        action,
        source,
        target,
        len(result.copied),
        len(result.skipped),
        len(result.deleted),
        len(result.errors),
        result.dry_run,
    )


def copy_tree(source: Storage, target: Storage, *, overwrite: bool = True) -> TreeResult:
    """Copy every file below ``source`` to the same relative path below ``target``.

    With ``overwrite=False`` a file the target already has is skipped. Empty
    directories are created where the target backend has real directories.
    """
    _checked_roots(source, target)
    files, directories = _entries(source, missing_ok=False)
    existing, _ = _entries(target, missing_ok=True)
    result = TreeResult()
    _make_directories(target, directories, result)
    for path in sorted(files):
        if not overwrite and path in existing:
            result.skipped.append(path)
        else:
            _copy_file(source, target, path, result)
    _log("copy_tree", source, target, result)
    return result


def sync_tree(
    source: Storage,
    target: Storage,
    *,
    delete: bool = False,
    checksum: bool = False,
    dry_run: bool = False,
) -> TreeResult:
    """Make ``target`` hold what ``source`` holds, copying only what changed."""
    _checked_roots(source, target)
    files, directories = _entries(source, missing_ok=False)
    existing, existing_directories = _entries(target, missing_ok=True)
    result = TreeResult(dry_run=dry_run)
    _make_directories(target, directories, result)
    for path in sorted(files):
        try:
            changed = _sync_file(source, target, (files[path], existing.get(path)), checksum)
        except StorageException as error:
            result.errors[path] = _failure(error)
            continue
        if changed:
            _copy_file(source, target, path, result)
        else:
            result.skipped.append(path)
    if delete:
        extra_files = sorted(set(existing) - set(files))
        extra_directories = sorted(set(existing_directories) - set(directories))
        _delete_extras(target, extra_files, extra_directories, result)
    _log("sync_tree", source, target, result)
    return result
