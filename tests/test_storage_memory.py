"""MemoryStorage: the storage contract plus the shared named stores."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from automation_file.storage import (
    MemoryStorage,
    StorageBackend,
    clear_memory_stores,
    memory_store,
)
from tests.storage_contract import StorageContract


class TestMemoryStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return MemoryStorage()


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


def test_uri_for_carries_the_store_name() -> None:
    assert MemoryStorage("scratch").uri_for("a/b.txt") == "memory://scratch/a/b.txt"
    assert MemoryStorage("scratch").uri_for("") == "memory://scratch"
    assert MemoryStorage().uri_for("a.txt") == "memory:///a.txt"
    assert MemoryStorage("scratch").name == "scratch"


def test_named_stores_are_shared_and_separate() -> None:
    first = memory_store("one")
    first.write_bytes("a.txt", b"x")
    assert memory_store("one") is first
    assert memory_store("one").read_bytes("a.txt") == b"x"
    assert memory_store("two").exists("a.txt") is False


def test_clear_memory_stores_forgets_everything() -> None:
    memory_store("one").write_bytes("a.txt", b"x")
    clear_memory_stores()
    assert memory_store("one").exists("a.txt") is False


def test_two_instances_do_not_share_content() -> None:
    first, second = MemoryStorage(), MemoryStorage()
    first.write_bytes("a.txt", b"x")
    assert second.exists("a.txt") is False
    second.copy_from(first, "a.txt", "copy.txt")
    assert second.read_bytes("copy.txt") == b"x"
