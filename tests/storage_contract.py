"""The contract every storage backend must pass.

Subclass :class:`StorageContract` in a ``test_*.py`` module and provide a
``backend`` fixture that returns an empty :class:`StorageBackend`:

.. code-block:: python

    class TestMyStorageContract(StorageContract):
        @pytest.fixture
        def backend(self) -> StorageBackend:
            return MyStorage(...)

The suite reads ``backend.capabilities`` to pick the expected behaviour where
backends legitimately differ (real directories versus implied ones, optional
``FileInfo`` fields). Everything else is the same for every backend.

The failure cases need a way to make the storage fail. Override the
``break_storage`` fixture to return ``fail(kind, times=1)``, which makes the next
``times`` calls to the service fail as ``"denied"`` or ``"transient"``; without it
those cases skip.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from automation_file.core.retry import retry_on_transient
from automation_file.exceptions import (
    FileNotExistsException,
    RetryExhaustedException,
    StorageAlreadyExistsException,
    StorageException,
    StorageNotEmptyException,
    StorageNotFoundException,
    StoragePathTypeException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnsupportedException,
    StorageURIException,
)
from automation_file.storage import StorageBackend

BINARY = bytes(range(256)) * 4
LARGE_SIZE = 5 * 1024 * 1024 + 123
UNICODE_PATHS = [
    "資料/報告 2026 ✓.txt",
    "données/été.bin",
    "ファイル/メモ.md",
    "with space/and (parens) & more.txt",
]


def _local_file(directory: Path, data: bytes, name: str = "source.bin") -> Path:
    path = directory / name
    path.write_bytes(data)
    return path


class StorageContract:
    """Behaviour shared by every backend. Not collected on its own."""

    @pytest.fixture
    def backend(self) -> StorageBackend:
        raise NotImplementedError("the contract subclass provides the backend fixture")

    @pytest.fixture
    def break_storage(self, backend: StorageBackend) -> Callable[..., None]:
        pytest.skip("this backend's stand-in cannot be made to fail")

    # ------------------------------------------------------------------ exists / stat

    def test_root_exists_and_is_a_directory(self, backend: StorageBackend) -> None:
        assert backend.exists("") is True
        assert backend.stat("").is_dir is True

    def test_missing_path_does_not_exist(self, backend: StorageBackend) -> None:
        assert backend.exists("nope.txt") is False

    def test_stat_of_a_missing_path_raises_not_found(self, backend: StorageBackend) -> None:
        with pytest.raises(StorageNotFoundException):
            backend.stat("nope.txt")

    def test_not_found_is_also_the_legacy_file_not_exists(self, backend: StorageBackend) -> None:
        with pytest.raises(FileNotExistsException):
            backend.stat("nope.txt")

    def test_stat_describes_a_file(self, backend: StorageBackend) -> None:
        info = backend.write_bytes("dir/report.txt", b"hello world")
        assert info == backend.stat("dir/report.txt")
        assert info.path == "dir/report.txt"
        assert info.name == "report.txt"
        assert info.is_dir is False
        assert info.size == 11

    def test_stat_reports_an_aware_modification_time(self, backend: StorageBackend) -> None:
        if not backend.capabilities.modified_at:
            pytest.skip("backend does not report modification times")
        modified = backend.write_bytes("a.txt", b"x").modified_at
        assert modified is not None
        assert modified.utcoffset() == timedelta(0)

    def test_stat_reports_a_content_type_where_supported(self, backend: StorageBackend) -> None:
        if not backend.capabilities.content_type:
            pytest.skip("backend does not report content types")
        assert backend.write_bytes("notes.txt", b"x").content_type == "text/plain"

    def test_file_info_is_json_friendly(self, backend: StorageBackend) -> None:
        document = backend.write_bytes("a.txt", b"x").to_dict()
        assert document["path"] == "a.txt"
        assert document["is_dir"] is False
        assert document["size"] == 1

    # ------------------------------------------------------------------ upload / download

    def test_upload_then_download_round_trips_binary_data(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        info = backend.upload(_local_file(tmp_path, BINARY), "data.bin")
        assert info.size == len(BINARY)
        target = backend.download("data.bin", tmp_path / "out" / "copy.bin")
        assert target == tmp_path / "out" / "copy.bin"
        assert target.read_bytes() == BINARY

    def test_upload_creates_missing_parent_directories(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        backend.upload(_local_file(tmp_path, b"deep"), "a/b/c/d.txt")
        assert backend.read_bytes("a/b/c/d.txt") == b"deep"
        assert backend.stat("a/b/c").is_dir is True
        assert backend.stat("a").is_dir is True

    def test_empty_file_round_trips(self, backend: StorageBackend, tmp_path: Path) -> None:
        info = backend.upload(_local_file(tmp_path, b""), "empty.bin")
        assert info.size == 0
        assert backend.read_bytes("empty.bin") == b""
        assert backend.download("empty.bin", tmp_path / "empty.out").read_bytes() == b""

    def test_large_file_round_trips(self, backend: StorageBackend, tmp_path: Path) -> None:
        data = bytes(range(251)) * (LARGE_SIZE // 251 + 1)
        data = data[:LARGE_SIZE]
        info = backend.upload(_local_file(tmp_path, data), "large.bin")
        assert info.size == LARGE_SIZE
        digest = hashlib.sha256(data).hexdigest()
        assert backend.checksum("large.bin").value == digest
        downloaded = backend.download("large.bin", tmp_path / "large.out")
        assert hashlib.sha256(downloaded.read_bytes()).hexdigest() == digest

    @pytest.mark.parametrize("path", UNICODE_PATHS)
    def test_unicode_paths_round_trip(self, backend: StorageBackend, path: str) -> None:
        backend.write_bytes(path, BINARY)
        assert backend.exists(path) is True
        assert backend.read_bytes(path) == BINARY
        directory, _, name = path.rpartition("/")
        assert [info.name for info in backend.list_dir(directory)] == [name]

    def test_upload_overwrites_by_default(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"first")
        info = backend.write_bytes("a.txt", b"second, longer")
        assert info.size == 14
        assert backend.read_bytes("a.txt") == b"second, longer"

    def test_upload_without_overwrite_keeps_the_existing_file(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        backend.write_bytes("a.txt", b"first")
        with pytest.raises(StorageAlreadyExistsException):
            backend.upload(_local_file(tmp_path, b"second"), "a.txt", overwrite=False)
        assert backend.read_bytes("a.txt") == b"first"

    def test_upload_of_a_missing_local_file_raises_not_found(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        with pytest.raises(StorageNotFoundException):
            backend.upload(tmp_path / "missing.bin", "a.bin")
        assert backend.exists("a.bin") is False

    def test_upload_onto_a_directory_is_refused(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.upload(_local_file(tmp_path, b"y"), "dir")

    def test_upload_onto_the_root_is_refused(self, backend: StorageBackend, tmp_path: Path) -> None:
        with pytest.raises(StoragePathTypeException):
            backend.upload(_local_file(tmp_path, b"y"), "")

    def test_download_of_a_missing_file_raises_not_found(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        target = tmp_path / "out.bin"
        with pytest.raises(StorageNotFoundException):
            backend.download("nope.bin", target)
        assert not target.exists()

    def test_download_of_a_directory_is_refused(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.download("dir", tmp_path / "out.bin")

    def test_download_overwrites_a_local_file_by_default(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        backend.write_bytes("a.txt", b"remote")
        target = _local_file(tmp_path, b"local", "target.txt")
        backend.download("a.txt", target)
        assert target.read_bytes() == b"remote"

    def test_download_without_overwrite_keeps_the_local_file(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        backend.write_bytes("a.txt", b"remote")
        target = _local_file(tmp_path, b"local", "target.txt")
        with pytest.raises(StorageAlreadyExistsException):
            backend.download("a.txt", target, overwrite=False)
        assert target.read_bytes() == b"local"

    def test_download_leaves_no_partial_file_behind(
        self, backend: StorageBackend, tmp_path: Path
    ) -> None:
        backend.write_bytes("a.txt", b"remote")
        backend.download("a.txt", tmp_path / "out" / "a.txt")
        assert [entry.name for entry in (tmp_path / "out").iterdir()] == ["a.txt"]

    def test_read_of_a_missing_file_raises_not_found(self, backend: StorageBackend) -> None:
        with pytest.raises(StorageNotFoundException):
            backend.read_bytes("nope.bin")

    # ------------------------------------------------------------------ streams

    def test_open_read_streams_the_content(self, backend: StorageBackend) -> None:
        backend.write_bytes("dir/data.bin", BINARY)
        with backend.open_read("dir/data.bin") as stream:
            assert stream.read(10) == BINARY[:10]
            assert stream.read() == BINARY[10:]
            assert stream.read() == b""
        assert stream.closed is True

    def test_open_read_of_a_missing_file_raises_not_found(self, backend: StorageBackend) -> None:
        with pytest.raises(StorageNotFoundException):
            backend.open_read("nope.bin")

    def test_open_read_of_a_directory_is_refused(self, backend: StorageBackend) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.open_read("dir")

    def test_open_write_stores_the_content_on_close(self, backend: StorageBackend) -> None:
        with backend.open_write("deep/dir/out.bin") as stream:
            stream.write(BINARY[:100])
            stream.write(BINARY[100:])
            assert backend.exists("deep/dir/out.bin") is False
        assert backend.read_bytes("deep/dir/out.bin") == BINARY

    def test_open_write_stores_nothing_when_the_block_fails(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"previous")
        with pytest.raises(RuntimeError, match="boom"), backend.open_write("a.txt") as stream:
            stream.write(b"half")
            raise RuntimeError("boom")
        assert backend.read_bytes("a.txt") == b"previous"

    def test_open_write_respects_overwrite(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"previous")
        with pytest.raises(StorageAlreadyExistsException):
            backend.open_write("a.txt", overwrite=False)
        assert backend.read_bytes("a.txt") == b"previous"

    def test_open_write_onto_a_directory_is_refused(self, backend: StorageBackend) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.open_write("dir")

    # ------------------------------------------------------------------ list_dir

    def test_list_dir_of_an_empty_root_is_empty(self, backend: StorageBackend) -> None:
        assert backend.list_dir() == []

    def test_list_dir_returns_immediate_children_sorted(self, backend: StorageBackend) -> None:
        for path in ("b.txt", "a.txt", "sub/c.txt", "sub/deeper/d.txt"):
            backend.write_bytes(path, b"x")
        listing = backend.list_dir("")
        assert [info.path for info in listing] == ["a.txt", "b.txt", "sub"]
        assert [info.is_dir for info in listing] == [False, False, True]
        assert [info.path for info in backend.list_dir("sub")] == ["sub/c.txt", "sub/deeper"]

    def test_list_dir_recursive_returns_every_descendant(self, backend: StorageBackend) -> None:
        for path in ("b.txt", "sub/c.txt", "sub/deeper/d.txt"):
            backend.write_bytes(path, b"xy")
        listing = backend.list_dir("", recursive=True)
        assert [info.path for info in listing] == [
            "b.txt",
            "sub",
            "sub/c.txt",
            "sub/deeper",
            "sub/deeper/d.txt",
        ]
        assert [info.size for info in listing if not info.is_dir] == [2, 2, 2]
        assert [info.path for info in backend.list_dir("sub", recursive=True)] == [
            "sub/c.txt",
            "sub/deeper",
            "sub/deeper/d.txt",
        ]

    def test_list_dir_of_a_missing_directory_raises_not_found(
        self, backend: StorageBackend
    ) -> None:
        with pytest.raises(StorageNotFoundException):
            backend.list_dir("nope")

    def test_list_dir_of_a_file_is_refused(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.list_dir("a.txt")

    # ------------------------------------------------------------------ mkdir

    def test_mkdir_creates_a_directory_where_directories_are_real(
        self, backend: StorageBackend
    ) -> None:
        backend.mkdir("new/nested")
        if backend.capabilities.directories:
            assert backend.stat("new/nested").is_dir is True
            assert [info.path for info in backend.list_dir("new")] == ["new/nested"]
        else:
            assert backend.exists("new/nested") is False

    def test_mkdir_of_an_existing_directory_is_fine_by_default(
        self, backend: StorageBackend
    ) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        backend.mkdir("dir")
        assert backend.read_bytes("dir/a.txt") == b"x"

    def test_mkdir_with_exist_ok_off_refuses_an_existing_directory(
        self, backend: StorageBackend
    ) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        with pytest.raises(StorageAlreadyExistsException):
            backend.mkdir("dir", exist_ok=False)

    def test_mkdir_over_a_file_is_refused(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.mkdir("a.txt")

    def test_mkdir_without_parents_needs_the_parent(self, backend: StorageBackend) -> None:
        if not backend.capabilities.directories:
            pytest.skip("directories are implied on this backend")
        with pytest.raises(StorageNotFoundException):
            backend.mkdir("missing/child", parents=False)
        assert backend.exists("missing") is False

    def test_a_file_cannot_be_created_below_a_file(self, backend: StorageBackend) -> None:
        if not backend.capabilities.directories:
            pytest.skip("directories are implied on this backend")
        backend.write_bytes("a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.write_bytes("a.txt/child.txt", b"y")

    # ------------------------------------------------------------------ delete

    def test_delete_removes_a_file(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"x")
        backend.delete("a.txt")
        assert backend.exists("a.txt") is False

    def test_delete_of_a_missing_path_raises_not_found(self, backend: StorageBackend) -> None:
        with pytest.raises(StorageNotFoundException):
            backend.delete("nope.txt")

    def test_delete_with_missing_ok_ignores_a_missing_path(self, backend: StorageBackend) -> None:
        backend.delete("nope.txt", missing_ok=True)

    def test_delete_refuses_a_directory_with_entries(self, backend: StorageBackend) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        with pytest.raises(StorageNotEmptyException):
            backend.delete("dir")
        assert backend.read_bytes("dir/a.txt") == b"x"

    def test_delete_recursive_removes_the_whole_tree(self, backend: StorageBackend) -> None:
        for path in ("dir/a.txt", "dir/sub/b.txt", "dir/sub/deeper/c.txt", "keep.txt"):
            backend.write_bytes(path, b"x")
        backend.delete("dir", recursive=True)
        assert backend.exists("dir") is False
        assert [info.path for info in backend.list_dir("", recursive=True)] == ["keep.txt"]

    def test_delete_removes_an_empty_directory(self, backend: StorageBackend) -> None:
        if not backend.capabilities.directories:
            pytest.skip("an empty directory cannot exist on this backend")
        backend.mkdir("empty")
        backend.delete("empty")
        assert backend.exists("empty") is False

    def test_delete_refuses_the_root(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"x")
        with pytest.raises(StorageUnsupportedException):
            backend.delete("", recursive=True)
        assert backend.read_bytes("a.txt") == b"x"

    # ------------------------------------------------------------------ checksum

    @pytest.mark.parametrize("algorithm", ["sha256", "sha512", "blake2b", "md5"])
    def test_checksum_matches_hashlib(self, backend: StorageBackend, algorithm: str) -> None:
        backend.write_bytes("data.bin", BINARY)
        checksum = backend.checksum("data.bin", algorithm)
        assert checksum.algorithm == algorithm
        assert checksum.value == hashlib.new(algorithm, BINARY).hexdigest()

    def test_checksum_defaults_to_sha256(self, backend: StorageBackend) -> None:
        backend.write_bytes("data.bin", BINARY)
        checksum = backend.checksum("data.bin")
        assert str(checksum) == f"sha256:{hashlib.sha256(BINARY).hexdigest()}"
        assert checksum.matches(hashlib.sha256(BINARY).hexdigest().upper()) is True

    @pytest.mark.parametrize("algorithm", ["no-such-hash", "shake_128", ""])
    def test_checksum_refuses_an_unusable_algorithm(
        self, backend: StorageBackend, algorithm: str
    ) -> None:
        backend.write_bytes("data.bin", BINARY)
        with pytest.raises(StorageUnsupportedException):
            backend.checksum("data.bin", algorithm)

    def test_checksum_of_a_missing_file_raises_not_found(self, backend: StorageBackend) -> None:
        with pytest.raises(StorageNotFoundException):
            backend.checksum("nope.bin")

    def test_checksum_of_a_directory_is_refused(self, backend: StorageBackend) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.checksum("dir")

    # ------------------------------------------------------------------ paths

    @pytest.mark.parametrize(
        "spelling", ["/dir/a.txt", "dir//a.txt", "./dir/./a.txt", "dir/a.txt/"]
    )
    def test_equivalent_spellings_name_the_same_file(
        self, backend: StorageBackend, spelling: str
    ) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        assert backend.stat(spelling).path == "dir/a.txt"

    @pytest.mark.parametrize("path", ["../escape.txt", "dir/../../escape.txt", "dir/.."])
    def test_parent_segments_are_rejected(self, backend: StorageBackend, path: str) -> None:
        with pytest.raises(StorageURIException):
            backend.exists(path)
        with pytest.raises(StorageURIException):
            backend.write_bytes(path, b"x")

    # ------------------------------------------------------------------ copy / move

    def test_copy_from_the_same_backend(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", BINARY)
        info = backend.copy_from(backend, "a.txt", "copies/b.txt")
        assert info.path == "copies/b.txt"
        assert backend.read_bytes("copies/b.txt") == BINARY
        assert backend.read_bytes("a.txt") == BINARY

    def test_copy_from_respects_overwrite(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"new")
        backend.write_bytes("b.txt", b"old")
        with pytest.raises(StorageAlreadyExistsException):
            backend.copy_from(backend, "a.txt", "b.txt", overwrite=False)
        assert backend.read_bytes("b.txt") == b"old"
        backend.copy_from(backend, "a.txt", "b.txt")
        assert backend.read_bytes("b.txt") == b"new"

    def test_copy_onto_itself_is_refused(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"x")
        with pytest.raises(StorageException):
            backend.copy_from(backend, "a.txt", "/a.txt")
        assert backend.read_bytes("a.txt") == b"x"

    def test_copy_of_a_missing_file_raises_not_found(self, backend: StorageBackend) -> None:
        with pytest.raises(StorageNotFoundException):
            backend.copy_from(backend, "nope.txt", "b.txt")
        assert backend.exists("b.txt") is False

    def test_copy_of_a_directory_is_refused(self, backend: StorageBackend) -> None:
        backend.write_bytes("dir/a.txt", b"x")
        with pytest.raises(StoragePathTypeException):
            backend.copy_from(backend, "dir", "other")

    def test_move_from_the_same_backend(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", BINARY)
        info = backend.move_from(backend, "a.txt", "moved/b.txt")
        assert info.path == "moved/b.txt"
        assert backend.read_bytes("moved/b.txt") == BINARY
        assert backend.exists("a.txt") is False

    def test_move_from_respects_overwrite(self, backend: StorageBackend) -> None:
        backend.write_bytes("a.txt", b"new")
        backend.write_bytes("b.txt", b"old")
        with pytest.raises(StorageAlreadyExistsException):
            backend.move_from(backend, "a.txt", "b.txt", overwrite=False)
        assert backend.read_bytes("a.txt") == b"new"
        assert backend.read_bytes("b.txt") == b"old"
        backend.move_from(backend, "a.txt", "b.txt")
        assert backend.read_bytes("b.txt") == b"new"
        assert backend.exists("a.txt") is False

    # ------------------------------------------------------------------ failures

    def test_a_denied_call_raises_the_permission_error(
        self, backend: StorageBackend, break_storage: Callable[..., None]
    ) -> None:
        backend.write_bytes("a.txt", b"x")
        break_storage("denied")
        with pytest.raises(StoragePermissionException) as caught:
            backend.read_bytes("a.txt")
        assert caught.value.__cause__ is not None
        assert backend.read_bytes("a.txt") == b"x"

    def test_a_transient_failure_raises_the_retryable_error(
        self, backend: StorageBackend, break_storage: Callable[..., None]
    ) -> None:
        backend.write_bytes("a.txt", b"x")
        break_storage("transient")
        with pytest.raises(StorageTransientException) as caught:
            backend.read_bytes("a.txt")
        assert caught.value.__cause__ is not None

    def test_a_transient_failure_goes_away_on_retry(
        self, backend: StorageBackend, break_storage: Callable[..., None]
    ) -> None:
        backend.write_bytes("a.txt", b"payload")

        @retry_on_transient(
            max_attempts=3,
            backoff_base=0.0,
            backoff_cap=0.0,
            retriable=(StorageTransientException,),
        )
        def read() -> bytes:
            return backend.read_bytes("a.txt")

        break_storage("transient", times=2)
        assert read() == b"payload"
        break_storage("transient", times=5)
        with pytest.raises(RetryExhaustedException) as caught:
            read()
        assert isinstance(caught.value.__cause__, StorageTransientException)

    def test_a_denied_call_is_not_retried(
        self, backend: StorageBackend, break_storage: Callable[..., None]
    ) -> None:
        backend.write_bytes("a.txt", b"x")
        attempts = 0

        @retry_on_transient(
            max_attempts=3,
            backoff_base=0.0,
            backoff_cap=0.0,
            retriable=(StorageTransientException,),
        )
        def read() -> bytes:
            nonlocal attempts
            attempts += 1
            return backend.read_bytes("a.txt")

        break_storage("denied", times=3)
        with pytest.raises(StoragePermissionException):
            read()
        assert attempts == 1

    # ------------------------------------------------------------------ lifecycle

    def test_backend_is_a_context_manager(self, backend: StorageBackend) -> None:
        with backend as entered:
            assert entered is backend
            entered.write_bytes("a.txt", b"x")
