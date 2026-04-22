"""Tests for automation_file.remote.fsspec_bridge."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest

fsspec = pytest.importorskip("fsspec")

# pylint: disable=wrong-import-position  # importorskip must precede these imports
from automation_file.exceptions import FsspecException  # noqa: E402
from automation_file.remote.fsspec_bridge import (  # noqa: E402
    FsspecEntry,
    fsspec_delete,
    fsspec_download,
    fsspec_exists,
    fsspec_list_dir,
    fsspec_mkdir,
    fsspec_upload,
    get_fs,
)


def _purge_memory_fs() -> None:
    fs = fsspec.filesystem("memory")
    # list() snapshot required — fs.rm() mutates fs.store during iteration.
    for path in list(fs.store):  # NOSONAR snapshot required — fs.rm mutates fs.store
        with contextlib.suppress(FileNotFoundError):
            fs.rm(path)


@pytest.fixture(autouse=True)
def _reset_memory_fs() -> Iterator[None]:
    _purge_memory_fs()
    yield
    _purge_memory_fs()


def test_get_fs_from_protocol() -> None:
    fs = get_fs("memory")
    assert fs.protocol == "memory"


def test_get_fs_from_url() -> None:
    fs = get_fs("memory://bucket/key")
    assert fs.protocol == "memory"


def test_upload_download_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "src.bin"
    source.write_bytes(b"round-trip")
    fsspec_upload(source, "memory://bucket/data.bin")
    assert fsspec_exists("memory://bucket/data.bin") is True

    dest = tmp_path / "out" / "copy.bin"
    fsspec_download("memory://bucket/data.bin", dest)
    assert dest.read_bytes() == b"round-trip"


def test_exists_false() -> None:
    assert fsspec_exists("memory://bucket/missing.bin") is False


def test_upload_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FsspecException):
        fsspec_upload(tmp_path / "nope.bin", "memory://bucket/x.bin")


def test_delete_removes_file(tmp_path: Path) -> None:
    source = tmp_path / "x.bin"
    source.write_bytes(b"x")
    fsspec_upload(source, "memory://bucket/x.bin")
    assert fsspec_exists("memory://bucket/x.bin") is True
    fsspec_delete("memory://bucket/x.bin")
    assert fsspec_exists("memory://bucket/x.bin") is False


def test_mkdir_and_list(tmp_path: Path) -> None:
    fsspec_mkdir("memory://bucket/folder")
    src = tmp_path / "a.bin"
    src.write_bytes(b"a")
    fsspec_upload(src, "memory://bucket/folder/a.bin")
    entries = fsspec_list_dir("memory://bucket/folder")
    names = {entry.name for entry in entries}
    assert "a.bin" in names
    file_entry = next(entry for entry in entries if entry.name == "a.bin")
    assert isinstance(file_entry, FsspecEntry)
    assert file_entry.is_dir is False
    assert file_entry.size == 1


def test_list_dir_raises_on_missing() -> None:
    with pytest.raises(FsspecException):
        fsspec_list_dir("memory://bucket/definitely-not-there")


def test_get_fs_rejects_unknown_protocol() -> None:
    with pytest.raises(FsspecException):
        get_fs("nope-no-such-protocol")
