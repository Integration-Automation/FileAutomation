"""MIME type detection by extension plus magic-byte sniffing.

The stdlib ``mimetypes`` module covers the common cases from the filename
alone. For ambiguous or extensionless files, :func:`detect_mime` peeks at the
first few bytes and recognises a small set of well-known signatures.
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

_SNIFF_LEN = 16
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b", "application/gzip"),
    (b"BZh", "application/x-bzip2"),
    (b"\xfd7zXZ\x00", "application/x-xz"),
    (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (b"Rar!\x1a\x07\x00", "application/vnd.rar"),
    (b"Rar!\x1a\x07\x01\x00", "application/vnd.rar"),
    (b"RIFF", "application/octet-stream"),  # overridden below for wav/webp
    (b"\x00\x00\x00 ftyp", "video/mp4"),
    (b"OggS", "application/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"{\\rtf", "application/rtf"),
    (b"SQLite format 3\x00", "application/vnd.sqlite3"),
)


def detect_mime(path: str | os.PathLike[str]) -> str:
    """Return the most specific MIME type we can determine for ``path``.

    Tries filename-based detection first; on miss or ambiguous result
    (``application/octet-stream``), sniffs the first ``_SNIFF_LEN`` bytes.
    """
    p = Path(path)
    guessed, _ = mimetypes.guess_type(p.name)
    if guessed:
        return guessed
    sniffed = _sniff(p)
    return sniffed or "application/octet-stream"


def detect_from_bytes(data: bytes) -> str:
    """MIME type of a byte blob using magic-byte sniffing."""
    mime = _match_signatures(data)
    return mime or "application/octet-stream"


def _sniff(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as fh:
            head = fh.read(_SNIFF_LEN)
    except OSError:
        return None
    return _match_signatures(head)


def _match_signatures(head: bytes) -> str | None:
    if head.startswith(b"RIFF") and len(head) >= 12:
        tag = head[8:12]
        if tag == b"WAVE":
            return "audio/wav"
        if tag == b"WEBP":
            return "image/webp"
    for signature, mime in _SIGNATURES:
        if signature == b"RIFF":
            continue
        if head.startswith(signature):
            return mime
    return None
