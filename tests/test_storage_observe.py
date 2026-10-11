"""Storage observers: what each backend operation reports."""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file.exceptions import (
    StorageAlreadyExistsException,
    StorageNotFoundException,
    StorageURIException,
)
from automation_file.storage import LocalStorage, MemoryStorage, observe
from automation_file.storage.observe import StorageOperation


@pytest.fixture
def seen() -> Iterator[list[StorageOperation]]:
    operations: list[StorageOperation] = []
    observe.add_listener(operations.append)
    yield operations
    observe.remove_listener(operations.append)


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage("observed")


def _summary(operations: list[StorageOperation]) -> list[tuple[str, str, str]]:
    return [(entry.operation, entry.uri, entry.status) for entry in operations]


def test_each_operation_is_reported_once(
    storage: MemoryStorage, seen: list[StorageOperation], tmp_path: Path
) -> None:
    storage.write_bytes("dir/a.txt", b"hello")
    storage.read_bytes("dir/a.txt")
    with storage.open_read("dir/a.txt") as stream:
        stream.read()
    storage.download("dir/a.txt", tmp_path / "a.txt")
    storage.mkdir("empty")
    storage.delete("empty")
    with storage.open_write("dir/b.txt") as stream:
        stream.write(b"x")
    assert _summary(seen) == [
        ("upload", "memory://observed/dir/a.txt", "ok"),
        ("read", "memory://observed/dir/a.txt", "ok"),
        ("read", "memory://observed/dir/a.txt", "ok"),
        ("download", "memory://observed/dir/a.txt", "ok"),
        ("mkdir", "memory://observed/empty", "ok"),
        ("delete", "memory://observed/empty", "ok"),
        ("upload", "memory://observed/dir/b.txt", "ok"),
    ]
    assert all(entry.backend == "memory" and entry.ok for entry in seen)
    assert all(entry.duration_ms >= 0 for entry in seen)
    assert all(entry.error is None and entry.error_type is None for entry in seen)


def test_lookups_are_not_reported(storage: MemoryStorage, seen: list[StorageOperation]) -> None:
    storage.write_bytes("a.txt", b"x")
    seen.clear()
    storage.exists("a.txt")
    storage.stat("a.txt")
    storage.list_dir("")
    storage.checksum("a.txt")
    assert seen == []


def test_a_copy_or_a_move_is_one_operation(
    storage: MemoryStorage, seen: list[StorageOperation], tmp_path: Path
) -> None:
    storage.write_bytes("a.txt", b"x")
    local = LocalStorage(tmp_path)
    seen.clear()
    local.copy_from(storage, "a.txt", "copy.txt")
    storage.move_from(local, "copy.txt", "back.txt")
    assert [(entry.operation, entry.backend, entry.status) for entry in seen] == [
        ("copy", "local", "ok"),
        ("move", "memory", "ok"),
    ]
    assert seen[0].source_uri == "memory://observed/a.txt"
    assert seen[0].uri == local.uri_for("copy.txt")
    assert seen[1].source_uri == local.uri_for("copy.txt")
    assert seen[1].uri == "memory://observed/back.txt"


def test_a_failure_is_reported_with_its_error(
    storage: MemoryStorage, seen: list[StorageOperation]
) -> None:
    with pytest.raises(StorageNotFoundException):
        storage.read_bytes("nope.txt")
    storage.write_bytes("a.txt", b"x")
    with pytest.raises(StorageAlreadyExistsException):
        storage.write_bytes("a.txt", b"y", overwrite=False)
    failures = [entry for entry in seen if not entry.ok]
    assert [(entry.operation, entry.error_type) for entry in failures] == [
        ("read", "StorageNotFoundException"),
        ("upload", "StorageAlreadyExistsException"),
    ]
    assert failures[0].error is not None
    assert failures[0].error.startswith("StorageNotFoundException: ")
    assert failures[0].status == "error"


def test_an_invalid_path_is_still_reported(
    storage: MemoryStorage, seen: list[StorageOperation]
) -> None:
    with pytest.raises(StorageURIException):
        storage.delete("../escape")
    assert _summary(seen) == [("delete", "memory:../escape", "error")]


def test_a_failing_observer_does_not_fail_the_operation(storage: MemoryStorage) -> None:
    def broken(_operation: StorageOperation) -> None:
        raise RuntimeError("observer bug")

    observe.add_listener(broken)
    try:
        assert storage.write_bytes("a.txt", b"x").size == 1
    finally:
        assert observe.remove_listener(broken) is True
    assert observe.remove_listener(broken) is False


def test_listeners_are_registered_once_and_must_be_callable() -> None:
    calls: list[StorageOperation] = []
    observe.add_listener(calls.append)
    observe.add_listener(calls.append)
    try:
        MemoryStorage("once").write_bytes("a.txt", b"x")
    finally:
        observe.remove_listener(calls.append)
    assert len(calls) == 1
    with pytest.raises(TypeError):
        observe.add_listener("nope")  # type: ignore[arg-type]


def test_suppressed_hides_the_operations_inside(
    storage: MemoryStorage, seen: list[StorageOperation]
) -> None:
    with observe.suppressed():
        storage.write_bytes("a.txt", b"x")
    storage.write_bytes("b.txt", b"x")
    assert _summary(seen) == [("upload", "memory://observed/b.txt", "ok")]


def test_to_dict() -> None:
    operation = StorageOperation("upload", "memory://x/a", "memory", "ok", 1.5)
    assert operation.to_dict() == {
        "operation": "upload",
        "uri": "memory://x/a",
        "backend": "memory",
        "status": "ok",
        "duration_ms": 1.5,
        "source_uri": None,
        "error": None,
        "error_type": None,
    }
