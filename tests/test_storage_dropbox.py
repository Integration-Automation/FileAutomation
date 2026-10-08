"""DropboxStorage: the storage contract against an in-memory stand-in for ``dropbox.Dropbox``.

The stand-in answers the calls the adapter makes -- ``files_get_metadata``,
``files_list_folder`` (paged), ``files_upload``, the upload session calls,
``files_download_to_file``, ``files_delete_v2``, ``files_create_folder_v2``,
``files_copy_v2`` and ``files_move_v2`` -- with the SDK's own data types and
raises the SDK's own exceptions. No request leaves the process.
"""

from __future__ import annotations

import hashlib
import inspect
import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("dropbox", reason="needs the dropbox extra")

# pylint: disable=wrong-import-position  # importorskip must precede these imports
import dropbox
import requests
from dropbox import auth as dropbox_auth
from dropbox import files
from dropbox.exceptions import (
    ApiError,
    AuthError,
    BadInputError,
    DropboxException,
    HttpError,
    InternalServerError,
    RateLimitError,
)
from dropbox.stone_serializers import json_compat_obj_decode

from automation_file.exceptions import (
    StorageAlreadyExistsException,
    StorageException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.remote.dropbox_api.client import dropbox_instance
from automation_file.storage import File, StorageBackend, StorageResolver
from automation_file.storage import dropbox_storage as dropbox_storage_module
from automation_file.storage.dropbox_storage import (
    DROPBOX_SCHEME,
    DropboxStorage,
    dropbox_factory,
)
from tests.storage_contract import StorageContract

PAGE_SIZE = 2
REQUEST_ID = "request-1"
_HASH_BLOCK = 4 * 1024 * 1024


def _api_error(error: Any) -> ApiError:
    return ApiError(REQUEST_ID, error, None, None)


def _content_hash(data: bytes) -> str:
    """Dropbox's content hash: the SHA-256 of the SHA-256 digests of 4 MiB blocks."""
    digests = b"".join(
        hashlib.sha256(data[start : start + _HASH_BLOCK]).digest()
        for start in range(0, len(data), _HASH_BLOCK)
    )
    return hashlib.sha256(digests).hexdigest()


def _parent(path: str) -> str:
    return path.rpartition("/")[0]


@dataclass
class _Stored:
    data: bytes
    revision: int
    modified: datetime

    def metadata(self, path: str) -> files.FileMetadata:
        return files.FileMetadata(
            name=path.rpartition("/")[2],
            id=f"id:{self.revision}",
            client_modified=self.modified,
            server_modified=self.modified,
            rev=f"{self.revision:016x}",
            size=len(self.data),
            path_lower=path.lower(),
            path_display=path,
            content_hash=_content_hash(self.data),
        )


def _folder_metadata(path: str) -> files.FolderMetadata:
    return files.FolderMetadata(
        name=path.rpartition("/")[2], id="id:folder", path_lower=path.lower(), path_display=path
    )


class FakeDropbox:
    """The subset of ``dropbox.Dropbox`` that DropboxStorage calls.

    Paths are ``""`` for the root and ``/a/b`` otherwise, as in the HTTP API. Unlike
    Dropbox, names are compared case-sensitively.
    """

    def __init__(self) -> None:
        self.stored: dict[str, _Stored] = {}
        self.folders: set[str] = set()
        self.calls: list[str] = []
        self.chunks: list[int] = []
        self.fail_with: Exception | None = None
        self._sessions: dict[str, bytearray] = {}
        self._cursors: dict[str, list[Any]] = {}
        self._revision = 0

    # ------------------------------------------------------------------ helpers

    def _begin(self, call: str, *paths: str) -> None:
        self.calls.append(call)
        if self.fail_with is not None:
            raise self.fail_with
        for path in paths:
            if path and (not path.startswith("/") or path.endswith("/")):
                raise BadInputError(REQUEST_ID, f"path: {path!r} did not match the pattern")

    def _is_folder(self, path: str) -> bool:
        return not path or path in self.folders

    def _write_conflict(self, path: str) -> Any:
        """Return the WriteError that stops a write at ``path``, or ``None``."""
        if path in self.folders:
            return files.WriteError.conflict(files.WriteConflictError.folder)
        ancestor = _parent(path)
        while ancestor:
            if ancestor in self.stored:
                return files.WriteError.conflict(files.WriteConflictError.file_ancestor)
            ancestor = _parent(ancestor)
        return None

    def _make_parents(self, path: str) -> None:
        ancestor = _parent(path)
        while ancestor:
            self.folders.add(ancestor)
            ancestor = _parent(ancestor)

    def _store(self, path: str, data: bytes, mode: Any) -> files.FileMetadata:
        conflict = self._write_conflict(path)
        if conflict is None and path in self.stored and not mode.is_overwrite():
            conflict = files.WriteError.conflict(files.WriteConflictError.file)
        if conflict is not None:
            failed = files.UploadWriteFailed(reason=conflict, upload_session_id="session")
            raise _api_error(files.UploadError.path(failed))
        self._make_parents(path)
        self._revision += 1
        moment = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        self.stored[path] = _Stored(data, self._revision, moment)
        return self.stored[path].metadata(path)

    def _metadata(self, path: str) -> Any:
        if path in self.stored:
            return self.stored[path].metadata(path)
        if path in self.folders:
            return _folder_metadata(path)
        return None

    # ------------------------------------------------------------------ the SDK surface

    def files_get_metadata(self, path: str) -> Any:
        self._begin("files_get_metadata", path)
        if not path:
            raise BadInputError(REQUEST_ID, "path: The root folder is unsupported.")
        metadata = self._metadata(path)
        if metadata is None:
            raise _api_error(files.GetMetadataError.path(files.LookupError.not_found))
        return metadata

    def files_list_folder(self, path: str) -> files.ListFolderResult:
        self._begin("files_list_folder", path)
        if path in self.stored:
            raise _api_error(files.ListFolderError.path(files.LookupError.not_folder))
        if not self._is_folder(path):
            raise _api_error(files.ListFolderError.path(files.LookupError.not_found))
        names = sorted(name for name in (*self.folders, *self.stored) if _parent(name) == path)
        return self._page([self._metadata(name) for name in names])

    def files_list_folder_continue(self, cursor: str) -> files.ListFolderResult:
        self._begin("files_list_folder_continue")
        return self._page(self._cursors.pop(cursor))

    def _page(self, entries: list[Any]) -> files.ListFolderResult:
        cursor = f"cursor-{len(self._cursors)}-{len(entries)}"
        rest = entries[PAGE_SIZE:]
        if rest:
            self._cursors[cursor] = rest
        return files.ListFolderResult(
            entries=entries[:PAGE_SIZE], cursor=cursor, has_more=bool(rest)
        )

    def files_upload(self, f: bytes, path: str, mode: Any = files.WriteMode.add) -> Any:
        self._begin("files_upload", path)
        if not isinstance(f, bytes):
            raise TypeError(f"expected request_binary as binary type, got {type(f)}")
        return self._store(path, f, mode)

    def files_upload_session_start(self, f: bytes) -> files.UploadSessionStartResult:
        self._begin("files_upload_session_start")
        session_id = f"session-{len(self._sessions)}"
        self._sessions[session_id] = bytearray(f)
        self.chunks.append(len(f))
        return files.UploadSessionStartResult(session_id=session_id)

    def _append(self, f: bytes, cursor: Any) -> bytearray:
        lookup = files.UploadSessionLookupError
        if cursor.session_id not in self._sessions:
            raise _api_error(files.UploadSessionFinishError.lookup_failed(lookup.not_found))
        session = self._sessions[cursor.session_id]
        if cursor.offset != len(session):
            offset = files.UploadSessionOffsetError(correct_offset=len(session))
            raise _api_error(
                files.UploadSessionFinishError.lookup_failed(lookup.incorrect_offset(offset))
            )
        session.extend(f)
        self.chunks.append(len(f))
        return session

    def files_upload_session_append_v2(self, f: bytes, cursor: Any) -> None:
        self._begin("files_upload_session_append_v2")
        self._append(f, cursor)

    def files_upload_session_finish(self, f: bytes, cursor: Any, commit: Any) -> Any:
        self._begin("files_upload_session_finish", commit.path)
        data = bytes(self._append(f, cursor))
        del self._sessions[cursor.session_id]
        return self._store(commit.path, data, commit.mode)

    def files_download_to_file(self, download_path: str, path: str) -> Any:
        self._begin("files_download_to_file", path)
        if path in self.folders:
            raise _api_error(files.DownloadError.path(files.LookupError.not_file))
        if path not in self.stored:
            raise _api_error(files.DownloadError.path(files.LookupError.not_found))
        Path(download_path).write_bytes(self.stored[path].data)
        return self.stored[path].metadata(path)

    def files_delete_v2(self, path: str) -> files.DeleteResult:
        self._begin("files_delete_v2", path)
        metadata = self._metadata(path)
        if metadata is None:
            raise _api_error(files.DeleteError.path_lookup(files.LookupError.not_found))
        below = f"{path}/"
        for name in [name for name in self.stored if name == path or name.startswith(below)]:
            del self.stored[name]
        self.folders = {
            name for name in self.folders if name != path and not name.startswith(below)
        }
        return files.DeleteResult(metadata=metadata)

    def files_create_folder_v2(self, path: str) -> None:
        self._begin("files_create_folder_v2", path)
        conflict = self._write_conflict(path)
        if path in self.stored:
            conflict = files.WriteError.conflict(files.WriteConflictError.file)
        if conflict is not None:
            raise _api_error(files.CreateFolderError.path(conflict))
        self._make_parents(path)
        self.folders.add(path)

    def _relocate(self, call: str, from_path: str, to_path: str) -> _Stored:
        self._begin(call, from_path, to_path)
        if from_path not in self.stored:
            raise _api_error(files.RelocationError.from_lookup(files.LookupError.not_found))
        conflict = self._write_conflict(to_path)
        if to_path in self.stored:
            conflict = files.WriteError.conflict(files.WriteConflictError.file)
        if conflict is not None:
            raise _api_error(files.RelocationError.to(conflict))
        self._make_parents(to_path)
        self._revision += 1
        source = self.stored[from_path]
        self.stored[to_path] = _Stored(source.data, self._revision, source.modified)
        return source

    def files_copy_v2(self, from_path: str, to_path: str) -> None:
        self._relocate("files_copy_v2", from_path, to_path)

    def files_move_v2(self, from_path: str, to_path: str) -> None:
        self._relocate("files_move_v2", from_path, to_path)
        del self.stored[from_path]


class TestDropboxStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return DropboxStorage(FakeDropbox())


class TestRootedDropboxStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        client = FakeDropbox()
        client.files_create_folder_v2("/team/a")
        client.files_upload(b"keep", "/other-team/keep.txt")
        return DropboxStorage(client, root="team/a")


class TestSessionUploadDropboxStorageContract(StorageContract):
    """The whole contract again, with every upload going through an upload session."""

    @pytest.fixture
    def backend(self, monkeypatch: pytest.MonkeyPatch) -> StorageBackend:
        monkeypatch.setattr(dropbox_storage_module, "UPLOAD_SESSION_THRESHOLD", -1)
        monkeypatch.setattr(dropbox_storage_module, "UPLOAD_CHUNK_SIZE", 1024 * 1024)
        return DropboxStorage(FakeDropbox())


@pytest.fixture
def client() -> FakeDropbox:
    return FakeDropbox()


@pytest.fixture
def storage(client: FakeDropbox) -> DropboxStorage:
    return DropboxStorage(client)


def test_stat_reports_what_the_metadata_carries(
    storage: DropboxStorage, client: FakeDropbox
) -> None:
    info = storage.write_bytes("reports/q1.json", b"{}")
    stored = client.stored["/reports/q1.json"]
    assert info.path == "reports/q1.json"
    assert info.size == 2
    assert info.modified_at == stored.modified.replace(tzinfo=timezone.utc)
    assert info.modified_at.utcoffset() == timedelta(0)
    assert info.version == f"{stored.revision:016x}"
    assert info.etag == _content_hash(b"{}")
    assert info.content_type is None
    folder = storage.stat("reports")
    assert (folder.is_dir, folder.size, folder.modified_at) == (True, None, None)


def test_the_account_root_needs_no_request(storage: DropboxStorage, client: FakeDropbox) -> None:
    assert storage.stat("").is_dir is True
    assert client.calls == []


def test_a_missing_root_folder_does_not_exist(client: FakeDropbox) -> None:
    rooted = DropboxStorage(client, root="/no/such/folder/")
    assert rooted.root == "no/such/folder"
    assert rooted.exists("") is False
    rooted.write_bytes("a.txt", b"x")
    assert rooted.exists("") is True
    assert sorted(client.stored) == ["/no/such/folder/a.txt"]


def test_listing_reads_every_page(storage: DropboxStorage, client: FakeDropbox) -> None:
    for index in range(5):
        storage.write_bytes(f"dir/{index}.txt", b"x")
    client.calls.clear()
    listing = storage.list_dir("dir")
    assert [info.path for info in listing] == [f"dir/{index}.txt" for index in range(5)]
    assert all(info.version and info.etag for info in listing)
    assert client.calls.count("files_list_folder_continue") == 2


def test_a_small_file_goes_up_in_one_request(storage: DropboxStorage, client: FakeDropbox) -> None:
    storage.write_bytes("a.bin", b"x" * 64)
    assert "files_upload" in client.calls
    assert "files_upload_session_start" not in client.calls


@pytest.mark.parametrize(
    "size,chunks",
    [
        (11, [4, 4, 3]),
        (12, [4, 4, 4]),
        (5, [4, 1]),
        (9, [4, 4, 1]),
    ],
)
def test_a_large_file_goes_up_through_an_upload_session(
    monkeypatch: pytest.MonkeyPatch,
    storage: DropboxStorage,
    client: FakeDropbox,
    size: int,
    chunks: list[int],
) -> None:
    monkeypatch.setattr(dropbox_storage_module, "UPLOAD_SESSION_THRESHOLD", 4)
    monkeypatch.setattr(dropbox_storage_module, "UPLOAD_CHUNK_SIZE", 4)
    data = bytes(range(size))
    storage.write_bytes("old.bin", b"old!")
    client.calls.clear()
    info = storage.write_bytes("big.bin", data)
    assert info.size == size
    assert client.stored["/big.bin"].data == data
    assert client.chunks == chunks
    assert "files_upload" not in client.calls
    assert client.calls.count("files_upload_session_start") == 1
    assert client.calls.count("files_upload_session_append_v2") == len(chunks) - 2
    assert client.calls.count("files_upload_session_finish") == 1


def test_a_session_upload_replaces_an_existing_file(
    monkeypatch: pytest.MonkeyPatch, storage: DropboxStorage, client: FakeDropbox
) -> None:
    monkeypatch.setattr(dropbox_storage_module, "UPLOAD_SESSION_THRESHOLD", 4)
    monkeypatch.setattr(dropbox_storage_module, "UPLOAD_CHUNK_SIZE", 4)
    storage.write_bytes("a.bin", b"first content")
    storage.write_bytes("a.bin", b"second")
    assert client.stored["/a.bin"].data == b"second"


def test_a_file_at_the_threshold_still_goes_up_in_one_request(
    monkeypatch: pytest.MonkeyPatch, storage: DropboxStorage, client: FakeDropbox
) -> None:
    monkeypatch.setattr(dropbox_storage_module, "UPLOAD_SESSION_THRESHOLD", 4)
    storage.write_bytes("a.bin", b"1234")
    assert client.calls.count("files_upload") == 1
    assert client.chunks == []


def test_the_default_chunk_is_a_multiple_of_four_mebibytes() -> None:
    assert dropbox_storage_module.UPLOAD_CHUNK_SIZE % (4 * 1024 * 1024) == 0
    assert dropbox_storage_module.UPLOAD_SESSION_THRESHOLD <= 150 * 1024 * 1024


def test_copy_and_move_within_dropbox_are_done_by_dropbox(
    storage: DropboxStorage, client: FakeDropbox
) -> None:
    storage.write_bytes("a.txt", b"payload")
    client.calls.clear()
    storage.copy_from(storage, "a.txt", "copies/b.txt")
    assert client.stored["/copies/b.txt"].data == b"payload"
    storage.move_from(storage, "a.txt", "moved/c.txt")
    assert sorted(client.stored) == ["/copies/b.txt", "/moved/c.txt"]
    assert {"files_copy_v2", "files_move_v2"} <= set(client.calls)
    assert not {"files_upload", "files_download_to_file"} & set(client.calls)


def test_a_copy_replaces_a_file_in_the_way(storage: DropboxStorage, client: FakeDropbox) -> None:
    storage.write_bytes("a.txt", b"new")
    storage.write_bytes("b.txt", b"old")
    client.calls.clear()
    storage.copy_from(storage, "a.txt", "b.txt")
    assert client.stored["/b.txt"].data == b"new"
    relocations = [call for call in client.calls if call in ("files_copy_v2", "files_delete_v2")]
    assert relocations == ["files_copy_v2", "files_delete_v2", "files_copy_v2"]


@pytest.mark.parametrize("relocate", ["_copy_from", "_move_from"])
def test_a_file_is_never_deleted_to_make_room_for_itself(
    storage: DropboxStorage, client: FakeDropbox, relocate: str
) -> None:
    """Dropbox ignores case, so ``A.txt`` over ``a.txt`` reaches it as a file in its own way."""
    storage.write_bytes("a.txt", b"only copy")
    client.calls.clear()
    with pytest.raises(StorageException, match="the same file"):
        getattr(storage, relocate)(storage, "a.txt", "a.txt")
    assert "files_delete_v2" not in client.calls
    assert client.stored["/a.txt"].data == b"only copy"


def test_a_folder_in_the_way_is_never_deleted(storage: DropboxStorage, client: FakeDropbox) -> None:
    storage.write_bytes("a.txt", b"new")
    storage.write_bytes("dir/keep.txt", b"keep")
    client.calls.clear()
    with pytest.raises(StorageAlreadyExistsException):
        storage._copy_from(storage, "a.txt", "dir")
    with pytest.raises(StorageAlreadyExistsException):
        storage._move_from(storage, "a.txt", "dir")
    assert "files_delete_v2" not in client.calls
    assert client.stored["/dir/keep.txt"].data == b"keep"
    assert client.stored["/a.txt"].data == b"new"


def test_copy_between_two_clients_goes_through_a_staging_file(storage: DropboxStorage) -> None:
    other_client = FakeDropbox()
    other = DropboxStorage(other_client)
    storage.write_bytes("a.txt", b"payload")
    other.copy_from(storage, "a.txt", "a.txt")
    assert other_client.stored["/a.txt"].data == b"payload"
    assert "files_copy_v2" not in other_client.calls
    other.move_from(storage, "a.txt", "b.txt")
    assert other_client.stored["/b.txt"].data == b"payload"
    assert storage.exists("a.txt") is False


def test_mkdir_accepts_a_folder_that_appeared_meanwhile(
    storage: DropboxStorage, client: FakeDropbox
) -> None:
    client.files_create_folder_v2("/dir")
    storage._mkdir("dir")
    client.files_upload(b"x", "/file")
    with pytest.raises(StorageAlreadyExistsException):
        storage._mkdir("file")


def test_deleting_a_directory_is_one_request(storage: DropboxStorage, client: FakeDropbox) -> None:
    for path in ("dir/a.txt", "dir/sub/b.txt", "dir/sub/deeper/c.txt"):
        storage.write_bytes(path, b"x")
    client.calls.clear()
    storage.delete("dir", recursive=True)
    assert client.calls.count("files_delete_v2") == 1
    assert client.stored == {}
    assert client.folders == set()


def _lookup(error: Any) -> ApiError:
    return _api_error(files.GetMetadataError.path(error))


@pytest.mark.parametrize(
    "error,expected",
    [
        (AuthError(REQUEST_ID, dropbox_auth.AuthError.invalid_access_token), "permission"),
        (HttpError(REQUEST_ID, 403, "forbidden"), "permission"),
        (_lookup(files.LookupError.restricted_content), "permission"),
        (
            _api_error(files.CreateFolderError.path(files.WriteError.no_write_permission)),
            "permission",
        ),
        (RateLimitError(REQUEST_ID, None, 1), "transient"),
        (InternalServerError(REQUEST_ID, 503, "unavailable"), "transient"),
        (HttpError(REQUEST_ID, 408, "timeout"), "transient"),
        (_api_error(files.DeleteError.too_many_write_operations), "transient"),
        (_api_error(files.RelocationError.internal_error), "transient"),
        (requests.ConnectionError("connection refused"), "transient"),
        (requests.Timeout("read timed out"), "transient"),
        (requests.exceptions.ChunkedEncodingError("cut off"), "transient"),
        (BadInputError(REQUEST_ID, "bad request"), "other"),
        (HttpError(REQUEST_ID, 418, "teapot"), "other"),
        (DropboxException(REQUEST_ID), "other"),
        (_lookup(files.LookupError.malformed_path(None)), "other"),
        (_api_error(files.ListFolderError.other), "other"),
    ],
)
def test_sdk_errors_become_storage_errors(
    storage: DropboxStorage, client: FakeDropbox, error: Exception, expected: str
) -> None:
    kinds: dict[str, type[Exception]] = {
        "permission": StoragePermissionException,
        "transient": StorageTransientException,
        "other": StorageException,
    }
    client.fail_with = error
    with pytest.raises(kinds[expected]) as caught:
        storage.stat("a.txt")
    assert caught.value.__cause__ is error
    assert type(caught.value) is kinds[expected]


def test_a_lost_upload_session_is_not_a_missing_path(
    monkeypatch: pytest.MonkeyPatch, storage: DropboxStorage, client: FakeDropbox, tmp_path: Path
) -> None:
    monkeypatch.setattr(dropbox_storage_module, "UPLOAD_SESSION_THRESHOLD", 1)
    monkeypatch.setattr(client, "files_upload_session_start", lambda _data: _Lost())
    source = tmp_path / "source.bin"
    source.write_bytes(b"0123456789")
    with pytest.raises(StorageException) as caught:
        storage.upload(source, "a.bin")
    assert type(caught.value) is StorageException
    assert "lookup_failed/not_found" in str(caught.value)


class _Lost:
    session_id = "no-such-session"


def test_error_tags_follow_the_sdk_unions() -> None:
    tags = dropbox_storage_module._tags
    assert tags(files.GetMetadataError.path(files.LookupError.not_found)) == ("path", "not_found")
    conflict = files.WriteError.conflict(files.WriteConflictError.file)
    failed = files.UploadWriteFailed(reason=conflict, upload_session_id="session")
    assert tags(files.UploadError.path(failed)) == ("path", "conflict", "file")
    assert tags(files.RelocationError.to(conflict)) == ("to", "conflict", "file")
    assert tags(files.DeleteError.path_lookup(files.LookupError.not_found)) == (
        "path_lookup",
        "not_found",
    )
    assert tags(files.LookupError.malformed_path("bad")) == ("malformed_path",)
    assert tags(None) == ()


def test_the_shared_client_must_be_initialised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dropbox_instance, "client", None)
    with pytest.raises(StorageUnavailableException, match="later_init"):
        DropboxStorage().exists("a.txt")


def test_dropbox_uris_use_the_shared_client(
    monkeypatch: pytest.MonkeyPatch, client: FakeDropbox, tmp_path: Path
) -> None:
    monkeypatch.setattr(dropbox_instance, "client", client)
    resolver = StorageResolver()
    resolver.register_scheme(DROPBOX_SCHEME, dropbox_factory)
    report = File("dropbox:///reports/q1.csv", resolver=resolver)
    report.write(b"a,b\n")
    assert client.stored["/reports/q1.csv"].data == b"a,b\n"
    assert resolver.resolve("dropbox:///reports/q1.csv") == (DropboxStorage(), "reports/q1.csv")
    assert resolver.resolve("dropbox:///") == (DropboxStorage(), "")
    report.copy_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    File(tmp_path / "q1.csv", resolver=resolver).move_to("dropbox:///archive/2026/q1.csv")
    assert client.stored["/archive/2026/q1.csv"].data == b"a,b\n"
    assert not (tmp_path / "q1.csv").exists()


def test_a_dropbox_uri_takes_no_authority() -> None:
    resolver = StorageResolver()
    resolver.register_scheme(DROPBOX_SCHEME, dropbox_factory)
    with pytest.raises(StorageURIException) as caught:
        resolver.resolve("dropbox://team/reports/q1.csv")
    assert "as in 'dropbox:///team/reports/q1.csv'" in str(caught.value)
    with pytest.raises(StorageURIException) as caught:
        resolver.resolve("dropbox://team")
    assert str(caught.value).endswith("as in 'dropbox:///team'")


def test_a_rooted_backend_can_be_mounted(client: FakeDropbox) -> None:
    resolver = StorageResolver()
    archive = DropboxStorage(client, root="archive/2026")
    resolver.mount("dropbox://archive", archive)
    File("dropbox://archive/q1.csv", resolver=resolver).write(b"x")
    assert sorted(client.stored) == ["/archive/2026/q1.csv"]
    assert resolver.resolve("dropbox://archive/q1.csv") == (archive, "q1.csv")
    assert resolver.capabilities("dropbox://archive").directories is True


def test_uri_equality_and_repr(client: FakeDropbox) -> None:
    assert DropboxStorage(client).uri_for("") == "dropbox:///"
    assert DropboxStorage(client).uri_for("/a//b.txt") == "dropbox:///a/b.txt"
    assert DropboxStorage(client, root="team").uri_for("a.txt") == "dropbox:///team/a.txt"
    assert DropboxStorage(client, root="team").uri_for() == "dropbox:///team"
    first, second = DropboxStorage(client), DropboxStorage(client)
    assert first == second
    assert DropboxStorage(client) != DropboxStorage(client, root="team")
    assert DropboxStorage(client) != DropboxStorage(FakeDropbox())
    first, second = DropboxStorage(), DropboxStorage()
    assert first == second
    assert len({DropboxStorage(client), DropboxStorage(client)}) == 1
    assert repr(DropboxStorage(client, root="team/a")) == "DropboxStorage(root='team/a')"
    assert DropboxStorage.scheme == DROPBOX_SCHEME == "dropbox"
    capabilities = DropboxStorage.capabilities
    assert (capabilities.directories, capabilities.etag, capabilities.version) == (True, True, True)
    assert (capabilities.content_type, capabilities.metadata) == (False, False)


# ---------------------------------------------------------------------- the real dropbox SDK


def _parameters(method: Any) -> list[str]:
    return list(inspect.signature(method).parameters)[1:]


def test_the_sdk_has_the_calls_the_adapter_makes() -> None:
    """The stand-in above is only as good as its match with the installed SDK."""
    client = dropbox.Dropbox
    assert _parameters(client.files_get_metadata)[0] == "path"
    assert _parameters(client.files_list_folder)[0] == "path"
    assert _parameters(client.files_list_folder_continue) == ["cursor"]
    assert _parameters(client.files_upload)[:3] == ["f", "path", "mode"]
    assert _parameters(client.files_upload_session_start)[0] == "f"
    assert _parameters(client.files_upload_session_append_v2)[:2] == ["f", "cursor"]
    assert _parameters(client.files_upload_session_finish)[:3] == ["f", "cursor", "commit"]
    assert _parameters(client.files_download_to_file)[:2] == ["download_path", "path"]
    assert _parameters(client.files_delete_v2)[0] == "path"
    assert _parameters(client.files_create_folder_v2)[0] == "path"
    assert _parameters(client.files_copy_v2)[:2] == ["from_path", "to_path"]
    assert _parameters(client.files_move_v2)[:2] == ["from_path", "to_path"]
    assert files.WriteMode.overwrite.is_overwrite() is True
    commit = files.CommitInfo(path="/a.bin", mode=files.WriteMode.overwrite)
    assert (commit.path, commit.mode.is_overwrite()) == ("/a.bin", True)
    cursor = files.UploadSessionCursor(session_id="session", offset=0)
    cursor.offset += 4
    assert (cursor.session_id, cursor.offset) == ("session", 4)


def test_the_sdk_takes_bytes_not_a_file_handle() -> None:
    """Why a large file needs a session: one request holds its whole body in memory."""
    client = dropbox.Dropbox("placeholder")
    with pytest.raises(TypeError, match="binary type"):
        client.files_upload(io.BytesIO(b"x"), "/a.bin")


def test_the_sdk_decodes_metadata_the_way_the_adapter_reads_it() -> None:
    decoded = json_compat_obj_decode(
        files.Metadata_validator,
        {
            ".tag": "file",
            "name": "a.txt",
            "id": "id:a",
            "client_modified": "2026-10-08T02:30:00Z",
            "server_modified": "2026-10-08T02:30:05Z",
            "rev": "0123456789abcdef",
            "size": 3,
            "path_lower": "/a.txt",
            "path_display": "/a.txt",
            "content_hash": "a" * 64,
        },
    )
    assert isinstance(decoded, files.FileMetadata)
    assert decoded.server_modified.tzinfo is None
    info = dropbox_storage_module._file_info("a.txt", decoded, files)
    assert info is not None
    assert info.modified_at == datetime(2026, 10, 8, 2, 30, 5, tzinfo=timezone.utc)
    assert (info.size, info.version, info.etag) == (3, "0123456789abcdef", "a" * 64)
    folder = json_compat_obj_decode(
        files.Metadata_validator,
        {".tag": "folder", "name": "d", "id": "id:d", "path_lower": "/d", "path_display": "/d"},
    )
    assert dropbox_storage_module._file_info("d", folder, files).is_dir is True
    deleted = json_compat_obj_decode(
        files.Metadata_validator,
        {".tag": "deleted", "name": "x", "path_lower": "/x", "path_display": "/x"},
    )
    assert dropbox_storage_module._file_info("x", deleted, files) is None


def test_two_roots_of_one_account_do_not_lose_a_file_to_itself(client: FakeDropbox) -> None:
    whole = DropboxStorage(client)
    inner = DropboxStorage(client, root="team/a")
    whole.mkdir("team/a")
    inner.write_bytes("docs/a.txt", b"payload")
    for operation in (whole.move_from, whole.copy_from):
        with pytest.raises(StorageException, match="same file"):
            operation(inner, "docs/a.txt", "team/a/docs/a.txt")
    with pytest.raises(StorageException, match="same file"):
        inner.move_from(whole, "team/a/docs/a.txt", "docs/a.txt")
    assert whole.read_bytes("team/a/docs/a.txt") == b"payload"
