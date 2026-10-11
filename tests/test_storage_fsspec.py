"""FsspecStorage: the storage contract against real fsspec filesystems.

fsspec ships a memory filesystem and a local one, so the contract runs against
both without a stand-in. A third filesystem written here keeps flat keys the way
an object store does, for the ``directories=False`` mode.
"""

# pylint: disable=arguments-differ  # a fixture or a stand-in takes other arguments than the one it replaces
# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=unidiomatic-typecheck  # the exact class is what is asserted
# pylint: disable=unused-argument  # a fixture is requested for its effect; a stand-in keeps the real signature
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import inspect
import os
import secrets
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

fsspec = pytest.importorskip("fsspec")

# pylint: disable=wrong-import-position  # importorskip must precede these imports
from fsspec import AbstractFileSystem  # noqa: E402
from fsspec.core import url_to_fs  # noqa: E402
from fsspec.implementations.local import LocalFileSystem  # noqa: E402
from fsspec.implementations.memory import MemoryFileSystem  # noqa: E402

from automation_file.exceptions import (  # noqa: E402
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageUnsupportedException,
    StorageURIException,
)
from automation_file.storage import File, StorageBackend, StorageResolver  # noqa: E402
from automation_file.storage import fsspec_storage as fsspec_storage_module  # noqa: E402
from automation_file.storage.fsspec_storage import FSSPEC_SCHEME, FsspecStorage  # noqa: E402
from tests.storage_contract import StorageContract  # noqa: E402

CLOSE_ENOUGH = timedelta(milliseconds=1)


def _wipe_memory_filesystem() -> None:
    """MemoryFileSystem keeps one store per process, files and directories alike."""
    MemoryFileSystem.store.clear()
    MemoryFileSystem.pseudo_dirs[:] = [""]


@pytest.fixture(autouse=True)
def _isolated_memory_filesystem() -> Iterator[None]:
    _wipe_memory_filesystem()
    yield
    _wipe_memory_filesystem()


class KeyValueFileSystem(AbstractFileSystem):
    """Flat keys, as in s3fs or gcsfs: a directory is only a prefix of the keys below it."""

    protocol = "keyvalue"
    cachable = False

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.objects: dict[str, tuple[bytes, datetime]] = {}
        self.calls: list[str] = []

    def _key(self, path: str) -> str:
        return str(self._strip_protocol(path)).strip("/")

    def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
        key = self._key(path)
        if key in self.objects:
            data, modified = self.objects[key]
            return {"name": key, "size": len(data), "type": "file", "LastModified": modified}
        if not key or any(name.startswith(f"{key}/") for name in self.objects):
            return {"name": key, "size": 0, "type": "directory"}
        raise FileNotFoundError(path)

    def ls(self, path: str, detail: bool = True, **kwargs: Any) -> list[Any]:
        key = self._key(path)
        if key in self.objects:
            return [self.info(key)] if detail else [key]
        prefix = f"{key}/" if key else ""
        below = (name[len(prefix) :] for name in self.objects if name.startswith(prefix))
        children = sorted({prefix + rest.split("/", 1)[0] for rest in below})
        if not children and key:
            raise FileNotFoundError(path)
        return [self.info(child) for child in children] if detail else children

    def put_file(self, lpath: str, rpath: str, callback: Any = None, **kwargs: Any) -> None:
        self.calls.append("put_file")
        self.objects[self._key(rpath)] = (Path(lpath).read_bytes(), datetime.now(timezone.utc))

    def get_file(self, rpath: str, lpath: str, callback: Any = None, **kwargs: Any) -> None:
        self.calls.append("get_file")
        Path(lpath).write_bytes(self.cat_file(rpath))

    def cat_file(self, path: str, start: Any = None, end: Any = None, **kwargs: Any) -> bytes:
        key = self._key(path)
        if key not in self.objects:
            raise FileNotFoundError(path)
        return self.objects[key][0][start:end]

    def rm_file(self, path: str) -> None:
        self.calls.append("rm_file")
        key = self._key(path)
        if key not in self.objects:
            raise FileNotFoundError(path)
        del self.objects[key]

    def cp_file(self, path1: str, path2: str, **kwargs: Any) -> None:
        self.calls.append("cp_file")
        self.objects[self._key(path2)] = (self.cat_file(path1), datetime.now(timezone.utc))

    def mkdir(self, path: str, create_parents: bool = True, **kwargs: Any) -> None:
        """A prefix needs no creating."""

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        """A prefix needs no creating."""

    def rmdir(self, path: str) -> None:
        # Like s3fs: a prefix whose keys are gone is not there to remove.
        raise FileNotFoundError(path)

    def modified(self, path: str) -> datetime:
        return self.info(path)["LastModified"]


class TimelessFileSystem(KeyValueFileSystem):
    """A filesystem that knows no modification times, like fsspec's HTTP one."""

    modified = AbstractFileSystem.modified

    def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
        details = super().info(path, **kwargs)
        details.pop("LastModified", None)
        return details


class CopylessFileSystem(KeyValueFileSystem):
    """A filesystem that cannot copy on its own side, like the abstract base."""

    cp_file = AbstractFileSystem.cp_file


class TestMemoryFsspecStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return FsspecStorage(MemoryFileSystem())


class TestRootedMemoryFsspecStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        filesystem = MemoryFileSystem()
        filesystem.makedirs("/team/a")
        filesystem.pipe_file("/other-team/keep.txt", b"keep")
        return FsspecStorage(filesystem, root="team/a")


class TestLocalFsspecStorageContract(StorageContract):
    @pytest.fixture
    def backend(self, tmp_path: Path) -> StorageBackend:
        root = tmp_path / "fsspec-root"
        root.mkdir()
        (tmp_path / "outside.txt").write_bytes(b"outside")
        return FsspecStorage(LocalFileSystem(), root=str(root))


class TestKeyValueFsspecStorageContract(StorageContract):
    """An object store: ``directories=False`` and a root that is only a key prefix."""

    @pytest.fixture
    def backend(self) -> StorageBackend:
        filesystem = KeyValueFileSystem()
        filesystem.objects["bucket/other-tenant/keep.txt"] = (b"keep", datetime.now(timezone.utc))
        return FsspecStorage(filesystem, root="bucket/tenant/a", directories=False)


@pytest.fixture
def memory() -> FsspecStorage:
    return FsspecStorage(MemoryFileSystem())


@pytest.fixture
def keyvalue() -> FsspecStorage:
    return FsspecStorage(KeyValueFileSystem(), root="bucket", scheme="gcs", directories=False)


def _stored() -> dict[str, bytes]:
    return {name: bytes(item.getbuffer()) for name, item in MemoryFileSystem.store.items()}


# ---------------------------------------------------------------------- stat and listing


def test_stat_takes_the_time_from_info_when_it_is_there(tmp_path: Path) -> None:
    storage = FsspecStorage(LocalFileSystem(), root=str(tmp_path))
    info = storage.write_bytes("dir/a.txt", b"xyz")
    expected = datetime.fromtimestamp(os.stat(tmp_path / "dir" / "a.txt").st_mtime, timezone.utc)
    assert info.size == 3
    assert abs(info.modified_at - expected) < CLOSE_ENOUGH
    assert info.modified_at.utcoffset() == timedelta(0)
    assert (info.etag, info.version, info.content_type) == (None, None, None)
    folder = storage.stat("dir")
    assert (folder.is_dir, folder.size) == (True, None)
    assert folder.modified_at is not None
    assert all(entry.modified_at is not None for entry in storage.list_dir("", recursive=True))


def test_stat_asks_modified_when_info_has_no_time(memory: FsspecStorage) -> None:
    info = memory.write_bytes("dir/a.txt", b"x")
    assert "mtime" not in memory.filesystem.info("/dir/a.txt")
    assert info.modified_at == memory.filesystem.modified("/dir/a.txt")
    assert info.modified_at.utcoffset() == timedelta(0)
    assert memory.stat("dir").modified_at is None
    # A listing stays one call: it carries a time only when the filesystem lists one.
    assert [entry.modified_at for entry in memory.list_dir("dir")] == [None]


def test_a_filesystem_without_times_reports_none() -> None:
    storage = FsspecStorage(TimelessFileSystem(), root="bucket", directories=False)
    assert storage.capabilities.modified_at is False
    info = storage.write_bytes("a.txt", b"x")
    assert (info.size, info.modified_at) == (1, None)


def test_capabilities_and_scheme_belong_to_the_instance(tmp_path: Path) -> None:
    local = FsspecStorage(LocalFileSystem(), root=str(tmp_path))
    store = FsspecStorage(KeyValueFileSystem(), root="bucket", scheme="GCS", directories=False)
    assert (local.scheme, local.capabilities.directories) == (FSSPEC_SCHEME, True)
    assert (store.scheme, store.capabilities.directories) == ("gcs", False)
    assert local.capabilities.modified_at is True
    assert store.capabilities.modified_at is True
    # The instances carry their own; the class keeps the defaults.
    assert FsspecStorage.scheme == FSSPEC_SCHEME == "fsspec"
    assert FsspecStorage.capabilities.directories is True
    with pytest.raises(StorageURIException):
        FsspecStorage(KeyValueFileSystem(), scheme="not a scheme")


AWARE = datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "value,expected",
    [
        (AWARE, AWARE),
        (AWARE.astimezone(timezone(timedelta(hours=8))), AWARE),
        (AWARE.replace(tzinfo=None), AWARE),
        (AWARE.timestamp(), AWARE),
        (int(AWARE.timestamp()), AWARE),
        ("2026-10-08T02:30:00Z", AWARE),
        ("2026-10-08T10:30:00+08:00", AWARE),
        ("2026-10-08T02:30:00.000Z", AWARE),
        ("Thu Oct  8 02:30:00 2026", None),
        ("", None),
        (None, None),
        (True, None),
        (float("nan"), None),
        (1e30, None),
        (b"2026", None),
    ],
)
def test_modification_times_are_read_in_every_usual_form(value: Any, expected: Any) -> None:
    assert fsspec_storage_module._utc(value) == expected


@pytest.mark.parametrize("key", ["mtime", "LastModified", "last_modified", "modified", "updated"])
def test_the_usual_info_keys_are_understood(key: str) -> None:
    assert fsspec_storage_module._listed_time({key: "2026-10-08T02:30:00Z"}) == AWARE
    assert fsspec_storage_module._listed_time({"created": AWARE}) is None


def test_a_placeholder_for_the_directory_itself_is_not_listed(keyvalue: FsspecStorage) -> None:
    filesystem = keyvalue.filesystem
    keyvalue.write_bytes("dir/a.txt", b"x")

    def _with_placeholder(path: str, detail: bool = True, **kwargs: Any) -> list[Any]:
        listing = KeyValueFileSystem.ls(filesystem, path, detail, **kwargs)
        return [{"name": f"{path}/", "size": 0, "type": "directory"}, *listing]

    filesystem.ls = _with_placeholder
    assert [info.path for info in keyvalue.list_dir("dir")] == ["dir/a.txt"]


# ---------------------------------------------------------------------- copy and move


def test_copy_and_move_within_one_filesystem_are_native(keyvalue: FsspecStorage) -> None:
    filesystem = keyvalue.filesystem
    keyvalue.write_bytes("a.txt", b"payload")
    filesystem.calls.clear()
    keyvalue.copy_from(keyvalue, "a.txt", "copies/b.txt")
    assert filesystem.objects["bucket/copies/b.txt"][0] == b"payload"
    assert filesystem.calls == ["cp_file"]
    filesystem.calls.clear()
    other_root = FsspecStorage(filesystem, root="bucket/moved", directories=False)
    other_root.move_from(keyvalue, "a.txt", "c.txt")
    assert sorted(filesystem.objects) == ["bucket/copies/b.txt", "bucket/moved/c.txt"]
    assert not {"get_file", "put_file"} & set(filesystem.calls)


def test_a_local_move_is_a_rename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = FsspecStorage(LocalFileSystem(), root=str(tmp_path))
    storage.write_bytes("a.txt", b"payload")
    storage.write_bytes("moved/b.txt", b"old")
    copies: list[str] = []
    monkeypatch.setattr(LocalFileSystem, "cp_file", lambda *paths, **_options: copies.append("cp"))
    storage.move_from(storage, "a.txt", "moved/b.txt")
    assert copies == []
    assert (tmp_path / "moved" / "b.txt").read_bytes() == b"payload"
    assert not (tmp_path / "a.txt").exists()


def test_names_with_glob_characters_are_taken_literally(memory: FsspecStorage) -> None:
    """fsspec's copy(), mv() and rm() would expand ``report[1].txt`` to ``report1.txt``."""
    memory.write_bytes("report1.txt", b"one")
    memory.write_bytes("report[1].txt", b"bracket")
    memory.write_bytes("dir1/keep.txt", b"keep")
    memory.write_bytes("dir[1]/a?.txt", b"question")
    memory.write_bytes("dir[1]/b*.txt", b"star")
    memory.copy_from(memory, "report[1].txt", "copy.txt")
    assert memory.read_bytes("copy.txt") == b"bracket"
    memory.move_from(memory, "report[1].txt", "moved.txt")
    memory.move_from(memory, "dir[1]/a?.txt", "dir[1]/renamed.txt")
    memory.move_from(memory, "copy.txt", "dir[1]/c[2].txt")
    memory.delete("dir[1]/b*.txt")
    assert _stored() == {
        "/report1.txt": b"one",
        "/moved.txt": b"bracket",
        "/dir1/keep.txt": b"keep",
        "/dir[1]/renamed.txt": b"question",
        "/dir[1]/c[2].txt": b"bracket",
    }
    memory.delete("dir[1]", recursive=True)
    assert _stored() == {
        "/report1.txt": b"one",
        "/moved.txt": b"bracket",
        "/dir1/keep.txt": b"keep",
    }
    assert [info.path for info in memory.list_dir("")] == ["dir1", "moved.txt", "report1.txt"]


def test_a_filesystem_that_cannot_copy_gets_a_staged_transfer() -> None:
    filesystem = CopylessFileSystem()
    storage = FsspecStorage(filesystem, root="bucket", directories=False)
    storage.write_bytes("a.txt", b"payload")
    filesystem.calls.clear()
    storage.copy_from(storage, "a.txt", "b.txt")
    assert filesystem.objects["bucket/b.txt"][0] == b"payload"
    assert filesystem.calls == ["get_file", "put_file"]
    storage.move_from(storage, "a.txt", "c.txt")
    assert sorted(filesystem.objects) == ["bucket/b.txt", "bucket/c.txt"]


def test_two_filesystem_objects_do_not_share_a_native_copy() -> None:
    first = FsspecStorage(KeyValueFileSystem(), root="bucket", directories=False)
    second = FsspecStorage(KeyValueFileSystem(), root="bucket", directories=False)
    first.write_bytes("a.txt", b"payload")
    second.copy_from(first, "a.txt", "a.txt")
    assert second.filesystem.objects["bucket/a.txt"][0] == b"payload"
    assert "cp_file" not in second.filesystem.calls
    assert first != second


def test_copy_from_another_backend(memory: FsspecStorage, tmp_path: Path) -> None:
    local = FsspecStorage(LocalFileSystem(), root=str(tmp_path))
    local.write_bytes("a.txt", b"payload")
    memory.move_from(local, "a.txt", "in/memory.txt")
    assert _stored() == {"/in/memory.txt": b"payload"}
    assert not (tmp_path / "a.txt").exists()


# ---------------------------------------------------------------------- errors


class _DriverError(Exception):
    """What a client library behind a filesystem might raise."""


@pytest.mark.parametrize(
    "error,expected",
    [
        (PermissionError(13, "denied"), StoragePermissionException),
        (ConnectionResetError(104, "reset"), StorageTransientException),
        (TimeoutError("timed out"), StorageTransientException),
        (NotImplementedError(), StorageUnsupportedException),
        (ImportError("Install s3fs to access S3"), StorageUnavailableException),
        (OSError("disk on fire"), StorageException),
        (ValueError("bad argument"), StorageException),
        (_DriverError("client library error"), StorageException),
    ],
)
def test_filesystem_errors_become_storage_errors(
    keyvalue: FsspecStorage, error: Exception, expected: type[Exception]
) -> None:
    def _fail(*_arguments: Any, **_options: Any) -> None:
        raise error

    keyvalue.write_bytes("a.txt", b"x")
    for method in ("info", "ls", "cat_file", "rm_file", "put_file", "get_file"):
        setattr(keyvalue.filesystem, method, _fail)
    with pytest.raises(expected) as caught:
        keyvalue.stat("a.txt")
    assert type(caught.value) is expected
    assert caught.value.__cause__ is error
    with pytest.raises(expected):
        keyvalue._list_dir("")
    with pytest.raises(expected):
        keyvalue._read_bytes("a.txt")
    with pytest.raises(expected):
        keyvalue._delete_file("a.txt")


def test_a_missing_path_is_none_not_an_error(keyvalue: FsspecStorage, tmp_path: Path) -> None:
    assert keyvalue.exists("nope.txt") is False
    with pytest.raises(StorageNotFoundException):
        keyvalue._delete_file("nope.txt")
    local = FsspecStorage(LocalFileSystem(), root=str(tmp_path / "no-such-directory"))
    assert local.exists("") is False
    with pytest.raises(StorageNotFoundException):
        local.list_dir("")
    # Only a root that is a key prefix lists as empty when nothing is below it.
    with pytest.raises(StorageNotFoundException):
        local._list_dir("")
    assert list(keyvalue._list_dir("")) == []
    with pytest.raises(StorageNotFoundException):
        keyvalue._list_dir("nope")


def test_a_directory_that_was_only_implied_goes_with_its_last_file(memory: FsspecStorage) -> None:
    """Written behind the adapter's back, these directories were never created as such."""
    memory.filesystem.pipe_file("/implied/sub/a.txt", b"x")
    memory.filesystem.pipe_file("/keep.txt", b"keep")
    assert memory.stat("implied/sub").is_dir is True
    memory.delete("implied", recursive=True)
    assert memory.exists("implied") is False
    assert _stored() == {"/keep.txt": b"keep"}


def test_a_read_only_filesystem_refuses_a_write(keyvalue: FsspecStorage) -> None:
    def _read_only(*_arguments: Any, **_options: Any) -> None:
        raise NotImplementedError

    keyvalue.filesystem.put_file = _read_only
    with pytest.raises(StorageUnsupportedException):
        keyvalue.write_bytes("a.txt", b"x")
    assert keyvalue.exists("a.txt") is False


@pytest.mark.parametrize("path", ["a\\..\\..\\secret.txt", "..\\secret.txt", "dir/..\\..\\x"])
def test_a_backslash_cannot_smuggle_a_parent_segment(tmp_path: Path, path: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "secret.txt").write_bytes(b"secret")
    storage = FsspecStorage(LocalFileSystem(), root=str(root))
    with pytest.raises(StorageURIException):
        storage.exists(path)
    with pytest.raises(StorageURIException):
        storage.write_bytes(path, b"overwritten")
    assert (tmp_path / "secret.txt").read_bytes() == b"secret"


def test_a_backslash_is_otherwise_part_of_the_name(keyvalue: FsspecStorage) -> None:
    keyvalue.write_bytes("dir/a\\b.txt", b"x")
    assert sorted(keyvalue.filesystem.objects) == ["bucket/dir/a\\b.txt"]


# ---------------------------------------------------------------------- from_url, mounting


def test_from_url_roots_the_storage_at_the_path_of_the_url() -> None:
    storage = FsspecStorage.from_url("memory://jobs/2026/")
    assert isinstance(storage.filesystem, MemoryFileSystem)
    assert (storage.root, storage.scheme) == ("/jobs/2026", "memory")
    assert storage.capabilities.directories is True
    storage.write_bytes("a.txt", b"x")
    assert _stored() == {"/jobs/2026/a.txt": b"x"}
    assert storage.uri_for("a.txt") == "memory:///jobs/2026/a.txt"
    whole = FsspecStorage.from_url("memory://", directories=False)
    assert (whole.root, whole.capabilities.directories) == ("/", False)
    assert whole.read_bytes("jobs/2026/a.txt") == b"x"


def test_from_url_passes_storage_options_to_the_filesystem(tmp_path: Path) -> None:
    storage = FsspecStorage.from_url(f"file://{tmp_path.as_posix()}", auto_mkdir=True)
    assert isinstance(storage.filesystem, LocalFileSystem)
    assert storage.filesystem.auto_mkdir is True
    assert storage.scheme == "local"
    assert Path(storage.root) == tmp_path
    storage.write_bytes("dir/a.txt", b"x")
    assert (tmp_path / "dir" / "a.txt").read_bytes() == b"x"


def test_from_url_refuses_what_fsspec_cannot_open(monkeypatch: pytest.MonkeyPatch) -> None:
    password = secrets.token_hex(8)
    with pytest.raises(StorageURIException, match="Protocol not known") as caught:
        FsspecStorage.from_url(f"no-such-protocol://user:{password}@host/data")
    assert "no-such-protocol://host/data" in str(caught.value)
    assert password not in str(caught.value)

    def _needs_a_driver(url: str, **_options: Any) -> None:
        raise ImportError("Install s3fs to access S3")

    monkeypatch.setattr("fsspec.core.url_to_fs", _needs_a_driver)
    with pytest.raises(StorageUnavailableException, match="Install s3fs"):
        FsspecStorage.from_url("s3://bucket/data")


def test_fsspec_must_be_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    filesystem = KeyValueFileSystem()
    monkeypatch.setitem(sys.modules, "fsspec", None)
    monkeypatch.setitem(sys.modules, "fsspec.core", None)
    with pytest.raises(StorageUnavailableException, match="fsspec is not installed"):
        FsspecStorage.from_url("memory://jobs")
    with pytest.raises(StorageUnavailableException, match="fsspec is not installed"):
        FsspecStorage(filesystem)


def test_any_scheme_can_be_mounted_on_it(keyvalue: FsspecStorage, tmp_path: Path) -> None:
    resolver = StorageResolver()
    resolver.mount("gcs://reports", keyvalue)
    report = File("gcs://reports/2026/q1.csv", resolver=resolver)
    report.write(b"a,b\n")
    assert keyvalue.filesystem.objects["bucket/2026/q1.csv"][0] == b"a,b\n"
    assert resolver.resolve("gcs://reports/2026/q1.csv") == (keyvalue, "2026/q1.csv")
    assert resolver.capabilities("gcs://reports").directories is False
    assert "gcs" in resolver.schemes()
    report.copy_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    report.move_to("gcs://reports/archive/q1.csv")
    assert sorted(keyvalue.filesystem.objects) == ["bucket/archive/q1.csv"]
    with pytest.raises(StorageURIException, match="no mount"):
        resolver.resolve("gcs://another-bucket/a.txt")


def test_uri_equality_and_repr(tmp_path: Path) -> None:
    filesystem = KeyValueFileSystem()
    storage = FsspecStorage(filesystem, root="bucket/tenant/", scheme="gcs", directories=False)
    assert storage.root == "bucket/tenant"
    assert storage.uri_for("") == "gcs://bucket/tenant"
    assert storage.uri_for("/a//b.txt") == "gcs://bucket/tenant/a/b.txt"
    assert FsspecStorage(filesystem).uri_for("bucket/a.txt") == "fsspec://bucket/a.txt"
    assert FsspecStorage(MemoryFileSystem()).uri_for("a.txt") == "fsspec:///a.txt"
    assert repr(storage) == "FsspecStorage(KeyValueFileSystem, root='bucket/tenant')"
    assert storage == FsspecStorage(filesystem, root="bucket/tenant")
    assert storage != FsspecStorage(filesystem, root="bucket")
    assert storage != FsspecStorage(KeyValueFileSystem(), root="bucket/tenant")
    assert len({storage, FsspecStorage(filesystem, root="bucket/tenant")}) == 1
    # fsspec hands out one object per filesystem configuration, so these two are one storage.
    first = FsspecStorage(LocalFileSystem(), root=str(tmp_path))
    second = FsspecStorage(LocalFileSystem(), root=str(tmp_path))
    assert first == second


# ---------------------------------------------------------------------- the real fsspec


def _parameters(method: Any) -> list[str]:
    return list(inspect.signature(method).parameters)[1:]


@pytest.mark.parametrize("filesystem", [AbstractFileSystem, LocalFileSystem, MemoryFileSystem])
def test_fsspec_has_the_calls_the_adapter_makes(filesystem: type) -> None:
    assert _parameters(filesystem.info)[0] == "path"
    assert _parameters(filesystem.ls)[:2] == ["path", "detail"]
    assert len(_parameters(filesystem.put_file)) >= 2
    assert len(_parameters(filesystem.get_file)) >= 2
    assert _parameters(filesystem.rm_file) == ["path"]
    assert _parameters(filesystem.makedirs) == ["path", "exist_ok"]
    assert _parameters(filesystem.rmdir) == ["path"]
    assert _parameters(filesystem.cp_file)[:2] == ["path1", "path2"]
    assert _parameters(filesystem.mv)[:2] == ["path1", "path2"]
    assert _parameters(filesystem.cat_file)[0] == "path"
    assert _parameters(filesystem.modified) == ["path"]
    assert isinstance(filesystem.root_marker, str)
    assert callable(filesystem._strip_protocol)


def test_fsspec_resolves_a_url_to_a_filesystem_and_a_path() -> None:
    assert _parameters(AbstractFileSystem.put_file)[:2] == ["lpath", "rpath"]
    assert _parameters(AbstractFileSystem.get_file)[:2] == ["rpath", "lpath"]
    assert list(inspect.signature(url_to_fs).parameters) == ["url", "kwargs"]
    filesystem, path = url_to_fs("memory://jobs/2026")
    assert isinstance(filesystem, MemoryFileSystem)
    assert path == "/jobs/2026"
    assert MemoryFileSystem() is MemoryFileSystem()
    with pytest.raises(NotImplementedError):
        AbstractFileSystem(skip_instance_cache=True).modified("a.txt")


def test_two_roots_of_one_filesystem_do_not_lose_a_file_to_itself() -> None:
    whole = FsspecStorage(MemoryFileSystem())
    inner = FsspecStorage(MemoryFileSystem(), root="team/a")
    whole.mkdir("team/a")
    inner.write_bytes("docs/a.txt", b"payload")
    for operation in (whole.move_from, whole.copy_from):
        with pytest.raises(StorageException, match="same file"):
            operation(inner, "docs/a.txt", "team/a/docs/a.txt")
    with pytest.raises(StorageException, match="same file"):
        inner.move_from(whole, "team/a/docs/a.txt", "docs/a.txt")
    assert whole.read_bytes("team/a/docs/a.txt") == b"payload"
