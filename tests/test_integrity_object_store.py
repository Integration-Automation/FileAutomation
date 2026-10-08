"""The monitor on an object store: etags, versions, an emptied prefix, and polling.

``_Bucket`` is an in-memory :class:`ObjectStorage` that behaves like S3 where it
matters here: a listing reports size, time and etag, and only a ``HEAD`` adds
the version and the content type. It counts its reads, so the tests can tell a
quick pass from a deep one.
"""

# The nosec / nosemgrep markers below sit on made-up values and on digests that are the thing
# under test; none is a credential or a security use of a hash.
# pylint: disable=line-too-long  # a marker has to follow the value it is about

# pylint: disable=consider-using-with  # the handle is closed by the code under test
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=unused-argument  # a fixture is requested for its effect; a stand-in keeps the real signature

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from automation_file.events import Event, EventBus, IntegrityViolation
from automation_file.integrity import IntegrityMonitor
from automation_file.storage import (
    FileInfo,
    ObjectStorage,
    Storage,
    StorageCapabilities,
    StorageResolver,
    clear_memory_stores,
)

TARGET = "bucket://reports/2026"
BASELINE = "memory://baselines/reports.json"
WAIT = 10.0


@dataclass
class _Object:
    data: bytes
    modified: datetime
    version: str


class _Bucket(ObjectStorage):
    scheme = "bucket"
    capabilities = StorageCapabilities(
        directories=False, modified_at=True, etag=True, version=True, content_type=True
    )

    def __init__(self) -> None:
        super().__init__()
        self.objects: dict[str, _Object] = {}
        self.downloads: list[str] = []
        self.heads: list[str] = []
        self.listings = threading.Semaphore(0)
        self._clock = datetime(2026, 10, 8, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def uri_for(self, path: str = "") -> str:
        return f"bucket://reports/{self._normalize(path)}"

    def _head(self, key: str) -> FileInfo | None:
        with self._lock:
            item = self.objects.get(key)
            self.heads.append(key)
        if item is None:
            return None
        return FileInfo(
            path=key,
            size=len(item.data),
            # An HTTP Last-Modified header carries whole seconds; the listing has the stored time.
            modified_at=item.modified.replace(microsecond=0),
            etag=hashlib.md5(item.data, usedforsecurity=False).hexdigest(),  # nosec B324  # nosemgrep
            version=item.version,
            content_type="text/csv" if key.endswith(".csv") else "application/octet-stream",
        )

    def _scan(self, key_prefix: str, *, shallow: bool) -> Iterable[FileInfo]:
        found: list[FileInfo] = []
        prefixes: set[str] = set()
        with self._lock:
            items = sorted(self.objects.items())
        for key, item in items:
            if not key.startswith(key_prefix):
                continue
            rest = key[len(key_prefix) :]
            if shallow and "/" in rest:
                prefixes.add(key_prefix + rest.split("/", 1)[0])
                continue
            found.append(
                FileInfo(
                    path=key,
                    size=len(item.data),
                    modified_at=item.modified,
                    etag=hashlib.md5(item.data, usedforsecurity=False).hexdigest(),  # nosec B324  # nosemgrep
                )
            )
        if not shallow:
            self.listings.release()
        return [*(FileInfo(path=prefix, is_dir=True) for prefix in sorted(prefixes)), *found]

    def _put(self, source: Path, key: str) -> None:
        with self._lock:
            self._clock += timedelta(seconds=1, microseconds=250_000)
            generation = int(self.objects[key].version[1:]) + 1 if key in self.objects else 1
            self.objects[key] = _Object(source.read_bytes(), self._clock, f"v{generation}")

    def _get(self, key: str, target: Path) -> None:
        with self._lock:
            self.downloads.append(key)
            data = self.objects[key].data
        target.write_bytes(data)

    def _remove(self, key: str) -> None:
        with self._lock:
            self.objects.pop(key, None)


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


@pytest.fixture
def bucket() -> _Bucket:
    return _Bucket()


@pytest.fixture
def resolver(bucket: _Bucket) -> StorageResolver:
    table = StorageResolver()
    table.mount("bucket://reports", bucket)
    return table


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def reports(resolver: StorageResolver) -> Storage:
    storage = Storage(TARGET, resolver=resolver)
    storage.file("q1.csv").write(b"region,total\nEMEA,42\n")
    storage.file("q2.csv").write(b"region,total\nEMEA,43\n")
    storage.file("raw/dump.bin").write(b"\x00\x01\x02")
    return storage


@pytest.fixture
def monitor(reports: Storage, resolver: StorageResolver, bus: EventBus) -> IntegrityMonitor:
    watching = IntegrityMonitor(TARGET, baseline=BASELINE, resolver=resolver, bus=bus)
    watching.create_baseline()
    return watching


def test_a_snapshot_takes_the_etag_from_the_listing_and_the_rest_from_a_head(
    monitor: IntegrityMonitor, bucket: _Bucket
) -> None:
    bucket.heads.clear()
    snapshot = monitor.snapshot()
    assert (snapshot.root, snapshot.backend) == (TARGET, "bucket")
    assert snapshot.paths == ("q1.csv", "q2.csv", "raw/dump.bin")
    entry = snapshot.get("q1.csv")
    assert entry is not None
    assert entry.checksum == hashlib.sha256(b"region,total\nEMEA,42\n").hexdigest()
    assert entry.etag == hashlib.md5(b"region,total\nEMEA,42\n", usedforsecurity=False).hexdigest()  # nosec B324  # nosemgrep
    assert (entry.version, entry.content_type, entry.backend, entry.mode) == (
        "v1",
        "text/csv",
        "bucket",
        None,
    )
    assert entry.modified_at == bucket.objects["2026/q1.csv"].modified
    assert sorted(bucket.heads).count("2026/q1.csv") >= 1


def test_a_quick_pass_downloads_nothing_while_the_listing_matches(
    monitor: IntegrityMonitor, reports: Storage, bucket: _Bucket
) -> None:
    bucket.downloads.clear()
    quick = monitor.verify(deep=False)
    assert (quick.ok, quick.deep, quick.checked, quick.hashed) == (True, False, 3, 0)
    assert bucket.downloads == []
    assert monitor.verify().hashed == 3
    assert sorted(bucket.downloads) == ["2026/q1.csv", "2026/q2.csv", "2026/raw/dump.bin"]

    bucket.downloads.clear()
    reports.file("q2.csv").write(b"region,total\nEMEA,99\n")
    quick = monitor.verify(deep=False)
    assert quick.paths("modified") == ["q2.csv"]
    assert (quick.hashed, bucket.downloads) == (1, ["2026/q2.csv"])


def test_the_same_content_stored_again_is_a_metadata_change(
    monitor: IntegrityMonitor, reports: Storage
) -> None:
    reports.file("q1.csv").write(b"region,total\nEMEA,42\n")
    for deep in (False, True):
        (change,) = monitor.verify(deep=deep).changes
        assert (change.kind.value, change.path) == ("metadata_changed", "q1.csv")
        assert change.fields == ("modified_at", "version")
    accepted = monitor.accept(monitor.verify(deep=False)).get("q2.csv")
    assert accepted is not None
    assert (accepted.version, accepted.content_type) == ("v1", "text/csv")
    assert monitor.verify(deep=False).ok is True


def test_a_prefix_that_holds_nothing_any_more_is_an_empty_tree(
    monitor: IntegrityMonitor, reports: Storage, bucket: _Bucket
) -> None:
    bucket.objects.clear()
    report = monitor.verify()
    assert report.counts["deleted"] == 3
    assert report.paths("deleted") == ["q1.csv", "q2.csv", "raw/dump.bin"]
    assert monitor.snapshot().paths == ()


def test_a_single_path_is_verified_with_the_listing_view_of_it(
    monitor: IntegrityMonitor, reports: Storage, bucket: _Bucket
) -> None:
    listed = bucket.objects["2026/q1.csv"].modified
    assert reports.stat("q1.csv").modified_at != listed
    clean = monitor.verify_paths(["q1.csv", "raw"])
    assert (clean.ok, clean.partial, clean.checked) == (True, True, 2)
    reports.file("q1.csv").write(b"region,total\nEMEA,0\n")
    bucket.objects.pop("2026/q2.csv")
    report = monitor.verify_paths(["q1.csv", "q2.csv", "raw/dump.bin"])
    assert [(change.kind.value, change.path) for change in report.changes] == [
        ("modified", "q1.csv"),
        ("deleted", "q2.csv"),
    ]


def test_another_backend_is_watched_by_polling_and_reports_a_drift_once(
    monitor: IntegrityMonitor, reports: Storage, bucket: _Bucket, bus: EventBus
) -> None:
    received: list[Event] = []
    arrived = threading.Semaphore(0)

    def _collect(event: Event) -> None:
        received.append(event)
        arrived.release()

    bus.subscribe(_collect, types=IntegrityViolation)
    reports.file("q1.csv").write(b"region,total\nEMEA,0\n")
    with monitor.watch(poll_interval=0.01) as handle:
        assert (handle.kind, handle.is_running) == ("poll", True)
        assert arrived.acquire(timeout=WAIT), "the poll did not report the drift"
        while bucket.listings.acquire(blocking=False):
            pass
        for _ in range(3):
            assert bucket.listings.acquire(timeout=WAIT), "the poll stopped"
        assert len(received) == 1
        reports.file("new.csv").write(b"region,total\n")
        assert arrived.acquire(timeout=WAIT), "the poll did not report the second drift"
    assert handle.is_running is False
    first, second = received
    assert (first.payload["deep"], first.payload["counts"]["modified"]) == (False, 1)
    assert second.payload["counts"]["created"] == 1
    report = monitor.last_report
    assert report is not None
    assert (report.deep, report.partial) == (False, False)
