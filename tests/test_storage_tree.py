"""copy_tree and sync_tree: directory trees between any two backends."""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePathTypeException,
)
from automation_file.storage import (
    File,
    MemoryStorage,
    Storage,
    StorageResolver,
    TreeResult,
    clear_memory_stores,
    copy_tree,
    sync_tree,
)


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


@pytest.fixture
def resolver() -> StorageResolver:
    return StorageResolver()


@pytest.fixture
def source(resolver: StorageResolver) -> Storage:
    storage = Storage("memory://one/src", resolver=resolver)
    for path, data in (("a.txt", b"a"), ("sub/b.txt", b"bb"), ("sub/deep/c.txt", b"ccc")):
        storage.file(path).write(data)
    storage.mkdir("empty")
    return storage


def _files(storage: Storage) -> dict[str, bytes]:
    return {
        info.path: storage.file(info.path).read()
        for info in storage.list_dir(recursive=True)
        if not info.is_dir
    }


def test_copy_tree_to_another_backend(source: Storage, tmp_path: Path) -> None:
    target = Storage(tmp_path / "out", resolver=StorageResolver())
    result = source.copy_to(target)
    assert isinstance(result, TreeResult)
    assert result.copied == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    assert (result.skipped, result.deleted, result.errors, result.dry_run) == ([], [], {}, False)
    assert result.ok is True
    assert _files(target) == {"a.txt": b"a", "sub/b.txt": b"bb", "sub/deep/c.txt": b"ccc"}
    assert (tmp_path / "out" / "empty").is_dir()


def test_copy_tree_accepts_a_uri_and_uses_the_same_resolver(
    source: Storage, resolver: StorageResolver
) -> None:
    resolver.mount("vault://bucket", MemoryStorage("vault"))
    result = source.copy_to("vault://bucket/backup")
    assert result.copied == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    assert File("vault://bucket/backup/sub/b.txt", resolver=resolver).read() == b"bb"


def test_copy_tree_without_overwrite_skips_what_exists(
    source: Storage, resolver: StorageResolver
) -> None:
    target = Storage("memory://two/dst", resolver=resolver)
    target.file("a.txt").write(b"kept")
    result = copy_tree(source, target, overwrite=False)
    assert result.skipped == ["a.txt"]
    assert result.copied == ["sub/b.txt", "sub/deep/c.txt"]
    assert target.file("a.txt").read() == b"kept"
    assert copy_tree(source, target).copied == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    assert target.file("a.txt").read() == b"a"


def test_copy_tree_needs_an_existing_source_directory(resolver: StorageResolver) -> None:
    target = Storage("memory://two/dst", resolver=resolver)
    with pytest.raises(StorageNotFoundException):
        copy_tree(Storage("memory://one/nope", resolver=resolver), target)
    File("memory://one/file.txt", resolver=resolver).write(b"x")
    with pytest.raises(StoragePathTypeException):
        copy_tree(Storage("memory://one/file.txt", resolver=resolver), target)


def test_a_tree_cannot_be_copied_onto_itself(source: Storage, resolver: StorageResolver) -> None:
    with pytest.raises(StorageException, match="both the source and the target"):
        source.copy_to("memory://one/src/")
    with pytest.raises(StorageException, match="both the source and the target"):
        sync_tree(source, Storage("memory://one/src", resolver=resolver))


def test_sync_copies_only_what_changed(source: Storage, resolver: StorageResolver) -> None:
    target = Storage("memory://two/dst", resolver=resolver)
    assert source.sync_to(target).copied == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    again = source.sync_to(target)
    assert again.copied == []
    assert again.skipped == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    source.file("sub/b.txt").write(b"longer now")
    changed = source.sync_to(target)
    assert changed.copied == ["sub/b.txt"]
    assert changed.skipped == ["a.txt", "sub/deep/c.txt"]
    assert target.file("sub/b.txt").read() == b"longer now"


def test_sync_copies_a_newer_file_of_the_same_size(tmp_path: Path) -> None:
    resolver = StorageResolver()
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    (tmp_path / "src" / "a.txt").write_bytes(b"new!")
    (tmp_path / "dst" / "a.txt").write_bytes(b"old!")
    os.utime(tmp_path / "dst" / "a.txt", (1_600_000_000, 1_600_000_000))
    source = Storage(tmp_path / "src", resolver=resolver)
    target = Storage(tmp_path / "dst", resolver=resolver)
    assert source.sync_to(target).copied == ["a.txt"]
    assert (tmp_path / "dst" / "a.txt").read_bytes() == b"new!"
    os.utime(tmp_path / "src" / "a.txt", (1_500_000_000, 1_500_000_000))
    (tmp_path / "dst" / "a.txt").write_bytes(b"tgt!")
    assert source.sync_to(target).skipped == ["a.txt"]
    assert (tmp_path / "dst" / "a.txt").read_bytes() == b"tgt!"
    assert source.sync_to(target, checksum=True).copied == ["a.txt"]
    assert (tmp_path / "dst" / "a.txt").read_bytes() == b"new!"
    assert source.sync_to(target, checksum=True).skipped == ["a.txt"]


def test_sync_with_delete_removes_what_the_source_lacks(
    source: Storage, resolver: StorageResolver
) -> None:
    target = Storage("memory://two/dst", resolver=resolver)
    source.sync_to(target)
    target.file("stale.txt").write(b"x")
    target.file("old/dir/stale.txt").write(b"x")
    kept = source.sync_to(target)
    assert kept.deleted == []
    assert target.exists("stale.txt") is True
    removed = source.sync_to(target, delete=True)
    assert removed.deleted == ["old/dir/stale.txt", "stale.txt", "old/dir", "old"]
    assert _files(target) == _files(source)
    assert target.exists("old") is False
    assert target.exists("empty") is True


def test_a_dry_run_changes_nothing(source: Storage, resolver: StorageResolver) -> None:
    target = Storage("memory://two/dst", resolver=resolver)
    target.file("stale.txt").write(b"x")
    preview = source.sync_to(target, delete=True, dry_run=True)
    assert preview.dry_run is True
    assert preview.copied == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]
    assert preview.deleted == ["stale.txt"]
    assert _files(target) == {"stale.txt": b"x"}
    assert target.exists("empty") is False
    assert preview.to_dict()["dry_run"] is True


def test_a_failing_file_is_recorded_and_the_rest_still_run(
    source: Storage, resolver: StorageResolver
) -> None:
    target = Storage("memory://two/dst", resolver=resolver)
    target.file("sub/b.txt/blocker").write(b"x")
    result = source.copy_to(target)
    assert result.copied == ["a.txt", "sub/deep/c.txt"]
    assert list(result.errors) == ["sub/b.txt"]
    assert result.errors["sub/b.txt"].startswith("StoragePathTypeException:")
    assert result.ok is False
    assert target.file("a.txt").read() == b"a"
