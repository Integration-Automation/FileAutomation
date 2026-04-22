"""Tests for automation_file.local.archive_ops."""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from automation_file.exceptions import ArchiveException
from automation_file.local.archive_ops import (
    detect_archive_format,
    extract_archive,
    list_archive,
    supported_formats,
)


def _make_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def _make_tar(path: Path, entries: dict[str, bytes], mode: str = "w") -> None:
    with tarfile.open(path, mode) as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_detect_zip(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    _make_zip(archive, {"x.txt": b"x"})
    assert detect_archive_format(archive) == "zip"


def test_detect_tar(tmp_path: Path) -> None:
    archive = tmp_path / "a.tar"
    _make_tar(archive, {"x.txt": b"x"})
    assert detect_archive_format(archive) == "tar"


def test_detect_tar_gz(tmp_path: Path) -> None:
    archive = tmp_path / "a.tar.gz"
    _make_tar(archive, {"x.txt": b"x"}, mode="w:gz")
    assert detect_archive_format(archive) == "tar.gz"


def test_detect_tar_xz(tmp_path: Path) -> None:
    archive = tmp_path / "a.tar.xz"
    _make_tar(archive, {"x.txt": b"x"}, mode="w:xz")
    assert detect_archive_format(archive) == "tar.xz"


def test_list_zip(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    _make_zip(archive, {"a.txt": b"a", "sub/b.txt": b"b"})
    names = list_archive(archive)
    assert set(names) == {"a.txt", "sub/b.txt"}


def test_extract_zip(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    _make_zip(archive, {"a.txt": b"alpha", "sub/b.txt": b"beta"})
    out = tmp_path / "out"
    names = extract_archive(archive, out)
    assert (out / "a.txt").read_bytes() == b"alpha"
    assert (out / "sub" / "b.txt").read_bytes() == b"beta"
    assert set(names) == {"a.txt", "sub/b.txt"}


def test_extract_tar(tmp_path: Path) -> None:
    archive = tmp_path / "a.tar"
    _make_tar(archive, {"z.txt": b"zed"})
    out = tmp_path / "out"
    extract_archive(archive, out)
    assert (out / "z.txt").read_bytes() == b"zed"


def test_extract_rejects_traversal_zip(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    out = tmp_path / "safe"
    with pytest.raises(ArchiveException):
        extract_archive(archive, out)


def test_unsupported_file_raises(tmp_path: Path) -> None:
    blob = tmp_path / "random.bin"
    blob.write_bytes(b"\x00\x01\x02not-an-archive")
    with pytest.raises(ArchiveException):
        detect_archive_format(blob)


def test_detect_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ArchiveException):
        detect_archive_format(tmp_path / "nope.zip")


def test_supported_formats_lists_known_entries() -> None:
    formats = set(supported_formats())
    assert {"zip", "tar", "tar.gz", "7z", "rar"}.issubset(formats)
