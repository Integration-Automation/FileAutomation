"""Shared directory-walker for cloud/SFTP ``*_upload_dir`` operations.

Every backend implements the same pattern: iterate ``Path.rglob('*')``,
skip non-files, compute a POSIX-relative remote identifier, call
``upload_file`` for each, and collect the successful remote keys. This
module factors that walk out so each backend only supplies the two
parts that actually differ — how to assemble the remote identifier
and which per-file upload function to call.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def walk_and_upload(
    source: Path,
    make_remote: Callable[[str], str],
    upload_one: Callable[[Path, str], bool],
) -> list[str]:
    """Return the list of remote identifiers successfully uploaded from ``source``.

    ``make_remote`` is called with the POSIX relative path of each file
    (no leading slash) and must return the backend-specific remote key.
    ``upload_one`` receives ``(local_path, remote_key)`` and returns True
    on success. Per-file failures are not raised — they are simply
    omitted from the returned list, matching the existing backend
    contract.
    """
    uploaded: list[str] = []
    for entry in source.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(source).as_posix()
        remote = make_remote(rel)
        if upload_one(entry, remote):
            uploaded.append(remote)
    return uploaded
