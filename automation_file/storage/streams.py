"""File objects over a staged local copy.

A backend that cannot stream natively still offers ``open_read`` and
``open_write`` through these two classes: the reader serves a downloaded copy and
removes it when closed; the writer collects what is written and hands the
finished file to the backend when closed.
"""

from __future__ import annotations

import io
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import TracebackType

_STAGED_NAME = "staged"


def new_scratch_file() -> tuple[Path, Path]:
    """Create a private scratch directory and return ``(directory, file path inside it)``."""
    scratch = Path(tempfile.mkdtemp())
    return scratch, scratch / _STAGED_NAME


class StagedReader(io.BufferedReader):
    """Read a staged copy; closing it removes the copy."""

    def __init__(self, staged: Path, scratch: Path) -> None:
        super().__init__(io.FileIO(staged, "rb"))
        self._scratch = scratch

    def close(self) -> None:
        try:
            super().close()
        finally:
            shutil.rmtree(self._scratch, ignore_errors=True)


class StagedWriter(io.BufferedWriter):
    """Collect written bytes; closing it stores them through ``commit``.

    Leaving a ``with`` block through an exception, calling :meth:`discard`, or
    dropping the object without closing it stores nothing.
    """

    def __init__(self, commit: Callable[[Path], object]) -> None:
        self._scratch, self._staged = new_scratch_file()
        super().__init__(io.FileIO(self._staged, "wb"))
        self._commit: Callable[[Path], object] | None = commit

    def discard(self) -> None:
        """Close without storing anything."""
        self._commit = None
        self.close()

    def close(self) -> None:
        # pylint: disable-next=using-constant-test  # closed is a property of the stream
        if self.closed:
            return
        commit, self._commit = self._commit, None
        try:
            super().close()
            if commit is not None:
                commit(self._staged)
        finally:
            shutil.rmtree(self._scratch, ignore_errors=True)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self._commit = None
        super().__exit__(exc_type, exc, tb)

    def __del__(self) -> None:
        # A writer that was never closed must not store a half-written file.
        self._commit = None
        self.close()
