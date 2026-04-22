"""SHA-256 content-addressable store.

:class:`ContentStore` ingests files or byte blobs and keys them by the hex
digest of their contents. A two-character fanout directory keeps any single
directory small: ``<root>/ab/abcdef…``. Identical inputs map to the same blob —
callers get deduplication for free.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import IO

from automation_file.exceptions import CASException

_HASH = "sha256"
_FANOUT = 2
_CHUNK = 1 << 20


class ContentStore:
    """Filesystem-backed CAS under ``root``."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, digest: str) -> Path:
        if len(digest) < _FANOUT + 1 or not all(c in "0123456789abcdef" for c in digest):
            raise CASException(f"invalid digest {digest!r}")
        return self._root / digest[:_FANOUT] / digest

    def exists(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def put(self, source: str | os.PathLike[str]) -> str:
        """Ingest the file at ``source`` and return its hex digest."""
        src = Path(source)
        if not src.is_file():
            raise CASException(f"source is not a file: {src}")
        digest = self._hash_file(src)
        target = self.path_for(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, target)
        except OSError as error:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise CASException(f"failed to ingest {src}: {error}") from error
        return digest

    def put_bytes(self, data: bytes) -> str:
        """Ingest raw bytes and return the hex digest."""
        digest = hashlib.new(_HASH, data).hexdigest()
        target = self.path_for(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, target)
        except OSError as error:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise CASException(f"failed to store blob: {error}") from error
        return digest

    def open(self, digest: str) -> IO[bytes]:
        """Open the stored blob for binary read."""
        path = self.path_for(digest)
        if not path.is_file():
            raise CASException(f"missing blob {digest}")
        return open(path, "rb")

    def copy_to(self, digest: str, destination: str | os.PathLike[str]) -> Path:
        """Copy the blob at ``digest`` into ``destination``. Returns the path."""
        src = self.path_for(digest)
        if not src.is_file():
            raise CASException(f"missing blob {digest}")
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return dest

    def delete(self, digest: str) -> bool:
        """Remove a blob. Returns True when the blob existed."""
        path = self.path_for(digest)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def iter_digests(self) -> Iterator[str]:
        """Yield the digest of every stored blob."""
        if not self._root.exists():
            return
        for bucket in self._root.iterdir():
            if not bucket.is_dir() or len(bucket.name) != _FANOUT:
                continue
            for blob in bucket.iterdir():
                if blob.is_file() and blob.name.startswith(bucket.name):
                    yield blob.name

    def size(self) -> int:
        """Return the total number of stored blobs."""
        return sum(1 for _ in self.iter_digests())

    def _hash_file(self, path: Path) -> str:
        hasher = hashlib.new(_HASH)
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
