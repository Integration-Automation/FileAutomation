"""Hash Engine: which digests may prove integrity, and hashing many files at once.

``sha256`` is the default; ``sha512`` and ``blake2b`` are the alternatives. ``md5``
and ``sha1`` are refused unless the caller passes ``allow_weak=True``: both have
practical collisions, so a file can be replaced by another with the same digest.
They exist only to keep reading a baseline that was written with one of them.

Files are hashed through the storage layer's ``checksum``, several at a time on
a thread pool, so the engine works on any backend.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from automation_file.exceptions import FileNotExistsException, StoragePathTypeException
from automation_file.integrity.errors import IntegrityException
from automation_file.storage.storage import Storage

DEFAULT_ALGORITHM = "sha256"
STRONG_ALGORITHMS = ("sha256", "sha512", "blake2b")
WEAK_ALGORITHMS = ("md5", "sha1")
_DEFAULT_WORKERS = 8

_ResultT = TypeVar("_ResultT")


def checked_algorithm(algorithm: str, *, allow_weak: bool = False) -> str:
    """Return the lower-case name of ``algorithm``, or raise when it may not be used."""
    name = str(algorithm).strip().lower()
    if name in STRONG_ALGORITHMS:
        return name
    choices = ", ".join(STRONG_ALGORITHMS)
    if name not in WEAK_ALGORITHMS:
        raise IntegrityException(
            f"unsupported integrity algorithm {algorithm!r}: choose {choices} "
            f"({', '.join(WEAK_ALGORITHMS)} only with allow_weak=True)"
        )
    if not allow_weak:
        raise IntegrityException(
            f"{name} is refused for integrity checks: it is not collision-resistant, so a file "
            f"can be replaced by another with the same digest and the change goes unnoticed. "
            f"Use {choices}; pass allow_weak=True only to keep reading a baseline that was "
            f"written with {name}"
        )
    return name


class HashEngine:
    """Hashes files of one :class:`~automation_file.storage.Storage` with one algorithm."""

    def __init__(
        self,
        algorithm: str = DEFAULT_ALGORITHM,
        *,
        allow_weak: bool = False,
        max_workers: int | None = None,
    ) -> None:
        self._algorithm = checked_algorithm(algorithm, allow_weak=allow_weak)
        if max_workers is not None and max_workers < 1:
            raise IntegrityException("max_workers must be at least 1")
        self._max_workers = max_workers or _DEFAULT_WORKERS

    @property
    def algorithm(self) -> str:
        return self._algorithm

    def hash_file(self, storage: Storage, path: str) -> str | None:
        """Return the hex digest of ``path``, or ``None`` when the file is no longer there."""
        try:
            return storage.checksum(path, self._algorithm).value
        except (FileNotExistsException, StoragePathTypeException):
            return None

    def hash_many(self, storage: Storage, paths: Iterable[str]) -> dict[str, str]:
        """Return the digest of every path; a file that vanished meanwhile is left out."""
        digests = self.map(lambda path: self.hash_file(storage, path), paths)
        return {path: digest for path, digest in digests.items() if digest is not None}

    def map(self, work: Callable[[str], _ResultT], paths: Iterable[str]) -> dict[str, _ResultT]:
        """Call ``work(path)`` for every path on the thread pool and return the results by path.

        The first failure is raised and the calls that have not started are dropped.
        """
        todo = list(dict.fromkeys(paths))
        if len(todo) <= 1 or self._max_workers == 1:
            return {path: work(path) for path in todo}
        workers = min(self._max_workers, len(todo))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fa-integrity") as pool:
            futures = {path: pool.submit(work, path) for path in todo}
            try:
                return {path: future.result() for path, future in futures.items()}
            finally:
                for future in futures.values():
                    future.cancel()
