"""Tests for automation_file.local.zip_ops."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from automation_file.exceptions import ZipInputException
from automation_file.local import zip_ops


def test_zip_file_single(tmp_path: Path, sample_file: Path) -> None:
    archive = tmp_path / "one.zip"
    zip_ops.zip_file(str(archive), str(sample_file))
    with zipfile.ZipFile(archive) as zf:
        assert zf.namelist() == [sample_file.name]


def test_zip_file_many(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    a.write_text("a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("b", encoding="utf-8")
    archive = tmp_path / "many.zip"
    zip_ops.zip_file(str(archive), [str(a), str(b)])
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["a.txt", "b.txt"]


def test_zip_file_rejects_bad_type(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with pytest.raises(ZipInputException):
        zip_ops.zip_file(str(archive), 123)  # type: ignore[arg-type]


def test_zip_dir(tmp_path: Path, sample_dir: Path) -> None:
    base = tmp_path / "snapshot"
    zip_ops.zip_dir(str(sample_dir), str(base))
    archive = base.with_suffix(".zip")
    assert archive.is_file()
    with zipfile.ZipFile(archive) as zf:
        assert "a.txt" in zf.namelist()


def test_unzip_and_read(tmp_path: Path, sample_file: Path) -> None:
    archive = tmp_path / "one.zip"
    zip_ops.zip_file(str(archive), str(sample_file))

    extract_dir = tmp_path / "out"
    extract_dir.mkdir()
    zip_ops.unzip_file(str(archive), sample_file.name, extract_path=str(extract_dir))
    assert (extract_dir / sample_file.name).is_file()

    assert zip_ops.read_zip_file(str(archive), sample_file.name) == b"hello world"


def test_unzip_all(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    a.write_text("a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("b", encoding="utf-8")
    archive = tmp_path / "pair.zip"
    zip_ops.zip_file(str(archive), [str(a), str(b)])

    extract_dir = tmp_path / "out"
    extract_dir.mkdir()
    zip_ops.unzip_all(str(archive), extract_path=str(extract_dir))
    assert {p.name for p in extract_dir.iterdir()} == {"a.txt", "b.txt"}


def test_zip_info_and_file_info(tmp_path: Path, sample_file: Path) -> None:
    archive = tmp_path / "info.zip"
    zip_ops.zip_file(str(archive), str(sample_file))
    assert zip_ops.zip_file_info(str(archive)) == [sample_file.name]
    info_list = zip_ops.zip_info(str(archive))
    assert len(info_list) == 1
    assert info_list[0].filename == sample_file.name


def test_set_zip_password_on_plain_archive(tmp_path: Path, sample_file: Path) -> None:
    """Standard zipfile only accepts password on encrypted archives; plain archives
    still allow the API call — assert it doesn't raise."""
    archive = tmp_path / "plain.zip"
    zip_ops.zip_file(str(archive), str(sample_file))
    zip_ops.set_zip_password(str(archive), b"12345678")
