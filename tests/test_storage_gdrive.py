"""GoogleDriveStorage: the storage contract against an in-memory Drive behind the real client.

The stand-in (``tests/drive_stand_in.py``) is the HTTP transport of a real
``googleapiclient`` service, built from the Drive v3 discovery document the
package ships. Every ``files()`` call the adapter makes is therefore the real
one, and the last section names what that pins and what it leaves open.
"""

# pylint: disable=line-too-long  # an expected value is kept on one line
# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=unidiomatic-typecheck  # the exact class is what is asserted
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import hashlib
import inspect
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("googleapiclient", reason="needs the gdrive extra")

# pylint: disable=wrong-import-position  # importorskip must precede these imports
import httplib2
from google.auth import exceptions as auth_errors
from googleapiclient import http as googleapiclient_http
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from automation_file.exceptions import (
    StorageException,
    StorageNotEmptyException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageUnsupportedException,
    StorageURIException,
)
from automation_file.remote.google_drive.client import (
    GoogleDriveClient,
    driver_instance,
)
from automation_file.storage import (
    File,
    StorageBackend,
    StorageResolver,
    gdrive_storage,
)
from automation_file.storage.gdrive_storage import (
    GDRIVE_SCHEME,
    GoogleDriveStorage,
    gdrive_factory,
)
from tests.drive_stand_in import (
    BINARY_MIME_TYPE,
    DISCOVERY,
    DOCUMENT_MIME_TYPE,
    FILE_METHODS,
    FILE_SCHEMA,
    MY_DRIVE_ID,
    FakeDrive,
    error_answer,
)
from tests.storage_contract import StorageContract


def _client(drive: FakeDrive) -> GoogleDriveClient:
    """A GoogleDriveClient whose service is the real one, talking to the stand-in."""
    client = GoogleDriveClient()
    client.service = build("drive", "v3", http=drive, static_discovery=True)
    return client


class TestGoogleDriveStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return GoogleDriveStorage(_client(FakeDrive()))


class TestRootedGoogleDriveStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        drive = FakeDrive()
        drive.add_file("keep.txt", b"keep")
        drive.add_file("keep.txt", b"keep", drive.add_folder("other-team"))
        return GoogleDriveStorage(_client(drive), root_id=drive.add_folder("team"))


@pytest.fixture
def drive() -> FakeDrive:
    return FakeDrive()


@pytest.fixture
def client(drive: FakeDrive) -> GoogleDriveClient:
    return _client(drive)


@pytest.fixture
def storage(client: GoogleDriveClient) -> GoogleDriveStorage:
    return GoogleDriveStorage(client)


# ---------------------------------------------------------------------- stat and listing


def test_stat_reports_what_drive_holds(storage: GoogleDriveStorage, drive: FakeDrive) -> None:
    info = storage.write_bytes("reports/q1.json", b"{}")
    assert info.path == "reports/q1.json"
    assert info.size == 2
    assert info.etag == hashlib.md5(b"{}", usedforsecurity=False).hexdigest()  # nosec B324  # nosemgrep  # the digest under test, not a security use
    assert info.version == "1"
    assert info.content_type == "application/json"
    assert info.modified_at is not None
    assert info.modified_at.utcoffset() == timedelta(0)
    assert datetime.now(timezone.utc) - info.modified_at < timedelta(minutes=1)
    assert dict(info.metadata) == {}
    assert drive.only("q1.json").mime_type == "application/json"


def test_a_folder_is_a_directory_with_a_modification_time(storage: GoogleDriveStorage) -> None:
    storage.mkdir("reports")
    info = storage.stat("reports")
    assert (info.is_dir, info.size, info.etag, info.content_type) == (True, None, None, None)
    assert info.modified_at is not None
    assert storage.stat("").is_dir is True


def test_a_name_without_a_known_suffix_is_uploaded_as_octet_stream(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    assert storage.write_bytes("blob", b"x").content_type == BINARY_MIME_TYPE
    opened = drive.last("create")
    assert opened.headers["x-upload-content-type"] == BINARY_MIME_TYPE
    assert opened.body == {"name": "blob", "parents": ["root"], "mimeType": BINARY_MIME_TYPE}


def test_listing_reads_every_page(storage: GoogleDriveStorage, drive: FakeDrive) -> None:
    for index in range(7):
        storage.write_bytes(f"dir/{index}.txt", b"x")
    drive.seen.clear()
    listing = storage.list_dir("dir")
    assert [info.path for info in listing] == [f"dir/{index}.txt" for index in range(7)]
    assert all(info.etag and info.size == 1 for info in listing)
    # "dir" is looked up twice (nothing is remembered between calls), then come four pages.
    assert drive.calls == ["list"] * 6
    assert len(storage.list_dir("", recursive=True)) == 8


def test_recursive_listing_asks_once_per_folder(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    storage.write_bytes("a/b/c.txt", b"x")
    drive.seen.clear()
    assert [info.path for info in storage.list_dir("", recursive=True)] == ["a", "a/b", "a/b/c.txt"]
    # The root is checked with files.get; each of the three folders is listed once.
    assert drive.calls == ["get", "list", "list", "list"]


def test_entries_in_the_trash_do_not_exist(storage: GoogleDriveStorage, drive: FakeDrive) -> None:
    storage.write_bytes("dir/a.txt", b"x")
    drive.only("a.txt").trashed = True
    assert storage.exists("dir/a.txt") is False
    assert storage.list_dir("dir") == []
    storage.write_bytes("dir/a.txt", b"new")
    assert storage.read_bytes("dir/a.txt") == b"new"


def test_a_missing_root_folder_is_not_found(client: GoogleDriveClient) -> None:
    missing = GoogleDriveStorage(client, root_id="no-such-folder")
    assert missing.exists("") is False
    assert missing.exists("a.txt") is False
    with pytest.raises(StorageNotFoundException):
        missing.list_dir()
    with pytest.raises(StorageNotFoundException):
        missing.write_bytes("a.txt", b"x")


def test_a_trashed_root_folder_is_not_found(client: GoogleDriveClient, drive: FakeDrive) -> None:
    folder = drive.add_folder("old")
    drive.entries[folder].trashed = True
    assert GoogleDriveStorage(client, root_id=folder).exists("") is False


# ---------------------------------------------------------------------- names


def test_duplicate_names_are_refused(storage: GoogleDriveStorage, drive: FakeDrive) -> None:
    folder = drive.add_folder("dir")
    first = drive.add_file("a.txt", b"first", folder)
    second = drive.add_file("a.txt", b"second", folder)
    for attempt in (
        lambda: storage.stat("dir/a.txt"),
        lambda: storage.exists("dir/a.txt"),
        lambda: storage.read_bytes("dir/a.txt"),
        lambda: storage.write_bytes("dir/a.txt", b"third"),
        lambda: storage.delete("dir/a.txt"),
        lambda: storage.delete("dir/a.txt", missing_ok=True),
        lambda: storage.copy_from(storage, "dir/a.txt", "b.txt"),
    ):
        with pytest.raises(StorageException, match=r"2 entries share the name 'a\.txt'") as caught:
            attempt()
        assert type(caught.value) is StorageException
        assert "gdrive:///dir/a.txt" in str(caught.value)
    # Neither was picked: both are untouched, and a listing still shows both.
    assert (drive.entries[first].data, drive.entries[second].data) == (b"first", b"second")
    assert [info.path for info in storage.list_dir("dir")] == ["dir/a.txt", "dir/a.txt"]
    assert storage.exists("b.txt") is False


def test_a_duplicate_folder_on_the_way_is_refused(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    for _ in range(3):
        drive.add_file("inner.txt", b"x", drive.add_folder("twin"))
    with pytest.raises(StorageException, match="3 entries share the name 'twin'") as caught:
        storage.exists("twin/inner.txt")
    assert "gdrive:///twin:" in str(caught.value)
    with pytest.raises(StorageException, match="3 entries"):
        storage.write_bytes("twin/new.txt", b"x")
    with pytest.raises(StorageException, match="3 entries"):
        storage.mkdir("twin/sub")
    assert len(drive.named("new.txt")) == 0
    # A recursive listing reads the folders by ID, so it still shows what is there.
    assert [info.path for info in storage.list_dir("", recursive=True)] == [
        "twin",
        "twin",
        "twin",
        "twin/inner.txt",
        "twin/inner.txt",
        "twin/inner.txt",
    ]


def test_names_that_differ_only_in_case_are_different_entries(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    # The stand-in's "name =" ignores case, as Drive's is reported to.
    storage.write_bytes("Report.txt", b"upper")
    assert storage.exists("report.txt") is False
    storage.write_bytes("report.txt", b"lower")
    assert storage.read_bytes("Report.txt") == b"upper"
    assert storage.read_bytes("report.txt") == b"lower"
    assert sorted(info.name for info in storage.list_dir()) == ["Report.txt", "report.txt"]
    storage.delete("Report.txt")
    assert [entry.data for entry in drive.named("report.txt")] == [b"lower"]


@pytest.mark.parametrize(
    "name", ["it's.txt", "back\\slash.txt", "both \\' at once", "'", "\\", "q='x' or name='y'"]
)
def test_quotes_and_backslashes_in_names_are_escaped(
    storage: GoogleDriveStorage, drive: FakeDrive, name: str
) -> None:
    drive.add_file("decoy", b"decoy")
    storage.write_bytes(f"dir/{name}", b"payload")
    assert storage.read_bytes(f"dir/{name}") == b"payload"
    assert drive.only(name).data == b"payload"
    storage.delete(f"dir/{name}")
    assert drive.named(name) == []
    assert drive.only("decoy").data == b"decoy"


def test_an_entry_no_path_can_address_is_left_out_but_protects_its_folder(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    folder = drive.add_folder("dir")
    drive.add_file("2026/10 notes.txt", b"x", folder)
    drive.add_file("..", b"x", folder)
    assert storage.list_dir("dir") == []
    assert [info.path for info in storage.list_dir("", recursive=True)] == ["dir"]
    with pytest.raises(StorageNotEmptyException):
        storage.delete("dir")
    assert len(drive.entries) == 4
    storage.delete("dir", recursive=True)
    assert list(drive.entries) == [MY_DRIVE_ID]


# ---------------------------------------------------------------------- Google Workspace documents


def test_a_google_doc_is_listed_without_a_size_and_cannot_be_downloaded(
    storage: GoogleDriveStorage, drive: FakeDrive, tmp_path: Path
) -> None:
    drive.add_document("Minutes", drive.add_folder("docs"))
    info = storage.stat("docs/Minutes")
    assert (info.is_dir, info.size, info.etag) == (False, None, None)
    assert info.content_type == DOCUMENT_MIME_TYPE
    assert storage.list_dir("docs") == [info]
    target = tmp_path / "minutes.bin"
    for attempt in (
        lambda: storage.download("docs/Minutes", target),
        lambda: storage.read_bytes("docs/Minutes"),
        lambda: storage.checksum("docs/Minutes"),
        lambda: storage.checksum("docs/Minutes", "md5"),
    ):
        with pytest.raises(StorageUnsupportedException, match="Google Workspace document"):
            attempt()
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
    assert "media" not in drive.calls


def test_a_google_doc_cannot_be_replaced_by_a_file(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    document = drive.add_document("Minutes")
    storage.write_bytes("a.txt", b"x")
    with pytest.raises(StorageUnsupportedException, match="cannot replace"):
        storage.write_bytes("Minutes", b"x")
    with pytest.raises(StorageUnsupportedException):
        storage.copy_from(storage, "a.txt", "Minutes")
    assert drive.entries[document].mime_type == DOCUMENT_MIME_TYPE
    assert len(drive.named("Minutes")) == 1


def test_a_google_doc_can_be_copied_moved_and_deleted(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    document = drive.add_document("Minutes")
    copied = storage.copy_from(storage, "Minutes", "archive/Minutes 2026")
    assert (copied.size, copied.content_type) == (None, DOCUMENT_MIME_TYPE)
    storage.move_from(storage, "Minutes", "archive/Minutes")
    assert drive.entries[document].parent == drive.only("archive").file_id
    storage.delete("archive/Minutes")
    assert [info.name for info in storage.list_dir("archive")] == ["Minutes 2026"]


# ---------------------------------------------------------------------- upload and download


def test_overwrite_keeps_the_file_id(storage: GoogleDriveStorage, drive: FakeDrive) -> None:
    storage.write_bytes("dir/a.txt", b"first")
    original = drive.only("a.txt").file_id
    drive.seen.clear()
    info = storage.write_bytes("dir/a.txt", b"second, longer")
    entry = drive.only("a.txt")
    assert (entry.file_id, entry.data, entry.version) == (original, b"second, longer", 2)
    assert (info.size, info.version) == (14, "2")
    assert "update" in drive.calls
    assert "create" not in drive.calls
    assert "delete" not in drive.calls


def test_an_upload_is_resumable_and_typed_by_the_target_name(
    storage: GoogleDriveStorage, drive: FakeDrive, tmp_path: Path
) -> None:
    source = tmp_path / "staged-without-a-suffix"
    source.write_bytes(b"a,b\n")
    storage.mkdir("reports")
    storage.upload(source, "reports/q1.csv")
    opened = drive.last("create")
    assert opened.params["uploadType"] == "resumable"
    assert opened.headers["x-upload-content-type"] == "text/csv"
    assert opened.headers["x-upload-content-length"] == "4"
    assert opened.body == {
        "name": "q1.csv",
        "parents": [drive.only("reports").file_id],
        "mimeType": "text/csv",
    }
    assert drive.last("upload").headers["content-range"] == "bytes 0-3/4"


def test_a_failed_upload_leaves_the_local_file_closed(
    storage: GoogleDriveStorage, drive: FakeDrive, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[MediaFileUpload] = []
    construct = MediaFileUpload.__init__

    def recording(media: MediaFileUpload, *arguments: Any, **options: Any) -> None:
        construct(media, *arguments, **options)
        opened.append(media)

    monkeypatch.setattr(MediaFileUpload, "__init__", recording)
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    drive.fail_with, drive.fail_methods = (503, "backendError"), frozenset({"PUT"})
    with pytest.raises(StorageTransientException):
        storage.upload(source, "a.bin")
    assert [media.stream().closed for media in opened] == [True]
    # On Windows an open handle would make this fail.
    source.unlink()
    assert storage.exists("a.bin") is False


def test_a_download_arrives_in_chunks(
    storage: GoogleDriveStorage, drive: FakeDrive, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = bytes(range(256)) * 20
    storage.write_bytes("data.bin", data)
    monkeypatch.setattr(gdrive_storage, "_DOWNLOAD_CHUNK_SIZE", 1024)
    drive.seen.clear()
    assert storage.download("data.bin", tmp_path / "data.bin").read_bytes() == data
    ranges = [seen.headers["range"] for seen in drive.seen if seen.call == "media"]
    assert ranges == [f"bytes={start}-{start + 1023}" for start in range(0, len(data), 1024)]


def test_a_failed_download_leaves_no_file_behind(
    storage: GoogleDriveStorage, drive: FakeDrive, tmp_path: Path
) -> None:
    storage.write_bytes("a.txt", b"remote")
    target = tmp_path / "out" / "a.txt"
    target.parent.mkdir()
    target.write_bytes(b"local")
    drive.fail_with, drive.fail_methods = (500, "backendError"), frozenset({"GET"})
    with pytest.raises(StorageTransientException):
        storage.download("a.txt", target)
    assert target.read_bytes() == b"local"
    assert [entry.name for entry in target.parent.iterdir()] == ["a.txt"]


# ---------------------------------------------------------------------- checksum


@pytest.mark.parametrize("algorithm", ["md5", "sha1", "sha256"])
def test_checksum_uses_the_digest_drive_holds(
    storage: GoogleDriveStorage, drive: FakeDrive, algorithm: str
) -> None:
    storage.write_bytes("data.bin", b"payload")
    drive.seen.clear()
    assert (
        storage.checksum("data.bin", algorithm).value
        == hashlib.new(algorithm, b"payload").hexdigest()
    )
    assert "media" not in drive.calls


@pytest.mark.parametrize("algorithm", ["md5", "sha256", "sha512"])
def test_checksum_falls_back_to_hashing_the_content(
    storage: GoogleDriveStorage, drive: FakeDrive, algorithm: str
) -> None:
    storage.write_bytes("data.bin", b"payload")
    drive.digests = False
    drive.seen.clear()
    assert storage.stat("data.bin").etag is None
    assert (
        storage.checksum("data.bin", algorithm).value
        == hashlib.new(algorithm, b"payload").hexdigest()
    )
    assert "media" in drive.calls


# ---------------------------------------------------------------------- copy and move


def test_copy_within_drive_is_done_by_drive(storage: GoogleDriveStorage, drive: FakeDrive) -> None:
    storage.write_bytes("a.txt", b"payload")
    original = drive.only("a.txt").file_id
    drive.seen.clear()
    storage.copy_from(storage, "a.txt", "copies/b.txt")
    assert "copy" in drive.calls
    assert not {"media", "upload"} & set(drive.calls)
    copied = drive.only("b.txt")
    assert (copied.data, copied.parent) == (b"payload", drive.only("copies").file_id)
    assert copied.file_id != original
    assert drive.only("a.txt").file_id == original
    assert drive.last("copy").body == {"name": "b.txt", "parents": [copied.parent]}


def test_move_within_drive_keeps_the_file_id(storage: GoogleDriveStorage, drive: FakeDrive) -> None:
    storage.write_bytes("inbox/a.txt", b"payload")
    original = drive.only("a.txt").file_id
    inbox = drive.only("inbox").file_id
    drive.seen.clear()
    storage.move_from(storage, "inbox/a.txt", "archive/2026/b.txt")
    assert not {"media", "upload", "copy", "delete"} & set(drive.calls)
    moved = drive.only("b.txt")
    assert (moved.file_id, moved.data) == (original, b"payload")
    assert moved.parent == drive.only("2026").file_id
    assert drive.named("a.txt") == []
    patch = drive.last("update")
    assert (patch.params["addParents"], patch.params["removeParents"]) == (moved.parent, inbox)
    assert patch.body == {"name": "b.txt"}


def test_a_rename_in_place_changes_no_parent(storage: GoogleDriveStorage, drive: FakeDrive) -> None:
    storage.write_bytes("a.txt", b"payload")
    storage.write_bytes("dir/c.txt", b"other")
    for source, target in (("a.txt", "b.txt"), ("dir/c.txt", "dir/d.txt")):
        drive.seen.clear()
        storage.move_from(storage, source, target)
        assert not {"addParents", "removeParents"} & set(drive.last("update").params)
    assert (drive.only("b.txt").parent, drive.only("b.txt").data) == (MY_DRIVE_ID, b"payload")
    assert drive.only("d.txt").parent == drive.only("dir").file_id


def test_a_move_to_my_drive_names_the_folder_by_its_id(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    storage.write_bytes("dir/a.txt", b"payload")
    storage.move_from(storage, "dir/a.txt", "a.txt")
    assert drive.only("a.txt").parent == MY_DRIVE_ID
    assert drive.last("update").params["addParents"] == MY_DRIVE_ID


def test_copy_and_move_onto_an_existing_file_keep_its_id(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    storage.write_bytes("a.txt", b"from a")
    storage.write_bytes("c.txt", b"from c")
    storage.write_bytes("b.txt", b"old")
    target = drive.only("b.txt").file_id
    storage.copy_from(storage, "a.txt", "b.txt")
    assert (drive.only("b.txt").file_id, drive.only("b.txt").data) == (target, b"from a")
    storage.move_from(storage, "c.txt", "b.txt")
    assert (drive.only("b.txt").file_id, drive.only("b.txt").data) == (target, b"from c")
    assert drive.named("c.txt") == []
    assert "copy" not in drive.calls


def test_two_roots_that_show_one_file_never_transfer_it_onto_itself(
    client: GoogleDriveClient, drive: FakeDrive
) -> None:
    whole = GoogleDriveStorage(client)
    whole.write_bytes("team/a.txt", b"payload")
    team = GoogleDriveStorage(client, root_id=drive.only("team").file_id)
    other_client = GoogleDriveStorage(_client(drive), root_id=drive.only("team").file_id)
    for target in (team, other_client):
        with pytest.raises(StorageException, match="same file"):
            target.move_from(whole, "team/a.txt", "a.txt")
        with pytest.raises(StorageException, match="same file"):
            target.copy_from(whole, "team/a.txt", "a.txt")
    assert drive.only("a.txt").data == b"payload"


def test_copy_between_two_clients_goes_through_a_staging_file(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    other_drive = FakeDrive()
    other = GoogleDriveStorage(_client(other_drive))
    storage.write_bytes("a.txt", b"payload")
    other.copy_from(storage, "a.txt", "a.txt")
    assert other_drive.only("a.txt").data == b"payload"
    assert "copy" not in other_drive.calls
    other.move_from(storage, "a.txt", "moved.txt")
    assert other_drive.only("moved.txt").data == b"payload"
    assert drive.named("a.txt") == []


def test_a_folder_goes_in_one_call_with_everything_in_it(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    for path in ("dir/a.txt", "dir/sub/b.txt", "keep.txt"):
        storage.write_bytes(path, b"x")
    drive.seen.clear()
    storage.delete("dir", recursive=True)
    assert drive.calls.count("delete") == 1
    assert sorted(entry.name for entry in drive.entries.values()) == ["My Drive", "keep.txt"]


# ---------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    "status,reason,expected",
    [
        (403, "rateLimitExceeded", StorageTransientException),
        (403, "userRateLimitExceeded", StorageTransientException),
        (429, "rateLimitExceeded", StorageTransientException),
        (500, "internalError", StorageTransientException),
        (503, "backendError", StorageTransientException),
        (401, "authError", StoragePermissionException),
        (403, "insufficientFilePermissions", StoragePermissionException),
        (403, "dailyLimitExceeded", StoragePermissionException),
        (400, "invalid", StorageException),
        (409, "conflict", StorageException),
    ],
)
def test_http_errors_become_storage_errors(
    storage: GoogleDriveStorage,
    drive: FakeDrive,
    status: int,
    reason: str,
    expected: type[Exception],
) -> None:
    drive.fail_with = (status, reason)
    with pytest.raises(expected) as caught:
        storage.stat("dir/a.txt")
    assert type(caught.value) is expected
    cause = caught.value.__cause__
    assert isinstance(cause, HttpError)
    assert cause.status_code == status
    message = str(caught.value)
    assert message.startswith("gdrive:///dir") or "access to gdrive:///dir" in message
    assert f"{status} {reason}" in message
    # The request URL, which can carry an API key, stays out of the message.
    assert "googleapis" not in message


def test_a_404_is_not_found_with_the_sdk_error_as_its_cause(
    storage: GoogleDriveStorage, drive: FakeDrive
) -> None:
    storage.write_bytes("a.txt", b"x")
    drive.fail_with, drive.fail_methods = (404, "notFound"), frozenset({"DELETE"})
    with pytest.raises(StorageNotFoundException) as caught:
        storage.delete("a.txt")
    assert isinstance(caught.value.__cause__, HttpError)
    drive.fail_methods = None
    assert storage.exists("a.txt") is False


@pytest.mark.parametrize(
    "error,expected",
    [
        (ConnectionResetError("reset by peer"), StorageTransientException),
        (TimeoutError("timed out"), StorageTransientException),
        (httplib2.ServerNotFoundError("no such host"), StorageTransientException),
        (ssl.SSLEOFError("EOF in violation of protocol"), StorageTransientException),
        (auth_errors.TransportError("token endpoint unreachable"), StorageTransientException),
        (auth_errors.RefreshError("invalid_grant"), StoragePermissionException),
        (ssl.SSLCertVerificationError("self-signed certificate"), StorageException),
        (httplib2.HttpLib2Error("redirected too often"), StorageException),
        (auth_errors.DefaultCredentialsError("no credentials"), StorageException),
    ],
)
def test_transport_and_credential_errors_become_storage_errors(
    storage: GoogleDriveStorage, drive: FakeDrive, error: Exception, expected: type[Exception]
) -> None:
    drive.fail_with = error
    with pytest.raises(expected) as caught:
        storage.stat("a.txt")
    assert type(caught.value) is expected
    assert caught.value.__cause__ is error
    assert str(error) not in str(caught.value)


def test_the_shared_client_must_be_initialised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver_instance, "service", None)
    with pytest.raises(StorageUnavailableException, match="later_init") as caught:
        GoogleDriveStorage().exists("a.txt")
    assert isinstance(caught.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------- identity and URIs


def test_uri_for(client: GoogleDriveClient) -> None:
    assert GoogleDriveStorage(client).uri_for("") == "gdrive:///"
    assert GoogleDriveStorage(client).uri_for("/reports//q1.csv") == "gdrive:///reports/q1.csv"
    rooted = GoogleDriveStorage(client, root_id="1AbC-dEf_9")
    assert rooted.uri_for("") == "gdrive://1AbC-dEf_9"
    assert rooted.uri_for("q1.csv") == "gdrive://1AbC-dEf_9/q1.csv"


def test_equality_and_repr(client: GoogleDriveClient, drive: FakeDrive) -> None:
    assert GoogleDriveStorage(client) == GoogleDriveStorage(client, root_id="root")
    assert GoogleDriveStorage(client) == GoogleDriveStorage(client, root_id=" ")
    assert GoogleDriveStorage(client) != GoogleDriveStorage(client, root_id="folder")
    assert GoogleDriveStorage(client) != GoogleDriveStorage(_client(drive))
    assert GoogleDriveStorage(client) != GoogleDriveStorage()
    assert len({GoogleDriveStorage(client), GoogleDriveStorage(client)}) == 1
    assert (
        repr(GoogleDriveStorage(client, root_id="folder")) == "GoogleDriveStorage(root_id='folder')"
    )
    assert GoogleDriveStorage(client).root_id == "root"
    assert GoogleDriveStorage.scheme == GDRIVE_SCHEME == "gdrive"
    assert GoogleDriveStorage.capabilities.to_dict() == {
        "directories": True,
        "modified_at": True,
        "etag": True,
        "version": True,
        "content_type": True,
        "metadata": False,
    }


@pytest.mark.parametrize("root_id", ["two words", "a/b", "user@host"])
def test_a_root_id_that_cannot_be_a_uri_authority_is_refused(root_id: str) -> None:
    with pytest.raises(StorageURIException):
        GoogleDriveStorage(root_id=root_id)


def test_gdrive_uris_use_the_shared_client(
    monkeypatch: pytest.MonkeyPatch, client: GoogleDriveClient, drive: FakeDrive, tmp_path: Path
) -> None:
    monkeypatch.setattr(driver_instance, "service", client.service)
    resolver = StorageResolver()
    resolver.register_scheme(GDRIVE_SCHEME, gdrive_factory)
    report = File("gdrive:///reports/q1.csv", resolver=resolver)
    report.write(b"a,b\n")
    assert drive.only("q1.csv").data == b"a,b\n"
    assert resolver.resolve("gdrive:///reports/q1.csv") == (GoogleDriveStorage(), "reports/q1.csv")
    assert resolver.resolve("gdrive://root/reports/q1.csv") == (
        GoogleDriveStorage(),
        "reports/q1.csv",
    )
    folder = drive.only("reports").file_id
    assert resolver.resolve(f"gdrive://{folder}/q1.csv") == (
        GoogleDriveStorage(root_id=folder),
        "q1.csv",
    )
    assert File(f"gdrive://{folder}/q1.csv", resolver=resolver).read() == b"a,b\n"
    report.copy_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    File(tmp_path / "q1.csv", resolver=resolver).copy_to(f"gdrive://{folder}/2026/q1.csv")
    assert [info.path for info in GoogleDriveStorage().list_dir("reports", recursive=True)] == [
        "reports/2026",
        "reports/2026/q1.csv",
        "reports/q1.csv",
    ]
    with pytest.raises(StorageException, match="same file"):
        report.copy_to(f"gdrive://{folder}/q1.csv")
    assert "gdrive" in resolver.schemes()


# ---------------------------------------------------------------------- the installed googleapiclient


def _parameters(method: str) -> set[str]:
    return set(FILE_METHODS[method]["parameters"]) | set(DISCOVERY["parameters"])


def test_the_discovery_document_has_the_calls_the_adapter_makes() -> None:
    """The stand-in serves a real service; this names what that service is held to."""
    assert DISCOVERY["name"] == "drive"
    assert DISCOVERY["version"] == "v3"
    everywhere = {"supportsAllDrives", "fields"}
    assert everywhere | {"q", "pageSize", "pageToken", "includeItemsFromAllDrives"} <= _parameters(
        "list"
    )
    assert everywhere | {"fileId"} <= _parameters("get")
    assert everywhere <= _parameters("create")
    assert everywhere | {"fileId", "addParents", "removeParents"} <= _parameters("update")
    assert everywhere | {"fileId"} <= _parameters("copy")
    assert {"supportsAllDrives", "fileId"} <= _parameters("delete")
    assert FILE_METHODS["get"]["supportsMediaDownload"] is True
    for method in ("create", "update"):
        assert "resumable" in FILE_METHODS[method]["mediaUpload"]["protocols"]
    assert {"files", "nextPageToken"} <= set(DISCOVERY["schemas"]["FileList"]["properties"])
    assert (
        int(FILE_METHODS["list"]["parameters"]["pageSize"]["maximum"]) >= gdrive_storage._PAGE_SIZE
    )


def test_the_fields_the_adapter_reads_are_in_the_file_schema() -> None:
    asked = {name.strip() for name in gdrive_storage._ENTRY_FIELDS.split(",")}
    asked |= {name.strip() for name in gdrive_storage._ROOT_FIELDS.split(",")}
    asked |= set(gdrive_storage._SERVER_DIGESTS.values())
    assert asked <= set(FILE_SCHEMA)
    assert asked >= {"id", "name", "mimeType", "size", "modifiedTime", "md5Checksum", "version"}
    # 64-bit integers travel as strings, and the time as RFC 3339 text.
    assert (FILE_SCHEMA["size"]["type"], FILE_SCHEMA["size"]["format"]) == ("string", "int64")
    assert (FILE_SCHEMA["version"]["type"], FILE_SCHEMA["version"]["format"]) == ("string", "int64")
    assert FILE_SCHEMA["modifiedTime"]["format"] == "date-time"
    assert FILE_SCHEMA["parents"]["type"] == "array"


def test_the_media_classes_take_the_arguments_the_adapter_passes() -> None:
    assert list(inspect.signature(MediaFileUpload.__init__).parameters) == [
        "self",
        "filename",
        "mimetype",
        "chunksize",
        "resumable",
    ]
    assert list(inspect.signature(MediaIoBaseDownload.__init__).parameters) == [
        "self",
        "fd",
        "request",
        "chunksize",
    ]
    assert callable(MediaFileUpload.stream)
    assert callable(MediaIoBaseDownload.next_chunk)
    assert isinstance(HttpError.status_code, property)


@pytest.mark.parametrize(
    "reason",
    [
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "dailyLimitExceeded",
        "sharingRateLimitExceeded",
        "insufficientFilePermissions",
        "fileNotDownloadable",
    ],
)
def test_a_403_is_transient_exactly_when_googleapiclient_would_retry_it(reason: str) -> None:
    retried = getattr(googleapiclient_http, "_should_retry_response", None)
    if retried is None:
        pytest.skip("this googleapiclient no longer has the private retry rule to compare with")
    _, body = error_answer(403, reason)
    assert retried(403, body) is (reason in gdrive_storage._RATE_LIMIT_REASONS)
    assert retried(429, b"") is True
    assert retried(500, b"") is True
    assert retried(404, b"") is False
