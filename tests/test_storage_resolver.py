"""StorageResolver: mounts, scheme factories, and the default table."""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from automation_file.exceptions import StorageURIException
from automation_file.storage import (
    File,
    LocalStorage,
    MemoryStorage,
    Storage,
    StorageBackend,
    StorageResolver,
    StorageURI,
    clear_memory_stores,
    default_resolver,
    memory_store,
    parse_storage_uri,
)


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


@pytest.fixture
def resolver() -> StorageResolver:
    return StorageResolver()


def test_default_schemes(resolver: StorageResolver) -> None:
    assert resolver.schemes() == [
        "azure",
        "dropbox",
        "ftp",
        "ftps",
        "gdrive",
        "local",
        "memory",
        "onedrive",
        "s3",
        "sftp",
    ]
    assert StorageResolver(defaults=False).schemes() == []


def test_local_uri_resolves_to_the_whole_filesystem(
    resolver: StorageResolver, tmp_path: Path
) -> None:
    (tmp_path / "a.txt").write_bytes(b"x")
    backend, path = resolver.resolve(tmp_path / "a.txt")
    assert isinstance(backend, LocalStorage)
    assert backend.root is None
    assert backend.read_bytes(path) == b"x"
    assert resolver.resolve(str(parse_storage_uri(tmp_path / "a.txt"))) == (backend, path)


@pytest.mark.skipif(os.sep == "\\", reason="Windows reads a local authority as a UNC host")
def test_a_local_authority_is_rejected_off_windows(resolver: StorageResolver) -> None:
    with pytest.raises(StorageURIException, match=re.escape("local:///data/report.csv")):
        resolver.resolve("local://data/report.csv")


def test_a_unc_uri_without_a_share_is_rejected(resolver: StorageResolver) -> None:
    with pytest.raises(StorageURIException, match="empty authority"):
        resolver.resolve("local://server")


def test_memory_uri_resolves_to_the_named_store(resolver: StorageResolver) -> None:
    backend, path = resolver.resolve("memory://scratch/dir/a.txt")
    assert backend is memory_store("scratch")
    assert path == "dir/a.txt"
    assert resolver.resolve("memory://other/a.txt")[0] is not backend


def test_an_unknown_scheme_names_the_known_ones(resolver: StorageResolver) -> None:
    with pytest.raises(StorageURIException) as caught:
        resolver.resolve("gopher://host/a.txt")
    message = str(caught.value)
    assert "'gopher'" in message
    assert "gopher://host/a.txt" in message
    assert "known schemes: azure, dropbox, ftp, ftps, gdrive, local, memory" in message


def test_register_scheme_installs_a_factory(resolver: StorageResolver) -> None:
    store = MemoryStorage("custom")

    def factory(uri: StorageURI) -> tuple[StorageBackend, str]:
        return store, f"{uri.authority}/{uri.path}"

    resolver.register_scheme("Custom", factory)
    assert "custom" in resolver.schemes()
    assert resolver.resolve("custom://bucket/a.txt") == (store, "bucket/a.txt")
    assert resolver.unregister_scheme("custom") is True
    assert resolver.unregister_scheme("custom") is False
    with pytest.raises(StorageURIException):
        resolver.resolve("custom://bucket/a.txt")


def test_register_scheme_rejects_a_non_callable(resolver: StorageResolver) -> None:
    not_a_factory: Any = "nope"
    with pytest.raises(TypeError):
        resolver.register_scheme("custom", not_a_factory)


def test_mount_serves_a_uri_and_everything_below(resolver: StorageResolver) -> None:
    nas = MemoryStorage("nas")
    resolver.mount("vault://nas/archive", nas)
    assert resolver.resolve("vault://nas/archive") == (nas, "")
    assert resolver.resolve("vault://nas/archive/2026/a.txt") == (nas, "2026/a.txt")
    assert "vault" in resolver.schemes()
    with pytest.raises(StorageURIException):
        resolver.resolve("vault://nas/archived/a.txt")
    with pytest.raises(StorageURIException):
        resolver.resolve("vault://other/archive/a.txt")


def test_the_longest_mount_wins(resolver: StorageResolver) -> None:
    whole, part = MemoryStorage("whole"), MemoryStorage("part")
    resolver.mount("vault://bucket", whole)
    resolver.mount("vault://bucket/reports/2026", part)
    assert resolver.resolve("vault://bucket/reports/2026/q1.csv") == (part, "q1.csv")
    assert resolver.resolve("vault://bucket/reports/2025/q1.csv") == (whole, "reports/2025/q1.csv")
    assert resolver.resolve("vault://bucket") == (whole, "")


def test_a_mount_takes_precedence_over_the_scheme_factory(resolver: StorageResolver) -> None:
    pinned = MemoryStorage("pinned")
    resolver.mount("memory://scratch/pinned", pinned)
    assert resolver.resolve("memory://scratch/pinned/a.txt") == (pinned, "a.txt")
    assert resolver.resolve("memory://scratch/free/a.txt")[0] is memory_store("scratch")


def test_mount_authority_matches_case_insensitively(resolver: StorageResolver) -> None:
    nas = MemoryStorage("nas")
    resolver.mount("vault://NAS.example.com", nas)
    assert resolver.resolve("vault://nas.example.com/a.txt") == (nas, "a.txt")


def test_unmount(resolver: StorageResolver) -> None:
    resolver.mount("vault://nas", MemoryStorage("nas"))
    assert resolver.unmount("vault://nas/other") is False
    assert resolver.unmount("vault://nas") is True
    assert resolver.unmount("vault://nas") is False
    assert "vault" not in resolver.schemes()


def test_mount_rejects_what_is_not_a_backend(resolver: StorageResolver) -> None:
    not_a_backend: Any = object()
    with pytest.raises(TypeError, match="StorageBackend"):
        resolver.mount("vault://nas", not_a_backend)


def test_capabilities_come_from_the_resolved_backend(resolver: StorageResolver) -> None:
    assert resolver.capabilities("memory://scratch").directories is True
    assert resolver.capabilities("local:///").content_type is True


def test_resolvers_are_independent(resolver: StorageResolver) -> None:
    resolver.mount("vault://nas", MemoryStorage("nas"))
    assert "vault" not in StorageResolver().schemes()
    assert "vault" not in default_resolver.schemes()


def test_storage_static_methods_drive_the_default_resolver() -> None:
    nas = MemoryStorage("nas")
    Storage.mount("vault://storage-test-nas", nas)
    try:
        assert Storage.resolve("vault://storage-test-nas/a.txt") == (nas, "a.txt")
        assert default_resolver.resolve("vault://storage-test-nas/a.txt") == (nas, "a.txt")
        assert "vault" in Storage.schemes()
    finally:
        assert Storage.unmount("vault://storage-test-nas") is True
    Storage.register_scheme("storage-test", lambda uri: (nas, uri.path))
    try:
        assert Storage.resolve("storage-test://x/a.txt") == (nas, "a.txt")
    finally:
        assert default_resolver.unregister_scheme("storage-test") is True


def test_a_rooted_backend_behind_its_own_authority_is_a_sandbox(
    resolver: StorageResolver, tmp_path: Path
) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (tmp_path / "secret.txt").write_bytes(b"secret")
    resolver.mount("sandbox://jobs", LocalStorage(jobs))
    File("sandbox://jobs/42/out.csv", resolver=resolver).write(b"done")
    assert (jobs / "42" / "out.csv").read_bytes() == b"done"
    backend, path = resolver.resolve("sandbox://jobs/42/out.csv")
    assert repr(backend) == f"LocalStorage({str(jobs.resolve())!r})"
    assert path == "42/out.csv"
    with pytest.raises(StorageURIException):
        File("sandbox://jobs/../secret.txt", resolver=resolver)
    assert [info.path for info in Storage("sandbox://jobs", resolver=resolver).list_dir()] == ["42"]


def test_backend_reprs() -> None:
    assert repr(LocalStorage()) == "LocalStorage()"
    assert repr(MemoryStorage("scratch")) == "MemoryStorage('scratch')"
