"""Shared directory-walker for cloud/SFTP ``*_upload_dir`` operations.

Every backend implements the same pattern: validate that ``dir_path``
exists, normalise the remote prefix, iterate ``Path.rglob('*')``, skip
non-files, compute a POSIX-relative remote identifier, call
``upload_file`` for each, and collect the successful remote keys. This
module factors that walk out so each backend only supplies the two
parts that actually differ — how to assemble the remote identifier and
which per-file upload function to call.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from automation_file.exceptions import DirNotExistsException


class UploadDirResult(NamedTuple):
    """Return value of :func:`walk_and_upload`.

    Carries the resolved ``source`` ``Path``, the normalised prefix
    (trailing ``/`` stripped), and the list of remote identifiers that
    uploaded successfully — so each backend can feed its own log line
    without re-doing the Path / prefix work.
    """

    source: Path
    prefix: str
    uploaded: list[str]


def walk_and_upload(
    dir_path: str,
    prefix: str,
    make_remote: Callable[[str, str], str],
    upload_one: Callable[[Path, str], bool],
) -> UploadDirResult:
    """Walk ``dir_path`` and upload every file via ``upload_one``.

    Raises :class:`DirNotExistsException` if ``dir_path`` is not a
    directory. ``prefix`` is ``rstrip("/")``-ed before being passed to
    ``make_remote(normalised_prefix, rel_posix)``, and ``upload_one``
    receives ``(local_path, remote_key)`` returning True on success.
    Per-file failures are not raised — they are simply omitted from
    :attr:`UploadDirResult.uploaded`, matching the existing backend
    contract.
    """
    source = Path(dir_path)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    normalised = prefix.rstrip("/")
    uploaded: list[str] = []
    for entry in source.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(source).as_posix()
        remote = make_remote(normalised, rel)
        if upload_one(entry, remote):
            uploaded.append(remote)
    return UploadDirResult(source=source, prefix=normalised, uploaded=uploaded)
