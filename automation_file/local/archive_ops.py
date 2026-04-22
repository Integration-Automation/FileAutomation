"""Archive format auto-detect and safe extraction.

Covers ZIP and the tar family (plain, gzip, bzip2, xz) from the stdlib. Adds
optional read-only support for 7z (via ``py7zr``) and RAR (via ``rarfile``) if
those packages are installed. Extraction refuses paths that escape the target
root — same guarantee as :func:`automation_file.local.safe_paths.safe_join`.
"""

from __future__ import annotations

import os
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path

from automation_file.exceptions import ArchiveException
from automation_file.local.safe_paths import is_within

_ZIP_SIG = b"PK\x03\x04"
_SEVEN_ZIP_SIG = b"7z\xbc\xaf\x27\x1c"
_RAR_SIG_V4 = b"Rar!\x1a\x07\x00"
_RAR_SIG_V5 = b"Rar!\x1a\x07\x01\x00"
_GZIP_SIG = b"\x1f\x8b"
_BZ2_SIG = b"BZh"
_XZ_SIG = b"\xfd7zXZ\x00"


def detect_archive_format(path: str | os.PathLike[str]) -> str:
    """Return one of zip / tar / 7z / rar / gz / bz2 / xz based on magic bytes."""
    src = Path(path)
    if not src.is_file():
        raise ArchiveException(f"not a file: {src}")
    with open(src, "rb") as fh:
        head = fh.read(262)
    if head.startswith(_ZIP_SIG):
        return "zip"
    if head.startswith(_SEVEN_ZIP_SIG):
        return "7z"
    if head.startswith(_RAR_SIG_V5) or head.startswith(_RAR_SIG_V4):
        return "rar"
    if head.startswith(_XZ_SIG):
        return "tar.xz" if _is_tar_stream(src, "xz") else "xz"
    if head.startswith(_BZ2_SIG):
        return "tar.bz2" if _is_tar_stream(src, "bz2") else "bz2"
    if head.startswith(_GZIP_SIG):
        return "tar.gz" if _is_tar_stream(src, "gz") else "gz"
    if tarfile.is_tarfile(src):
        return "tar"
    raise ArchiveException(f"unsupported archive format: {src}")


def list_archive(path: str | os.PathLike[str]) -> list[str]:
    """Return the entry names inside ``path``."""
    fmt = detect_archive_format(path)
    if fmt == "zip":
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    if fmt.startswith("tar"):
        with tarfile.open(path) as tf:  # nosec B202  # NOSONAR(python:S5042) metadata listing only, no extraction
            return tf.getnames()
    if fmt == "7z":
        return _seven_zip_namelist(path)
    if fmt == "rar":
        return _rar_namelist(path)
    raise ArchiveException(f"listing not supported for format {fmt!r}")


def extract_archive(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
) -> list[str]:
    """Extract ``source`` into ``target``. Returns the list of extracted names."""
    fmt = detect_archive_format(source)
    dest = Path(target)
    dest.mkdir(parents=True, exist_ok=True)
    if fmt == "zip":
        return _extract_zip(Path(source), dest)
    if fmt.startswith("tar"):
        return _extract_tar(Path(source), dest)
    if fmt == "7z":
        return _extract_seven_zip(Path(source), dest)
    if fmt == "rar":
        return _extract_rar(Path(source), dest)
    raise ArchiveException(f"extraction not supported for format {fmt!r}")


def _is_tar_stream(path: Path, compression: str) -> bool:
    try:
        if compression == "gz":
            with tarfile.open(path, mode="r:gz"):  # nosec B202  # NOSONAR(python:S5042) read-only probe, no extraction
                return True
        if compression == "bz2":
            with tarfile.open(path, mode="r:bz2"):  # nosec B202  # NOSONAR(python:S5042) read-only probe, no extraction
                return True
        if compression == "xz":
            with tarfile.open(path, mode="r:xz"):  # nosec B202  # NOSONAR(python:S5042) read-only probe, no extraction
                return True
    except (tarfile.TarError, OSError):
        return False
    return False


def _extract_zip(source: Path, dest: Path) -> list[str]:
    names: list[str] = []
    with zipfile.ZipFile(source) as zf:
        for info in zf.infolist():
            out = dest / info.filename
            _ensure_within(dest, out)
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src_fh, open(out, "wb") as dst_fh:
                while True:
                    chunk = src_fh.read(1 << 20)
                    if not chunk:
                        break
                    dst_fh.write(chunk)
            names.append(info.filename)
    return names


def _extract_tar(source: Path, dest: Path) -> list[str]:
    names: list[str] = []
    # Per-member path containment + link rejection below; on 3.12+ the
    # tarfile.data_filter enforces the same rules at the C layer.
    with tarfile.open(source) as tf:  # nosec B202  # NOSONAR(python:S5042) entries validated before extract
        _apply_tar_data_filter(tf)
        for member in tf.getmembers():
            out = dest / member.name
            _ensure_within(dest, out)
            if member.islnk() or member.issym():
                raise ArchiveException(f"refusing to extract link: {member.name}")
            tf.extract(member, dest)
            names.append(member.name)
    return names


def _apply_tar_data_filter(tf: tarfile.TarFile) -> None:
    data_filter = getattr(tarfile, "data_filter", None)
    if data_filter is not None:
        tf.extraction_filter = data_filter


def _extract_seven_zip(source: Path, dest: Path) -> list[str]:
    try:
        import py7zr
    except ImportError as error:
        raise ArchiveException("py7zr is required for 7z extraction") from error
    with py7zr.SevenZipFile(source, mode="r") as archive:
        names = archive.getnames()
        for name in names:
            _ensure_within(dest, dest / name)
        # Every entry name has been validated via _ensure_within above.
        archive.extractall(path=dest)  # nosec B202 - entries validated before extract
    return list(names)


def _extract_rar(source: Path, dest: Path) -> list[str]:
    try:
        import rarfile
    except ImportError as error:
        raise ArchiveException("rarfile is required for RAR extraction") from error
    with rarfile.RarFile(source) as archive:
        names = archive.namelist()
        for name in names:
            _ensure_within(dest, dest / name)
        # Every entry name has been validated via _ensure_within above.
        archive.extractall(path=str(dest))  # nosec B202 - entries validated before extract
    return list(names)


def _seven_zip_namelist(path: str | os.PathLike[str]) -> list[str]:
    try:
        import py7zr
    except ImportError as error:
        raise ArchiveException("py7zr is required to list 7z contents") from error
    with py7zr.SevenZipFile(path, mode="r") as archive:
        return list(archive.getnames())


def _rar_namelist(path: str | os.PathLike[str]) -> list[str]:
    try:
        import rarfile
    except ImportError as error:
        raise ArchiveException("rarfile is required to list RAR contents") from error
    with rarfile.RarFile(path) as archive:
        return list(archive.namelist())


def _ensure_within(root: Path, candidate: Path) -> None:
    if not is_within(root, candidate):
        raise ArchiveException(f"archive entry escapes target root: {candidate}")


def supported_formats() -> Iterable[str]:
    """Return the archive tags this module can detect."""
    return ("zip", "tar", "tar.gz", "tar.bz2", "tar.xz", "gz", "bz2", "xz", "7z", "rar")
