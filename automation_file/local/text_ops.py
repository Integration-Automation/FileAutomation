"""Text and binary file helpers: split, merge, encoding conversion, sed, line count.

These are the low-level building blocks for automating large-file handling
(splitting a multi-gigabyte archive into transferable chunks, for instance),
pipeline text munging that currently needs a shell, and cheap text stats.

Every helper writes atomically where a destination file is produced: data
lands in a sibling temp file that is ``os.replace`` d over the final path
after the operation finishes, so a crash leaves either the old content or
the new content — never a partial mix.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from automation_file.exceptions import FileNotExistsException, TextOpsException
from automation_file.logging_config import file_automation_logger

_CHUNK_IO = 1 << 20  # 1 MiB read buffer


def file_split(file_path: str, chunk_size: int, output_dir: str | None = None) -> list[str]:
    """Split ``file_path`` into fixed-size chunks; return the part paths in order.

    Parts are named ``<basename>.part000``, ``<basename>.part001``, ... and
    written under ``output_dir`` if given (created if missing), otherwise
    alongside the source file. ``chunk_size`` is the maximum bytes per part
    and must be > 0.
    """
    if chunk_size <= 0:
        raise TextOpsException("chunk_size must be positive")
    source = Path(file_path)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    dest_dir = Path(output_dir) if output_dir else source.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    with open(source, "rb") as reader:
        index = 0
        while True:
            chunk = reader.read(chunk_size)
            if not chunk:
                break
            part_path = dest_dir / f"{source.name}.part{index:03d}"
            with open(part_path, "wb") as writer:
                writer.write(chunk)
            parts.append(str(part_path))
            index += 1
    file_automation_logger.info("file_split: %s -> %d parts", source, len(parts))
    return parts


def file_merge(parts: list[str], target_path: str) -> bool:
    """Concatenate ``parts`` in list order into ``target_path``. Atomic write."""
    if not parts:
        raise TextOpsException("parts must be a non-empty list")
    missing = [p for p in parts if not Path(p).is_file()]
    if missing:
        raise FileNotExistsException(", ".join(missing))
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(target.parent), delete=False, suffix=".tmp"
        ) as writer:
            tmp_name = writer.name
            for part in parts:
                with open(part, "rb") as reader:
                    for chunk in iter(lambda r=reader: r.read(_CHUNK_IO), b""):
                        writer.write(chunk)
        os.replace(tmp_name, target)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
    file_automation_logger.info("file_merge: %d parts -> %s", len(parts), target)
    return True


def encoding_convert(
    file_path: str,
    target_path: str,
    source_encoding: str,
    target_encoding: str,
    *,
    errors: str = "strict",
) -> bool:
    """Re-encode a text file from ``source_encoding`` to ``target_encoding``.

    ``errors`` follows :func:`codecs.decode`'s contract (``strict`` / ``replace``
    / ``ignore``). Defaults to ``strict`` so mis-declared source encodings
    surface as :class:`TextOpsException` instead of silently corrupting.
    """
    source = Path(file_path)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = source.read_bytes()
        text = raw.decode(source_encoding, errors=errors)
        encoded = text.encode(target_encoding, errors=errors)
    except (LookupError, UnicodeError) as err:
        raise TextOpsException(
            f"encoding_convert {source_encoding}->{target_encoding} failed: {err}"
        ) from err
    _atomic_write_bytes(target, encoded)
    file_automation_logger.info(
        "encoding_convert: %s (%s) -> %s (%s)",
        source,
        source_encoding,
        target,
        target_encoding,
    )
    return True


def line_count(file_path: str, *, encoding: str = "utf-8") -> int:
    """Count lines in a text file. A trailing newline is not counted as an extra line."""
    source = Path(file_path)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    count = 0
    with open(source, encoding=encoding) as reader:
        for _ in reader:
            count += 1
    return count


def sed_replace(
    file_path: str,
    pattern: str,
    replacement: str,
    *,
    regex: bool = False,
    count: int = 0,
    encoding: str = "utf-8",
) -> int:
    """Replace occurrences of ``pattern`` with ``replacement`` in-place; return hit count.

    ``regex=False`` (default) does literal substring replacement; ``regex=True``
    treats ``pattern`` as a :mod:`re` pattern and ``replacement`` may use
    backreferences. ``count=0`` replaces every occurrence; any positive integer
    caps the number of replacements.
    """
    if count < 0:
        raise TextOpsException("count must be >= 0")
    source = Path(file_path)
    if not source.is_file():
        raise FileNotExistsException(str(source))
    original = source.read_text(encoding=encoding)
    try:
        new_text, hits = _apply_replacement(original, pattern, replacement, regex, count)
    except re.error as err:
        raise TextOpsException(f"invalid regex: {err}") from err
    if hits:
        _atomic_write_bytes(source, new_text.encode(encoding))
    file_automation_logger.info("sed_replace: %s -> %d replacement(s)", source, hits)
    return hits


def _apply_replacement(
    text: str, pattern: str, replacement: str, regex: bool, count: int
) -> tuple[str, int]:
    if regex:
        compiled = re.compile(pattern)
        new_text, hits = compiled.subn(replacement, text, count=count)
        return new_text, hits
    if not pattern:
        raise TextOpsException("pattern must not be empty for literal replace")
    hits = text.count(pattern) if count == 0 else min(text.count(pattern), count)
    new_text = text.replace(pattern, replacement, -1 if count == 0 else count)
    return new_text, hits


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=str(target.parent), delete=False, suffix=".tmp"
        ) as writer:
            tmp_name = writer.name
            writer.write(data)
        os.replace(tmp_name, target)
        tmp_name = None
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
