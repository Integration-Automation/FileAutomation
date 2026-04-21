"""File checksum + integrity verification helpers.

Streaming hashes so multi-GB files don't blow up memory. The hash algorithm
is whatever :func:`hashlib.new` understands (``sha256``, ``sha1``, ``md5``,
``blake2b``, ...). :func:`file_checksum` returns the hex digest;
:func:`verify_checksum` does a constant-time compare against the expected
value so callers can't leak timing on the check.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

from automation_file.exceptions import FileAutomationException, FileNotExistsException
from automation_file.logging_config import file_automation_logger

__all__ = [
    "ChecksumMismatchException",
    "file_checksum",
    "verify_checksum",
]

_DEFAULT_ALGO = "sha256"
_DEFAULT_CHUNK = 1024 * 1024  # 1 MiB


class ChecksumMismatchException(FileAutomationException):
    """Raised when a computed digest does not match the expected value."""


def file_checksum(
    path: str | os.PathLike[str],
    algorithm: str = _DEFAULT_ALGO,
    chunk_size: int = _DEFAULT_CHUNK,
) -> str:
    """Return the hex digest of ``path`` under ``algorithm``.

    Reads the file in ``chunk_size`` blocks so the memory cost is bounded
    regardless of file size. Raises :class:`FileNotExistsException` when the
    path is missing and :class:`ValueError` for unknown algorithms.
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotExistsException(f"checksum target missing: {target}")
    try:
        digest = hashlib.new(algorithm)
    except ValueError as err:
        raise ValueError(f"unknown hash algorithm: {algorithm!r}") from err
    with target.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_checksum(
    path: str | os.PathLike[str],
    expected: str,
    algorithm: str = _DEFAULT_ALGO,
    chunk_size: int = _DEFAULT_CHUNK,
) -> bool:
    """Return True iff ``path``'s digest matches ``expected`` (case-insensitive).

    Uses :func:`hmac.compare_digest` so the match check is constant-time.
    """
    actual = file_checksum(path, algorithm=algorithm, chunk_size=chunk_size)
    matched = hmac.compare_digest(actual.lower(), expected.lower())
    if not matched:
        file_automation_logger.warning("verify_checksum mismatch: %s algo=%s", path, algorithm)
    return matched
