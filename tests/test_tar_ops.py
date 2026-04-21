from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from automation_file import (
    TarException,
    build_default_registry,
    create_tar,
    extract_tar,
)
from automation_file.exceptions import PathTraversalException


@pytest.fixture
def sample_dir(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hello\n", encoding="utf-8")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_text("world\n", encoding="utf-8")
    return src


def test_create_and_extract_gz(sample_dir: Path, tmp_path: Path) -> None:
    archive = tmp_path / "out.tar.gz"
    create_tar(str(sample_dir), str(archive))
    assert archive.is_file()

    dest = tmp_path / "dest"
    members = extract_tar(str(archive), str(dest))
    assert members  # non-empty
    assert (dest / sample_dir.name / "a.txt").read_text(encoding="utf-8") == "hello\n"
    assert (dest / sample_dir.name / "sub" / "b.txt").read_text(encoding="utf-8") == "world\n"


def test_create_uncompressed(sample_dir: Path, tmp_path: Path) -> None:
    archive = tmp_path / "plain.tar"
    create_tar(str(sample_dir), str(archive), compression=None)
    with tarfile.open(str(archive), "r") as tf:
        assert any(name.endswith("a.txt") for name in tf.getnames())


def test_create_bz2(sample_dir: Path, tmp_path: Path) -> None:
    archive = tmp_path / "out.tar.bz2"
    create_tar(str(sample_dir), str(archive), compression="bz2")
    assert archive.is_file()


def test_create_xz(sample_dir: Path, tmp_path: Path) -> None:
    archive = tmp_path / "out.tar.xz"
    create_tar(str(sample_dir), str(archive), compression="xz")
    assert archive.is_file()


def test_unknown_compression_raises(sample_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(TarException):
        create_tar(str(sample_dir), str(tmp_path / "x.tar"), compression="rar")


def test_source_not_found_raises(tmp_path: Path) -> None:
    with pytest.raises(TarException):
        create_tar(str(tmp_path / "nope"), str(tmp_path / "out.tar"))


def test_extract_missing_archive_raises(tmp_path: Path) -> None:
    with pytest.raises(TarException):
        extract_tar(str(tmp_path / "nope.tar.gz"), str(tmp_path / "dest"))


def test_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar"
    with tarfile.open(str(archive), "w") as tf:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = 0
        tf.addfile(info, None)

    with pytest.raises(PathTraversalException):
        extract_tar(str(archive), str(tmp_path / "dest"))


def test_extract_rejects_absolute_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar"
    with tarfile.open(str(archive), "w") as tf:
        info = tarfile.TarInfo(name="link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)

    with pytest.raises(PathTraversalException):
        extract_tar(str(archive), str(tmp_path / "dest"))


def test_tar_actions_registered() -> None:
    registry = build_default_registry()
    assert "FA_create_tar" in registry
    assert "FA_extract_tar" in registry
