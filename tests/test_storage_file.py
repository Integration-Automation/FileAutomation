"""File and Storage: the object API over the resolver, including cross-backend transfers."""

# The nosec / nosemgrep markers below sit on made-up values and on digests that are the thing
# under test; none is a credential or a security use of a hash.
# pylint: disable=line-too-long  # a marker has to follow the value it is about

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

import automation_file
from automation_file.exceptions import (
    StorageAlreadyExistsException,
    StorageNotFoundException,
    StoragePathTypeException,
    StorageURIException,
)
from automation_file.storage import (
    Checksum,
    File,
    LocalStorage,
    MemoryStorage,
    Storage,
    StorageResolver,
    clear_memory_stores,
    parse_storage_uri,
)

PAYLOAD = bytes(range(256)) * 3
SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


@pytest.fixture
def resolver() -> StorageResolver:
    return StorageResolver()


@pytest.fixture
def remote(resolver: StorageResolver) -> MemoryStorage:
    """A stand-in for a remote backend, mounted below ``vault://bucket/data``."""
    backend = MemoryStorage("remote")
    resolver.mount("vault://bucket/data", backend)
    return backend


# ---------------------------------------------------------------------- File


def test_creating_a_file_touches_nothing(resolver: StorageResolver) -> None:
    file = File("nowhere://host/a.txt", resolver=resolver)
    assert str(file) == "nowhere://host/a.txt"
    assert repr(file) == "File('nowhere://host/a.txt')"
    assert file.name == "a.txt"
    assert file.uri == parse_storage_uri("nowhere://host/a.txt")
    with pytest.raises(StorageURIException):
        file.exists()


def test_write_then_read(resolver: StorageResolver) -> None:
    file = File("memory://scratch/dir/a.bin", resolver=resolver)
    info = file.write(PAYLOAD)
    assert info.path == "dir/a.bin"
    assert info.size == len(PAYLOAD)
    assert file.read() == PAYLOAD
    assert file.exists() is True
    assert file.is_file() is True
    assert file.is_dir() is False


def test_text_round_trips_as_utf8_by_default(resolver: StorageResolver) -> None:
    file = File("memory://scratch/note.txt", resolver=resolver)
    file.write("報告 ✓")
    assert file.read() == "報告 ✓".encode()
    assert file.read_text() == "報告 ✓"
    file.write("été", encoding="latin-1")
    assert file.read() == b"\xe9t\xe9"
    assert file.read_text(encoding="latin-1") == "été"


def test_write_respects_overwrite(resolver: StorageResolver) -> None:
    file = File("memory://scratch/a.txt", resolver=resolver)
    file.write(b"first")
    with pytest.raises(StorageAlreadyExistsException):
        file.write(b"second", overwrite=False)
    assert file.read() == b"first"


def test_metadata_properties_come_from_stat(resolver: StorageResolver, tmp_path: Path) -> None:
    file = File(tmp_path / "notes.txt", resolver=resolver)
    file.write(b"hello")
    info = file.stat()
    assert info.path == parse_storage_uri(tmp_path / "notes.txt").path
    assert file.size == 5
    assert file.modified_at == info.modified_at
    assert file.content_type == "text/plain"
    assert file.etag is None
    assert file.version is None
    assert dict(file.metadata) == {}


def test_a_missing_file(resolver: StorageResolver) -> None:
    file = File("memory://scratch/nope.txt", resolver=resolver)
    assert file.exists() is False
    assert file.is_file() is False
    assert file.is_dir() is False
    with pytest.raises(StorageNotFoundException):
        file.stat()
    with pytest.raises(StorageNotFoundException):
        file.read()
    with pytest.raises(StorageNotFoundException):
        file.delete()
    file.delete(missing_ok=True)


def test_a_directory_is_not_a_file(resolver: StorageResolver) -> None:
    File("memory://scratch/dir/a.txt", resolver=resolver).write(b"x")
    directory = File("memory://scratch/dir", resolver=resolver)
    assert directory.exists() is True
    assert directory.is_dir() is True
    assert directory.is_file() is False
    with pytest.raises(StoragePathTypeException):
        directory.read()
    with pytest.raises(StoragePathTypeException, match="recursive=True"):
        directory.delete()
    assert File("memory://scratch/dir/a.txt", resolver=resolver).read() == b"x"


def test_delete(resolver: StorageResolver) -> None:
    file = File("memory://scratch/a.txt", resolver=resolver)
    file.write(b"x")
    file.delete()
    assert file.exists() is False


def test_upload_from_and_download_to(resolver: StorageResolver, tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(PAYLOAD)
    file = File("memory://scratch/up/a.bin", resolver=resolver)
    assert file.upload_from(source).path == "up/a.bin"
    target = file.download_to(tmp_path / "out" / "a.bin")
    assert target.read_bytes() == PAYLOAD
    with pytest.raises(StorageAlreadyExistsException):
        file.download_to(target, overwrite=False)
    with pytest.raises(StorageAlreadyExistsException):
        file.upload_from(source, overwrite=False)


def test_checksum_and_verify(resolver: StorageResolver) -> None:
    file = File("memory://scratch/a.bin", resolver=resolver)
    file.write(PAYLOAD)
    assert file.checksum() == Checksum("sha256", SHA256)
    assert file.checksum("md5").value == hashlib.md5(PAYLOAD, usedforsecurity=False).hexdigest()  # nosec B324  # nosemgrep
    assert file.verify(SHA256) is True
    assert file.verify(SHA256.upper()) is True
    assert file.verify(f"sha256:{SHA256}") is True
    assert file.verify(Checksum("sha256", SHA256)) is True
    assert file.verify("0" * 64) is False
    md5 = hashlib.md5(PAYLOAD, usedforsecurity=False).hexdigest()  # nosec B324  # nosemgrep
    assert file.verify(md5, algorithm="md5") is True
    assert file.verify(f"md5:{md5}") is True
    assert file.verify(md5) is False


def test_copy_to_another_backend(
    resolver: StorageResolver, remote: MemoryStorage, tmp_path: Path
) -> None:
    source = File(tmp_path / "report.csv", resolver=resolver)
    source.write(PAYLOAD)
    copy = source.copy_to("vault://bucket/data/2026/report.csv")
    assert copy == File("vault://bucket/data/2026/report.csv", resolver=resolver)
    assert remote.read_bytes("2026/report.csv") == PAYLOAD
    assert source.read() == PAYLOAD
    assert copy.checksum().matches(source.checksum()) is True


def test_copy_back_from_another_backend(
    resolver: StorageResolver, remote: MemoryStorage, tmp_path: Path
) -> None:
    remote.write_bytes("in/report.csv", PAYLOAD)
    target = tmp_path / "downloads" / "report.csv"
    File("vault://bucket/data/in/report.csv", resolver=resolver).copy_to(target)
    assert target.read_bytes() == PAYLOAD
    assert [entry.name for entry in target.parent.iterdir()] == ["report.csv"]


def test_copy_to_accepts_a_file_and_respects_overwrite(resolver: StorageResolver) -> None:
    source = File("memory://one/a.txt", resolver=resolver)
    target = File("memory://two/a.txt", resolver=resolver)
    source.write(b"new")
    target.write(b"old")
    with pytest.raises(StorageAlreadyExistsException):
        source.copy_to(target, overwrite=False)
    assert target.read() == b"old"
    assert source.copy_to(target) is target
    assert target.read() == b"new"


def test_move_to_another_backend(
    resolver: StorageResolver, remote: MemoryStorage, tmp_path: Path
) -> None:
    source = File(tmp_path / "report.csv", resolver=resolver)
    source.write(PAYLOAD)
    moved = source.move_to("vault://bucket/data/report.csv")
    assert moved.read() == PAYLOAD
    assert remote.exists("report.csv") is True
    assert source.exists() is False


def test_move_within_the_local_filesystem(resolver: StorageResolver, tmp_path: Path) -> None:
    source = File(tmp_path / "a.txt", resolver=resolver)
    source.write(b"x")
    moved = source.move_to(tmp_path / "sub" / "b.txt")
    assert (tmp_path / "sub" / "b.txt").read_bytes() == b"x"
    assert not (tmp_path / "a.txt").exists()
    assert moved.name == "b.txt"


def test_copy_of_a_missing_file_creates_nothing(
    resolver: StorageResolver, remote: MemoryStorage
) -> None:
    with pytest.raises(StorageNotFoundException):
        File("memory://scratch/nope.txt", resolver=resolver).copy_to("vault://bucket/data/a.txt")
    assert remote.list_dir() == []


def test_copy_onto_a_directory_is_refused(resolver: StorageResolver, remote: MemoryStorage) -> None:
    remote.write_bytes("dir/a.txt", b"x")
    source = File("memory://scratch/a.txt", resolver=resolver)
    source.write(b"y")
    with pytest.raises(StoragePathTypeException):
        source.copy_to("vault://bucket/data/dir")


def test_files_compare_by_uri(resolver: StorageResolver) -> None:
    first = File("memory://scratch/a.txt", resolver=resolver)
    assert first == File("memory://scratch//a.txt/")
    assert first != File("memory://scratch/b.txt")
    assert first != "memory://scratch/a.txt"
    assert len({first, File("memory://scratch/a.txt")}) == 1


def test_a_file_follows_a_backend_mounted_later(resolver: StorageResolver) -> None:
    file = File("vault://later/a.txt", resolver=resolver)
    with pytest.raises(StorageURIException):
        file.exists()
    resolver.mount("vault://later", MemoryStorage("later"))
    file.write(b"x")
    assert file.read() == b"x"


# ---------------------------------------------------------------------- Storage


def test_storage_paths_are_relative_to_its_uri(
    resolver: StorageResolver, remote: MemoryStorage
) -> None:
    for path in ("reports/2026/q1.csv", "reports/2026/q2.csv", "reports/2025/q4.csv", "other.txt"):
        remote.write_bytes(path, b"xy")
    reports = Storage("vault://bucket/data/reports", resolver=resolver)
    assert str(reports) == "vault://bucket/data/reports"
    assert repr(reports) == "Storage('vault://bucket/data/reports')"
    assert reports.uri == parse_storage_uri("vault://bucket/data/reports")
    assert reports.backend is remote
    assert reports.capabilities == remote.capabilities
    assert [info.path for info in reports.list_dir()] == ["2025", "2026"]
    assert [info.path for info in reports.list_dir("2026")] == ["2026/q1.csv", "2026/q2.csv"]
    assert [info.path for info in reports.list_dir(recursive=True)] == [
        "2025",
        "2025/q4.csv",
        "2026",
        "2026/q1.csv",
        "2026/q2.csv",
    ]
    assert reports.stat("2026/q1.csv").path == "2026/q1.csv"
    assert reports.stat("2026/q1.csv").size == 2
    assert reports.stat().path == ""
    assert reports.stat().is_dir is True
    assert reports.exists("2026/q1.csv") is True
    assert reports.exists("other.txt") is False
    assert reports.exists() is True


def test_storage_file_returns_a_file_below_it(
    resolver: StorageResolver, remote: MemoryStorage
) -> None:
    reports = Storage("vault://bucket/data/reports", resolver=resolver)
    file = reports.file("2026/q1.csv")
    assert str(file) == "vault://bucket/data/reports/2026/q1.csv"
    file.write(b"x")
    assert remote.read_bytes("reports/2026/q1.csv") == b"x"
    with pytest.raises(StorageURIException):
        reports.file("../escape.txt")


def test_storage_upload_download_checksum_delete(
    resolver: StorageResolver, remote: MemoryStorage, tmp_path: Path
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(PAYLOAD)
    storage = Storage("vault://bucket/data/in", resolver=resolver)
    assert storage.upload(source, "a/b.bin").path == "a/b.bin"
    assert remote.read_bytes("in/a/b.bin") == PAYLOAD
    assert storage.checksum("a/b.bin") == Checksum("sha256", SHA256)
    assert storage.download("a/b.bin", tmp_path / "out.bin").read_bytes() == PAYLOAD
    storage.mkdir("empty")
    assert storage.stat("empty").is_dir is True
    storage.delete("a", recursive=True)
    assert [info.path for info in storage.list_dir()] == ["empty"]
    storage.delete("", recursive=True)
    assert remote.exists("in") is False
    storage.delete("gone", missing_ok=True)


def test_storage_over_a_local_directory(resolver: StorageResolver, tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()
    storage = Storage(tmp_path / "work", resolver=resolver)
    storage.file("a/b.txt").write(b"x")
    assert (tmp_path / "work" / "a" / "b.txt").read_bytes() == b"x"
    assert [info.path for info in storage.list_dir(recursive=True)] == ["a", "a/b.txt"]
    assert isinstance(storage.backend, LocalStorage)


def test_storage_spanning_a_nested_mount_reports_the_asked_paths(
    resolver: StorageResolver, remote: MemoryStorage
) -> None:
    nested = MemoryStorage("nested")
    resolver.mount("vault://bucket/data/hot", nested)
    nested.write_bytes("a.txt", b"x")
    data = Storage("vault://bucket/data", resolver=resolver)
    assert [info.path for info in data.list_dir("hot")] == ["hot/a.txt"]
    assert data.stat("hot/a.txt").path == "hot/a.txt"
    assert remote.exists("hot") is False


def test_storages_compare_by_uri(resolver: StorageResolver) -> None:
    assert Storage("memory://scratch/a", resolver=resolver) == Storage("memory://scratch/a/")
    assert Storage("memory://scratch/a") != Storage("memory://scratch/b")
    assert len({Storage("memory://scratch/a"), Storage("memory://scratch/a")}) == 1


# ---------------------------------------------------------------------- facade


@pytest.mark.parametrize(
    "name",
    [
        "Checksum",
        "File",
        "FileInfo",
        "LocalStorage",
        "MemoryStorage",
        "Storage",
        "StorageBackend",
        "StorageCapabilities",
        "StorageResolver",
        "StorageURI",
        "parse_storage_uri",
        "StorageException",
        "StorageAlreadyExistsException",
        "StorageNotEmptyException",
        "StorageNotFoundException",
        "StoragePathTypeException",
        "StoragePermissionException",
        "StorageTransientException",
        "StorageURIException",
        "StorageUnavailableException",
        "StorageUnsupportedException",
    ],
)
def test_the_facade_exports_the_storage_layer(name: str) -> None:
    assert name in automation_file.__all__
    assert hasattr(automation_file, name)


def test_the_default_resolver_serves_local_files(tmp_path: Path) -> None:
    file = automation_file.File(tmp_path / "a.txt")
    file.write("hello")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"
    assert automation_file.Storage(tmp_path).list_dir()[0].path == "a.txt"
