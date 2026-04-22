"""Cross-platform advisory file lock.

Uses ``fcntl.flock`` on POSIX and ``msvcrt.locking`` on Windows, so two processes
can serialise on a well-known lock path. Locks are exclusive (writer-style);
shared locks are not supported because ``msvcrt`` cannot express them portably.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import IO

from automation_file.exceptions import LockTimeoutException

_POLL_INTERVAL = 0.05


class FileLock:
    """Advisory exclusive lock on a sidecar lock file.

    ``path`` is the lock file itself — typically ``<resource>.lock`` next to the
    protected resource. ``timeout`` is the maximum seconds to wait when
    acquiring; ``None`` waits indefinitely, ``0`` fails immediately.
    """

    def __init__(self, path: str | os.PathLike[str], timeout: float | None = None) -> None:
        self._path = Path(path)
        self._timeout = timeout
        self._fh: IO[bytes] | None = None
        self._thread_lock = threading.Lock()
        self._owned = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_held(self) -> bool:
        return self._owned

    def acquire(self) -> None:
        """Block until the lock is held. Raises :class:`LockTimeoutException` on timeout."""
        with self._thread_lock:
            if self._owned:
                raise LockTimeoutException(f"lock {self._path} already held by this instance")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(self._path, "a+b")  # noqa: SIM115 — held across acquire/release
            try:
                self._acquire_os_lock(fh)
            except BaseException:
                fh.close()
                raise
            self._fh = fh
            self._owned = True

    def release(self) -> None:
        """Release the lock; idempotent."""
        with self._thread_lock:
            if not self._owned or self._fh is None:
                return
            try:
                self._release_os_lock(self._fh)
            finally:
                self._fh.close()
                self._fh = None
                self._owned = False

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    def _acquire_os_lock(self, fh: IO[bytes]) -> None:
        deadline = None if self._timeout is None else time.monotonic() + self._timeout
        while True:
            if _try_lock(fh):
                return
            if deadline is not None and time.monotonic() >= deadline:
                raise LockTimeoutException(
                    f"timed out acquiring lock {self._path} after {self._timeout}s"
                )
            time.sleep(_POLL_INTERVAL)

    def _release_os_lock(self, fh: IO[bytes]) -> None:
        _unlock(fh)


if sys.platform == "win32":
    import msvcrt

    def _try_lock(fh: IO[bytes]) -> bool:
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fh: IO[bytes]) -> None:
        with contextlib.suppress(OSError):
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fh: IO[bytes]) -> bool:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fh: IO[bytes]) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
