"""Bridge helpers that expose `fsspec <https://filesystem-spec.readthedocs.io>`_
backends through the same verbs as our native clients.

fsspec already implements a large catalogue of filesystems — memory, local,
HTTP, GCS, ABFS, SSH, and more. Rather than reimplement each one, this
module gives callers a tiny surface (``upload`` / ``download`` / ``exists`` /
``list_dir`` / ``delete`` / ``mkdir``) over any ``fsspec`` URL. The ``fsspec``
import is lazy so installing the package is only required when the bridge
is actually used.

This is a **developer helper**, not a user-input surface. Callers are
responsible for validating URLs before handing them in — there is no SSRF
guard here because fsspec supports dozens of schemes, many of which bypass
the ``http(s)`` validator entirely (``ssh://``, ``s3://``, ``gcs://``…).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from automation_file.exceptions import FsspecException


@dataclass(frozen=True)
class FsspecEntry:
    """A single directory listing entry returned by :func:`fsspec_list_dir`."""

    name: str
    is_dir: bool
    size: int | None


def _import_fsspec() -> Any:
    try:
        import fsspec
    except ImportError as error:
        raise FsspecException(
            "fsspec import failed — install `fsspec` (and any backend extras) to use the bridge"
        ) from error
    return fsspec


def get_fs(url_or_protocol: str, **storage_options: Any) -> Any:
    """Return an :class:`fsspec.AbstractFileSystem` for ``url_or_protocol``.

    Pass either a bare protocol (``"s3"``, ``"memory"``) or a full URL —
    fsspec's ``url_to_fs`` will extract the protocol and pass ``storage_options``
    through to the backend constructor.
    """
    fsspec = _import_fsspec()
    try:
        if "://" in url_or_protocol:
            fs, _ = fsspec.core.url_to_fs(url_or_protocol, **storage_options)
            return fs
        return fsspec.filesystem(url_or_protocol, **storage_options)
    except Exception as error:
        raise FsspecException(
            f"could not resolve fsspec filesystem for {url_or_protocol!r}: {error}"
        ) from error


def _split(url: str) -> tuple[Any, str]:
    fsspec = _import_fsspec()
    try:
        fs, path = fsspec.core.url_to_fs(url)
    except Exception as error:
        raise FsspecException(f"invalid fsspec url {url!r}: {error}") from error
    return fs, path


def fsspec_exists(url: str) -> bool:
    """Return True if ``url`` exists on its backing fsspec filesystem."""
    fs, path = _split(url)
    try:
        return bool(fs.exists(path))
    except Exception as error:
        raise FsspecException(f"exists failed for {url!r}: {error}") from error


def fsspec_upload(local_path: str | os.PathLike[str], url: str) -> None:
    """Copy ``local_path`` onto the fsspec target at ``url``."""
    source = Path(local_path)
    if not source.is_file():
        raise FsspecException(f"local source is not a file: {source}")
    fs, path = _split(url)
    try:
        fs.put_file(str(source), path)
    except Exception as error:
        raise FsspecException(f"upload failed for {url!r}: {error}") from error


def fsspec_download(url: str, local_path: str | os.PathLike[str]) -> None:
    """Download the fsspec resource at ``url`` to ``local_path``."""
    dest = Path(local_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fs, path = _split(url)
    try:
        fs.get_file(path, str(dest))
    except Exception as error:
        raise FsspecException(f"download failed for {url!r}: {error}") from error


def fsspec_delete(url: str, *, recursive: bool = False) -> None:
    """Remove ``url`` from its fsspec filesystem."""
    fs, path = _split(url)
    try:
        fs.rm(path, recursive=recursive)
    except Exception as error:
        raise FsspecException(f"delete failed for {url!r}: {error}") from error


def fsspec_mkdir(url: str, *, create_parents: bool = True) -> None:
    """Create the directory at ``url`` (optionally including parents)."""
    fs, path = _split(url)
    try:
        fs.makedirs(path, exist_ok=True) if create_parents else fs.mkdir(path)
    except Exception as error:
        raise FsspecException(f"mkdir failed for {url!r}: {error}") from error


def fsspec_list_dir(url: str) -> list[FsspecEntry]:
    """Return a shallow listing of ``url`` as :class:`FsspecEntry` records."""
    fs, path = _split(url)
    try:
        raw = fs.ls(path, detail=True)
    except Exception as error:
        raise FsspecException(f"list_dir failed for {url!r}: {error}") from error
    entries: list[FsspecEntry] = []
    for item in raw:
        if isinstance(item, str):
            entries.append(FsspecEntry(name=item.rsplit("/", 1)[-1], is_dir=False, size=None))
            continue
        raw_name = item.get("name", "")
        name = str(raw_name).rsplit("/", 1)[-1]
        kind = str(item.get("type", "file"))
        is_dir = kind == "directory"
        size_obj = item.get("size")
        size: int | None = int(size_obj) if isinstance(size_obj, int) and not is_dir else None
        entries.append(FsspecEntry(name=name, is_dir=is_dir, size=size))
    return entries
