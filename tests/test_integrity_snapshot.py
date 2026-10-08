"""Snapshots, the manifest schema and the hash engine."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import stat
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from automation_file.core.manifest import write_manifest
from automation_file.integrity import (
    MANIFEST_SCHEMA_VERSION,
    HashEngine,
    IntegrityException,
    Snapshot,
    SnapshotEntry,
    Target,
    build_snapshot,
    dump_manifest,
    from_manifest,
    load_manifest,
    to_manifest,
)
from automation_file.integrity.hashing import checked_algorithm
from automation_file.integrity.snapshot import quick_matches
from automation_file.storage import FileInfo, Storage, clear_memory_stores

TREE = "memory://snap/tree"
FILES = {"a.txt": b"alpha", "sub/b.bin": b"bravo!", "sub/deep/c.txt": b""}
MOMENT = datetime(2026, 10, 8, 10, 15, 30, 123456, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


def _write(uri: str, files: dict[str, bytes]) -> Storage:
    storage = Storage(uri)
    for path, data in files.items():
        storage.file(path).write(data)
    return storage


def _snapshot(uri: str = TREE, algorithm: str = "sha256") -> Snapshot:
    target = Target(uri)
    return build_snapshot(target, HashEngine(algorithm), target.files())


def _entry(path: str = "a.txt", **fields: Any) -> SnapshotEntry:
    return SnapshotEntry(path=path, **fields)


# ---------------------------------------------------------------------- snapshot contents


def test_a_snapshot_lists_every_file_with_what_the_backend_reports() -> None:
    storage = _write(TREE, FILES)
    storage.mkdir("empty")
    before = datetime.now(timezone.utc) - timedelta(seconds=5)
    snapshot = _snapshot()
    assert snapshot.root == TREE
    assert snapshot.backend == "memory"
    assert snapshot.algorithm == "sha256"
    assert snapshot.created_at.utcoffset() == timedelta(0)
    assert snapshot.paths == ("a.txt", "sub/b.bin", "sub/deep/c.txt")
    assert len(snapshot) == 3
    assert "a.txt" in snapshot and "empty" not in snapshot
    entry = snapshot.get("sub/b.bin")
    assert entry is not None
    assert entry.size == 6
    assert entry.checksum == hashlib.sha256(b"bravo!").hexdigest()
    assert entry.algorithm == "sha256"
    assert entry.backend == "memory"
    assert entry.modified_at is not None and entry.modified_at > before
    assert entry.modified_at.utcoffset() == timedelta(0)
    assert (entry.content_type, entry.version, entry.etag, entry.mode) == (None, None, None, None)
    assert snapshot.get("nope.txt") is None


def test_a_local_snapshot_records_permission_bits_and_content_type(tmp_path: Path) -> None:
    (tmp_path / "tree" / "sub").mkdir(parents=True)
    (tmp_path / "tree" / "a.txt").write_bytes(b"alpha")
    (tmp_path / "tree" / "sub" / "data").write_bytes(b"\x00\x01")
    snapshot = _snapshot(str(tmp_path / "tree"))
    assert snapshot.root.startswith("local:///")
    assert snapshot.backend == "local"
    entry = snapshot.get("a.txt")
    assert entry is not None
    assert entry.mode == stat.S_IMODE(os.stat(tmp_path / "tree" / "a.txt").st_mode)
    assert entry.content_type == "text/plain"
    assert entry.backend == "local"
    nested = snapshot.get("sub/data")
    assert nested is not None
    assert (nested.content_type, nested.size) == (None, 2)
    assert nested.mode is not None


def test_a_file_that_vanishes_while_the_snapshot_is_taken_is_left_out() -> None:
    _write(TREE, {"a.txt": b"alpha"})
    target = Target(TREE)
    listed = [*target.files(), FileInfo(path="gone.txt", size=4, modified_at=MOMENT)]
    snapshot = build_snapshot(target, HashEngine(), listed)
    assert snapshot.paths == ("a.txt",)


def test_a_known_entry_keeps_its_checksum_instead_of_being_hashed() -> None:
    _write(TREE, {"a.txt": b"alpha", "b.txt": b"bravo"})
    target = Target(TREE)
    carried = _entry("a.txt", checksum="carried-over", content_type="text/x-kept", version="v7")
    snapshot = build_snapshot(target, HashEngine(), target.files(), known={"a.txt": carried})
    first, second = snapshot.entries
    assert (first.checksum, first.content_type, first.version) == (
        "carried-over",
        "text/x-kept",
        "v7",
    )
    assert second.checksum == hashlib.sha256(b"bravo").hexdigest()


def test_quick_matches_trusts_only_an_identical_stamp() -> None:
    baseline = Snapshot(
        root=TREE,
        entries=(
            _entry("same.txt", size=5, modified_at=MOMENT, checksum="1"),
            _entry("resized.txt", size=5, modified_at=MOMENT, checksum="2"),
            _entry("touched.txt", size=5, modified_at=MOMENT, checksum="3"),
            _entry("retagged.txt", size=5, modified_at=MOMENT, etag="old", checksum="4"),
            _entry("legacy.txt", size=5, checksum="5"),
            _entry("etag-only.txt", size=5, etag="tag", checksum="6"),
        ),
    )
    listed = [
        FileInfo(path="same.txt", size=5, modified_at=MOMENT),
        FileInfo(path="resized.txt", size=6, modified_at=MOMENT),
        FileInfo(path="touched.txt", size=5, modified_at=MOMENT + timedelta(seconds=1)),
        FileInfo(path="retagged.txt", size=5, modified_at=MOMENT, etag="new"),
        FileInfo(path="legacy.txt", size=5),
        FileInfo(path="etag-only.txt", size=5, etag="tag"),
        FileInfo(path="new.txt", size=5, modified_at=MOMENT),
    ]
    assert sorted(quick_matches(listed, baseline)) == ["etag-only.txt", "same.txt"]


def test_quick_matches_compares_instants_not_time_zones() -> None:
    baseline = Snapshot(
        root=TREE, entries=(_entry("a.txt", size=1, modified_at=MOMENT, checksum="1"),)
    )
    elsewhere = MOMENT.astimezone(timezone(timedelta(hours=8)))
    naive = MOMENT.replace(tzinfo=None)
    assert list(quick_matches([FileInfo(path="a.txt", size=1, modified_at=elsewhere)], baseline))
    assert list(quick_matches([FileInfo(path="a.txt", size=1, modified_at=naive)], baseline))


# ---------------------------------------------------------------------- value types


def test_an_entry_round_trips_through_json() -> None:
    entry = SnapshotEntry(
        path="報告/q1 ✓.csv",
        size=1024,
        modified_at=MOMENT,
        checksum="9f86d0",
        algorithm="sha512",
        content_type="text/csv",
        backend="s3",
        version="v3",
        etag="5d41",
        mode=0o640,
    )
    document = json.loads(json.dumps(entry.to_dict()))
    assert document["modified_at"] == "2026-10-08T10:15:30.123456+00:00"
    assert document["mode"] == 0o640
    assert list(document) == [
        "path",
        "size",
        "modified_at",
        "checksum",
        "algorithm",
        "content_type",
        "backend",
        "version",
        "etag",
        "mode",
    ]
    assert SnapshotEntry.from_dict(document) == entry


def test_from_dict_fills_the_gaps_and_reads_a_z_suffix() -> None:
    entry = SnapshotEntry.from_dict(
        {"path": "a.txt", "checksum": " ABC ", "modified_at": "2026-10-08T10:15:30Z"},
        algorithm="blake2b",
        backend="memory",
    )
    assert (entry.algorithm, entry.backend, entry.checksum) == ("blake2b", "memory", "abc")
    assert entry.modified_at == datetime(2026, 10, 8, 10, 15, 30, tzinfo=timezone.utc)
    assert (entry.size, entry.mode, entry.etag) == (None, None, None)


@pytest.mark.parametrize(
    "document",
    [
        "not an object",
        {},
        {"path": ""},
        {"path": 7},
        {"path": "../outside.txt"},
        {"path": "a/../../outside.txt"},
        {"path": "a.txt", "size": -1},
        {"path": "a.txt", "size": True},
        {"path": "a.txt", "size": "12"},
        {"path": "a.txt", "checksum": 12},
        {"path": "a.txt", "mode": "0644"},
        {"path": "a.txt", "modified_at": "yesterday"},
        {"path": "a.txt", "modified_at": 1728382530},
    ],
)
def test_from_dict_rejects_a_malformed_entry(document: Any) -> None:
    with pytest.raises(IntegrityException):
        SnapshotEntry.from_dict(document)


def test_a_snapshot_is_frozen_sorted_and_refuses_a_duplicate_path() -> None:
    snapshot = Snapshot(root=TREE, entries=(_entry("b.txt"), _entry("a.txt")))
    assert snapshot.paths == ("a.txt", "b.txt")
    assert [entry.path for entry in snapshot] == ["a.txt", "b.txt"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.root = "elsewhere"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.entries[0].size = 3  # type: ignore[misc]
    with pytest.raises(IntegrityException, match="more than once"):
        Snapshot(root=TREE, entries=(_entry("a.txt"), _entry("a.txt")))


def test_below_returns_a_path_and_everything_under_it() -> None:
    paths = ["a", "a.txt", "a/x.txt", "a/y/z.txt", "a0", "ab/c.txt", "b/a/x.txt"]
    snapshot = Snapshot(root=TREE, entries=tuple(_entry(path) for path in paths))
    assert [entry.path for entry in snapshot.below("a")] == ["a", "a/x.txt", "a/y/z.txt"]
    assert [entry.path for entry in snapshot.below("a/y")] == ["a/y/z.txt"]
    assert [entry.path for entry in snapshot.below("a.txt")] == ["a.txt"]
    assert snapshot.below("nope") == ()
    assert snapshot.below("") == snapshot.entries


def test_merged_replaces_removes_and_adds() -> None:
    snapshot = Snapshot(
        root="old", entries=(_entry("a.txt", checksum="1"), _entry("b.txt", checksum="2"))
    )
    merged = snapshot.merged(
        removed=["a.txt", "b.txt"],
        added=[_entry("b.txt", checksum="3"), _entry("c.txt", checksum="4")],
        root=TREE,
        backend="memory",
    )
    assert (merged.root, merged.backend) == (TREE, "memory")
    assert [(entry.path, entry.checksum) for entry in merged] == [("b.txt", "3"), ("c.txt", "4")]


# ---------------------------------------------------------------------- manifest


def test_a_manifest_round_trips() -> None:
    _write(TREE, FILES)
    snapshot = _snapshot()
    document = to_manifest(snapshot)
    assert list(document) == [
        "schema_version",
        "created_at",
        "root",
        "backend",
        "algorithm",
        "entries",
    ]
    assert document["schema_version"] == MANIFEST_SCHEMA_VERSION == 2
    assert [entry["path"] for entry in document["entries"]] == list(snapshot.paths)
    assert from_manifest(json.loads(json.dumps(document))) == snapshot
    encoded = dump_manifest(snapshot)
    assert isinstance(encoded, bytes)
    assert load_manifest(encoded) == snapshot
    assert load_manifest(encoded.decode("utf-8")) == snapshot
    assert Snapshot.from_dict(snapshot.to_dict()) == snapshot


def test_a_manifest_keeps_non_ascii_paths_readable() -> None:
    _write(TREE, {"報告/q1 ✓.csv": b"x"})
    encoded = dump_manifest(_snapshot())
    assert "報告/q1 ✓.csv" in encoded.decode("utf-8")
    assert load_manifest(encoded).paths == ("報告/q1 ✓.csv",)


def test_the_legacy_manifest_format_is_converted(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "nested").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"alpha")
    (root / "nested" / "b.txt").write_bytes(b"bravo")
    legacy = write_manifest(root, tmp_path / "manifest.json")
    assert "schema_version" not in legacy
    snapshot = load_manifest((tmp_path / "manifest.json").read_bytes())
    assert snapshot.paths == ("a.txt", "nested/b.txt")
    assert snapshot.algorithm == "sha256"
    assert snapshot.backend == "local"
    assert snapshot.root == _snapshot(str(root)).root
    assert snapshot.created_at == datetime.fromisoformat(legacy["created_at"])
    entry = snapshot.get("nested/b.txt")
    assert entry is not None
    assert (entry.size, entry.checksum) == (5, hashlib.sha256(b"bravo").hexdigest())
    assert (entry.modified_at, entry.mode, entry.algorithm) == (None, None, "sha256")
    assert to_manifest(snapshot)["schema_version"] == 2


def test_a_legacy_entry_without_a_checksum_is_kept_without_one() -> None:
    snapshot = from_manifest({"files": {"a.txt": {"size": "big"}, "b.txt": None}})
    assert [(entry.path, entry.size, entry.checksum) for entry in snapshot] == [
        ("a.txt", None, ""),
        ("b.txt", None, ""),
    ]
    assert snapshot.root == ""


@pytest.mark.parametrize("version", [1, 3, "2", 2.5, None, True])
def test_an_unknown_schema_version_is_refused(version: Any) -> None:
    document = {"schema_version": version, "entries": [], "root": TREE, "algorithm": "sha256"}
    with pytest.raises(IntegrityException, match="schema version"):
        from_manifest(document, origin="baseline memory://b/m.json")


def test_a_legacy_manifest_of_an_unknown_version_is_refused() -> None:
    with pytest.raises(IntegrityException, match="legacy manifest of version 4"):
        from_manifest({"version": 4, "files": {}})


@pytest.mark.parametrize(
    "document",
    [
        [],
        "text",
        {"version": 1},
        {"files": ["a.txt"]},
        {"schema_version": 2},
        {"schema_version": 2, "entries": {"a.txt": {}}},
        {"schema_version": 2, "entries": [{"path": "../x"}]},
        {"schema_version": 2, "entries": [{"path": "a"}, {"path": "a"}]},
        {"schema_version": 2, "entries": [], "created_at": "soon"},
        {"files": {"../x": {"size": 1, "checksum": "ab"}}},
    ],
)
def test_a_document_that_is_not_a_manifest_is_refused(document: Any) -> None:
    with pytest.raises(IntegrityException, match="the baseline"):
        from_manifest(document, origin="the baseline")


@pytest.mark.parametrize("data", [b"{not json", b"\xff\xfe\x00", ""])
def test_unreadable_json_is_refused(data: bytes | str) -> None:
    with pytest.raises(IntegrityException, match="not readable JSON"):
        load_manifest(data)


# ---------------------------------------------------------------------- hash engine


@pytest.mark.parametrize("algorithm", ["sha256", "sha512", "blake2b"])
def test_the_strong_algorithms_hash_through_the_storage_layer(algorithm: str) -> None:
    storage = _write(TREE, FILES)
    engine = HashEngine(algorithm.upper())
    assert engine.algorithm == algorithm
    assert engine.hash_many(storage, FILES) == {
        path: hashlib.new(algorithm, data).hexdigest() for path, data in FILES.items()
    }
    assert {entry.algorithm for entry in _snapshot(algorithm=algorithm)} == {algorithm}


@pytest.mark.parametrize("algorithm", ["md5", "MD5", "sha1"])
def test_a_weak_algorithm_is_refused_with_the_reason(algorithm: str) -> None:
    with pytest.raises(IntegrityException) as refusal:
        HashEngine(algorithm)
    message = str(refusal.value)
    assert "not collision-resistant" in message
    assert "allow_weak=True" in message
    assert "sha256" in message


def test_a_weak_algorithm_works_when_explicitly_allowed() -> None:
    storage = _write(TREE, {"a.txt": b"alpha"})
    engine = HashEngine("md5", allow_weak=True)
    assert engine.algorithm == "md5"
    assert engine.hash_file(storage, "a.txt") == (
        hashlib.md5(b"alpha", usedforsecurity=False).hexdigest()
    )


@pytest.mark.parametrize("algorithm", ["sha384", "crc32", "", "shake_128"])
def test_an_unsupported_algorithm_is_refused_even_when_weak_ones_are_allowed(
    algorithm: str,
) -> None:
    with pytest.raises(IntegrityException, match="unsupported integrity algorithm"):
        checked_algorithm(algorithm, allow_weak=True)


def test_the_default_algorithm_is_sha256() -> None:
    assert HashEngine().algorithm == "sha256"
    with pytest.raises(IntegrityException, match="at least 1"):
        HashEngine(max_workers=0)


def test_a_missing_file_has_no_digest() -> None:
    storage = _write(TREE, {"a.txt": b"alpha"})
    storage.mkdir("folder")
    engine = HashEngine()
    assert engine.hash_file(storage, "nope.txt") is None
    assert engine.hash_file(storage, "folder") is None
    assert list(engine.hash_many(storage, ["a.txt", "nope.txt", "folder"])) == ["a.txt"]


def test_files_are_hashed_in_parallel() -> None:
    together = threading.Barrier(3, timeout=10)

    def work(path: str) -> str:
        together.wait()
        return path.upper()

    # Three calls can only pass the barrier when three threads are inside it at once.
    assert HashEngine(max_workers=3).map(work, ["a", "b", "c"]) == {"a": "A", "b": "B", "c": "C"}


def test_one_worker_hashes_in_the_calling_thread() -> None:
    threads: set[int] = set()

    def work(path: str) -> str:
        threads.add(threading.get_ident())
        return path

    assert list(HashEngine(max_workers=1).map(work, ["a", "b", "a"])) == ["a", "b"]
    assert threads == {threading.get_ident()}


def test_the_first_failure_is_raised() -> None:
    def work(path: str) -> str:
        if path == "bad":
            raise IntegrityException("cannot read bad")
        return path

    with pytest.raises(IntegrityException, match="cannot read bad"):
        HashEngine(max_workers=2).map(work, ["a", "bad", "c", "d"])
