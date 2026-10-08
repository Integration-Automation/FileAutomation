"""OneDriveStorage: the storage contract against an in-memory OneDrive behind a real session.

The stand-in (``tests/graph_stand_in.py``) is a transport adapter mounted on the
``requests.Session`` of a real ``OneDriveClient``, so every request is prepared by
``requests`` itself. What Microsoft Graph answers is the stand-in's reading of the
``driveItem`` documentation: nothing installed describes that API.
"""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=unidiomatic-typecheck  # the exact class is what is asserted
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

# pylint: disable=protected-access  # the shared client's session is swapped for the stand-in's

from __future__ import annotations

import inspect
import json
import logging
import traceback
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import requests

from automation_file.exceptions import (
    OneDriveException,
    StorageException,
    StorageNotFoundException,
    StoragePathTypeException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.logging_config import file_automation_logger
from automation_file.remote.onedrive.client import OneDriveClient, onedrive_instance
from automation_file.storage import File, StorageBackend, StorageResolver, onedrive_storage
from automation_file.storage.onedrive_storage import (
    ONEDRIVE_SCHEME,
    OneDriveStorage,
    onedrive_factory,
)
from tests.graph_stand_in import (
    DOWNLOAD_ORIGIN,
    DRIVE_ROOT,
    ERROR_CODES,
    FAKE_TOKEN,
    FRAGMENT_LIMIT,
    FRAGMENT_UNIT,
    GRAPH_ORIGIN,
    KIB,
    SIMPLE_UPLOAD_LIMIT,
    UPLOAD_ORIGIN,
    URL_SIGNATURE,
    FakeGraph,
    graph_answer,
)
from tests.storage_contract import StorageContract


def _client(graph: FakeGraph) -> OneDriveClient:
    """A OneDriveClient whose session is a real one, with the stand-in as its transport."""
    client = OneDriveClient()
    client.later_init(FAKE_TOKEN)
    client.require_session().mount("https://", graph)
    return client


def _printed(error: BaseException) -> str:
    """Everything a logger would print for ``error``: its text, its cause, its traceback."""
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


class TestOneDriveStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return OneDriveStorage(_client(FakeGraph()))


class TestRootedOneDriveStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        graph = FakeGraph()
        graph.add_file("keep.txt", b"keep")
        graph.add_file("tenants/b/keep.txt", b"keep")
        graph.add_folder("tenants/a")
        return OneDriveStorage(_client(graph), root="tenants/a")


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def client(graph: FakeGraph) -> OneDriveClient:
    return _client(graph)


@pytest.fixture
def storage(client: OneDriveClient) -> OneDriveStorage:
    return OneDriveStorage(client)


@pytest.fixture
def logged() -> Iterator[list[str]]:
    """The messages the library logs while the test runs."""
    messages: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    handler = _Collect(level=logging.DEBUG)
    file_automation_logger.addHandler(handler)
    yield messages
    file_automation_logger.removeHandler(handler)


# ---------------------------------------------------------------------- stat and listing


def test_stat_reports_the_drive_item(storage: OneDriveStorage, graph: FakeGraph) -> None:
    info = storage.write_bytes("reports/q1.json", b"{}")
    item = graph.at("reports/q1.json")
    assert info.path == "reports/q1.json"
    assert info.size == 2
    assert info.etag == f"{{{item.item_id}}},1"
    assert info.content_type == "application/json"
    assert info.version is None
    assert dict(info.metadata) == {}
    assert info.modified_at is not None
    assert info.modified_at.utcoffset() == timedelta(0)
    assert info.modified_at == item.modified


def test_a_folder_is_a_directory_with_a_modification_time(storage: OneDriveStorage) -> None:
    storage.mkdir("reports")
    info = storage.stat("reports")
    assert (info.is_dir, info.size, info.etag, info.content_type) == (True, None, None, None)
    assert info.modified_at is not None
    assert storage.stat("").is_dir is True


def test_listing_follows_the_next_link(storage: OneDriveStorage, graph: FakeGraph) -> None:
    for index in range(7):
        storage.write_bytes(f"dir/{index}.txt", b"x")
    graph.seen.clear()
    listing = storage.list_dir("dir")
    assert [info.path for info in listing] == [f"dir/{index}.txt" for index in range(7)]
    assert all(info.etag and info.size == 1 for info in listing)
    pages = graph.all("children")
    assert len(pages) == 4
    assert "skiptoken" not in pages[0].url
    assert all("skiptoken" in page.url and "select" in page.url for page in pages[1:])
    assert len(storage.list_dir("", recursive=True)) == 8


@pytest.mark.parametrize(
    "name",
    ["100% #1 'draft' +v2.txt", "a%20b.txt", "q=1&r=2;s.txt", "~[x]{y}^`!$@,.txt", "Ünïcödé ß.txt"],
)
def test_reserved_characters_in_a_name_reach_onedrive_intact(
    storage: OneDriveStorage, graph: FakeGraph, name: str
) -> None:
    storage.write_bytes(f"odd names/{name}", b"payload")
    assert graph.paths() == ["odd names", f"odd names/{name}"]
    assert storage.read_bytes(f"odd names/{name}") == b"payload"
    assert [info.name for info in storage.list_dir("odd names")] == [name]
    storage.move_from(storage, f"odd names/{name}", f"moved/{name}")
    storage.delete(f"moved/{name}")
    assert graph.paths() == ["moved", "odd names"]


def test_a_name_onedrive_does_not_allow_is_a_storage_error(storage: OneDriveStorage) -> None:
    with pytest.raises(StorageException, match="400 invalidRequest") as caught:
        storage.write_bytes("what?.txt", b"x")
    assert type(caught.value) is StorageException


def test_names_compare_without_regard_to_case(storage: OneDriveStorage, graph: FakeGraph) -> None:
    storage.write_bytes("Docs/Report.txt", b"first")
    original = graph.at("Docs/Report.txt").item_id
    assert storage.exists("docs/report.txt") is True
    assert storage.stat("DOCS/REPORT.TXT").path == "DOCS/REPORT.TXT"
    storage.write_bytes("docs/report.txt", b"second")
    assert graph.paths() == ["Docs", "Docs/Report.txt"]
    assert (graph.at("Docs/Report.txt").item_id, graph.at("Docs/Report.txt").data) == (
        original,
        b"second",
    )
    assert [info.path for info in storage.list_dir("docs")] == ["docs/Report.txt"]


# ---------------------------------------------------------------------- upload and download


def test_a_small_file_goes_up_in_one_request(storage: OneDriveStorage, graph: FakeGraph) -> None:
    storage.mkdir("reports")
    graph.seen.clear()
    storage.write_bytes("reports/q1.csv", b"a,b\n")
    (put,) = graph.all("put")
    assert put.url == f"{GRAPH_ORIGIN}{DRIVE_ROOT}:/reports/q1.csv:/content"
    assert (put.headers["Content-Type"], put.headers["Content-Length"]) == ("text/csv", "4")
    assert put.body == b"a,b\n"
    assert not {"session", "fragment"} & set(graph.calls)


def test_overwrite_keeps_the_item(storage: OneDriveStorage, graph: FakeGraph) -> None:
    storage.write_bytes("dir/a.txt", b"first")
    original = graph.at("dir/a.txt").item_id
    graph.seen.clear()
    info = storage.write_bytes("dir/a.txt", b"second, longer")
    item = graph.at("dir/a.txt")
    assert (item.item_id, item.data, item.revision) == (original, b"second, longer", 2)
    assert (info.size, info.etag) == (14, f"{{{original}}},2")
    assert "delete" not in graph.calls


def test_the_simple_upload_limit_decides_between_one_request_and_a_session(
    storage: OneDriveStorage, graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(onedrive_storage, "_SIMPLE_UPLOAD_MAX", 100)
    storage.write_bytes("at-the-limit.bin", b"x" * 100)
    assert graph.calls.count("put") == 1
    assert "session" not in graph.calls
    storage.write_bytes("over-the-limit.bin", b"x" * 101)
    assert graph.calls.count("put") == 1
    assert (graph.calls.count("session"), graph.calls.count("fragment")) == (1, 1)
    assert graph.at("over-the-limit.bin").data == b"x" * 101


def test_a_large_file_goes_up_in_fragments_read_from_the_file(
    storage: OneDriveStorage, graph: FakeGraph, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(onedrive_storage, "_SIMPLE_UPLOAD_MAX", KIB)
    monkeypatch.setattr(onedrive_storage, "_UPLOAD_CHUNK_SIZE", FRAGMENT_UNIT)
    data = bytes(range(251)) * 4200
    data = data[: KIB * KIB + 17]
    source = tmp_path / "large.bin"
    source.write_bytes(data)
    storage.write_bytes("large.bin", b"the file it replaces")
    original = graph.at("large.bin").item_id
    graph.seen.clear()
    info = storage.upload(source, "large.bin")
    assert info.size == len(data)
    assert (graph.at("large.bin").item_id, graph.at("large.bin").data) == (original, data)
    (opened,) = graph.all("session")
    assert opened.url == f"{GRAPH_ORIGIN}{DRIVE_ROOT}:/large.bin:/createUploadSession"
    fragments = graph.all("fragment")
    assert [fragment.headers["Content-Range"] for fragment in fragments] == [
        f"bytes 0-327679/{len(data)}",
        f"bytes 327680-655359/{len(data)}",
        f"bytes 655360-983039/{len(data)}",
        f"bytes 983040-{len(data) - 1}/{len(data)}",
    ]
    assert max(len(fragment.body) for fragment in fragments) == FRAGMENT_UNIT
    assert all(fragment.url.startswith(UPLOAD_ORIGIN) for fragment in fragments)
    assert not {"put", "cancel"} & set(graph.calls)
    assert graph.sessions == {}


def test_the_default_fragment_size_is_a_multiple_of_320_kib() -> None:
    assert onedrive_storage._UPLOAD_CHUNK_SIZE % FRAGMENT_UNIT == 0
    assert 0 < onedrive_storage._UPLOAD_CHUNK_SIZE <= FRAGMENT_LIMIT
    assert onedrive_storage._SIMPLE_UPLOAD_MAX == SIMPLE_UPLOAD_LIMIT


@pytest.mark.parametrize(
    "failure",
    [503, requests.ConnectionError(f"Max retries exceeded with url: /session/1?{URL_SIGNATURE}")],
)
def test_a_failed_fragment_cancels_the_session_and_keeps_its_url_secret(
    storage: OneDriveStorage,
    graph: FakeGraph,
    monkeypatch: pytest.MonkeyPatch,
    logged: list[str],
    failure: int | Exception,
) -> None:
    monkeypatch.setattr(onedrive_storage, "_SIMPLE_UPLOAD_MAX", 10)
    graph.fail_with, graph.fail_calls = failure, frozenset({"fragment"})
    with pytest.raises(StorageTransientException) as caught:
        storage.write_bytes("big.bin", b"x" * 100)
    assert graph.calls[-2:] == ["fragment", "cancel"]
    assert graph.sessions == {}
    assert storage.exists("big.bin") is False
    assert caught.value.__cause__ is None
    assert "onedrive:///big.bin" in str(caught.value)
    assert URL_SIGNATURE not in _printed(caught.value)
    assert not any(URL_SIGNATURE in message or FAKE_TOKEN in message for message in logged)


def test_a_session_that_cannot_be_cancelled_is_logged_and_the_first_error_wins(
    storage: OneDriveStorage,
    graph: FakeGraph,
    monkeypatch: pytest.MonkeyPatch,
    logged: list[str],
) -> None:
    monkeypatch.setattr(onedrive_storage, "_SIMPLE_UPLOAD_MAX", 10)
    graph.fail_with, graph.fail_calls = 403, frozenset({"fragment", "cancel"})
    with pytest.raises(StoragePermissionException, match="403 accessDenied"):
        storage.write_bytes("big.bin", b"x" * 100)
    (warning,) = [message for message in logged if "could not be cancelled" in message]
    assert "onedrive:///big.bin" in warning
    assert URL_SIGNATURE not in warning


def test_an_upload_session_without_an_https_url_is_refused(
    storage: OneDriveStorage, graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(onedrive_storage, "_SIMPLE_UPLOAD_MAX", 10)
    plain = {"uploadUrl": "http://upload.onedrive.invalid/session/1"}
    monkeypatch.setattr(graph, "_on_session", lambda request, *_: graph_answer(request, 200, plain))
    with pytest.raises(StorageException, match="without a URL"):
        storage.write_bytes("big.bin", b"x" * 100)
    assert "fragment" not in graph.calls


def test_a_download_is_streamed_through_the_redirect(
    storage: OneDriveStorage, graph: FakeGraph, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = bytes(range(256)) * 20
    storage.write_bytes("data.bin", data)
    read: list[tuple[int, int]] = []
    iter_content = requests.Response.iter_content

    def recording(response: requests.Response, chunk_size: int = 1, **options: Any) -> Any:
        for chunk in iter_content(response, chunk_size, **options):
            read.append((chunk_size, len(chunk)))
            yield chunk

    monkeypatch.setattr(requests.Response, "iter_content", recording)
    monkeypatch.setattr(onedrive_storage, "_DOWNLOAD_CHUNK_SIZE", KIB)
    graph.seen.clear()
    assert storage.download("data.bin", tmp_path / "data.bin").read_bytes() == data
    assert graph.calls == ["item", "content", "download"]
    assert all(seen.stream for seen in graph.seen[1:])
    assert graph.seen[2].url.startswith(DOWNLOAD_ORIGIN)
    # requests reads an unstreamed body in one piece; the download came in 1 KiB pieces.
    assert [size for asked, size in read if asked == KIB] == [KIB] * 5


def test_a_failed_download_keeps_the_download_url_secret_and_leaves_no_file(
    storage: OneDriveStorage, graph: FakeGraph, tmp_path: Path
) -> None:
    storage.write_bytes("a.txt", b"remote")
    target = tmp_path / "out" / "a.txt"
    target.parent.mkdir()
    target.write_bytes(b"local")
    graph.fail_with = requests.ConnectionError(
        f"Max retries exceeded with url: /c/1?{URL_SIGNATURE}"
    )
    graph.fail_calls = frozenset({"download"})
    with pytest.raises(StorageTransientException) as caught:
        storage.download("a.txt", target)
    assert caught.value.__cause__ is None
    assert URL_SIGNATURE not in _printed(caught.value)
    assert target.read_bytes() == b"local"
    assert [entry.name for entry in target.parent.iterdir()] == ["a.txt"]


# ---------------------------------------------------------------------- directories


def test_a_folder_goes_in_one_call_with_everything_in_it(
    storage: OneDriveStorage, graph: FakeGraph
) -> None:
    for path in ("dir/a.txt", "dir/sub/b.txt", "keep.txt"):
        storage.write_bytes(path, b"x")
    graph.seen.clear()
    storage.delete("dir", recursive=True)
    assert graph.calls == ["item", "delete"]
    assert graph.paths() == ["keep.txt"]


def test_creating_a_folder_that_appeared_meanwhile_is_fine(
    storage: OneDriveStorage, graph: FakeGraph
) -> None:
    graph.add_file("dir/a.txt", b"x")
    storage._mkdir("dir")
    assert graph.paths() == ["dir", "dir/a.txt"]
    with pytest.raises(StoragePathTypeException, match="is a file"):
        storage._mkdir("dir/a.txt")


# ---------------------------------------------------------------------- copy and move


def test_move_within_onedrive_is_done_by_onedrive(
    storage: OneDriveStorage, graph: FakeGraph
) -> None:
    storage.write_bytes("inbox/a.txt", b"payload")
    original = graph.at("inbox/a.txt").item_id
    graph.seen.clear()
    info = storage.move_from(storage, "inbox/a.txt", "archive/2026/b.txt")
    assert info.path == "archive/2026/b.txt"
    assert graph.paths() == ["archive", "archive/2026", "archive/2026/b.txt", "inbox"]
    moved = graph.at("archive/2026/b.txt")
    assert (moved.item_id, moved.data) == (original, b"payload")
    (patch,) = graph.all("patch")
    assert patch.url == f"{GRAPH_ORIGIN}{DRIVE_ROOT}:/inbox/a.txt"
    assert json.loads(patch.body) == {
        "parentReference": {"id": graph.at("archive/2026").item_id},
        "name": "b.txt",
    }
    assert not {"content", "put", "session", "delete"} & set(graph.calls)


def test_a_move_between_two_spellings_renames_the_item(
    storage: OneDriveStorage, graph: FakeGraph
) -> None:
    storage.write_bytes("dir/report.txt", b"payload")
    original = graph.at("dir/report.txt").item_id
    graph.seen.clear()
    storage.move_from(storage, "dir/report.txt", "dir/Report.TXT")
    assert graph.paths() == ["dir", "dir/Report.TXT"]
    assert (graph.at("dir/Report.TXT").item_id, graph.at("dir/Report.TXT").data) == (
        original,
        b"payload",
    )
    assert not {"content", "put", "delete"} & set(graph.calls)


def test_a_copy_between_two_spellings_of_one_item_is_refused(
    storage: OneDriveStorage, graph: FakeGraph
) -> None:
    storage.write_bytes("report.txt", b"payload")
    with pytest.raises(StorageException, match="same file"):
        storage.copy_from(storage, "report.txt", "REPORT.txt")
    assert graph.at("report.txt").data == b"payload"


def test_two_roots_that_show_one_file_never_transfer_it_onto_itself(
    client: OneDriveClient, graph: FakeGraph
) -> None:
    whole = OneDriveStorage(client)
    whole.write_bytes("team/a.txt", b"payload")
    team = OneDriveStorage(client, root="team")
    other_client = OneDriveStorage(_client(graph), root="TEAM")
    for target in (team, other_client):
        with pytest.raises(StorageException, match="same file"):
            target.move_from(whole, "team/a.txt", "a.txt")
        with pytest.raises(StorageException, match="same file"):
            target.copy_from(whole, "team/a.txt", "a.txt")
    with pytest.raises(StorageException, match="same file"):
        other_client.move_from(whole, "team/a.txt", "A.TXT")
    assert graph.paths() == ["team", "team/a.txt"]
    assert graph.at("team/a.txt").data == b"payload"


def test_copy_and_move_onto_an_existing_file_keep_its_item(
    storage: OneDriveStorage, graph: FakeGraph
) -> None:
    storage.write_bytes("a.txt", b"from a")
    storage.write_bytes("c.txt", b"from c")
    storage.write_bytes("b.txt", b"old")
    target = graph.at("b.txt").item_id
    storage.copy_from(storage, "a.txt", "b.txt")
    assert (graph.at("b.txt").item_id, graph.at("b.txt").data) == (target, b"from a")
    storage.move_from(storage, "c.txt", "b.txt")
    assert (graph.at("b.txt").item_id, graph.at("b.txt").data) == (target, b"from c")
    assert graph.paths() == ["a.txt", "b.txt"]
    assert "patch" not in graph.calls


def test_copy_goes_through_a_staging_file(storage: OneDriveStorage, graph: FakeGraph) -> None:
    storage.write_bytes("a.txt", b"payload")
    graph.seen.clear()
    storage.copy_from(storage, "a.txt", "copies/b.txt")
    assert graph.at("copies/b.txt").data == b"payload"
    assert graph.at("copies/b.txt").item_id != graph.at("a.txt").item_id
    assert {"content", "download", "put"} <= set(graph.calls)


def test_a_move_between_two_clients_copies_then_deletes(storage: OneDriveStorage) -> None:
    other_graph = FakeGraph()
    other = OneDriveStorage(_client(other_graph))
    storage.write_bytes("a.txt", b"payload")
    other.move_from(storage, "a.txt", "moved/a.txt")
    assert other_graph.at("moved/a.txt").data == b"payload"
    assert "patch" not in other_graph.calls
    assert storage.exists("a.txt") is False


# ---------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, StoragePermissionException),
        (403, StoragePermissionException),
        (408, StorageTransientException),
        (429, StorageTransientException),
        (500, StorageTransientException),
        (503, StorageTransientException),
        (504, StorageTransientException),
        (400, StorageException),
        (409, StorageException),
    ],
)
def test_http_errors_become_storage_errors(
    storage: OneDriveStorage, graph: FakeGraph, status: int, expected: type[Exception]
) -> None:
    graph.fail_with = status
    with pytest.raises(expected) as caught:
        storage.stat("dir/a.txt")
    assert type(caught.value) is expected
    message = str(caught.value)
    assert "onedrive:///dir/a.txt" in message
    assert f"{status} {ERROR_CODES[status]}" in message
    assert "graph.microsoft.com" not in message
    assert FAKE_TOKEN not in _printed(caught.value)


def test_a_404_is_not_found(storage: OneDriveStorage, graph: FakeGraph) -> None:
    storage.write_bytes("a.txt", b"x")
    graph.fail_with, graph.fail_calls = 404, frozenset({"delete"})
    with pytest.raises(StorageNotFoundException, match=r"onedrive:///a\.txt does not exist"):
        storage.delete("a.txt")
    graph.fail_calls = None
    assert storage.exists("a.txt") is False
    with pytest.raises(StorageNotFoundException):
        storage.list_dir()


@pytest.mark.parametrize(
    "error,expected",
    [
        (requests.ConnectionError("connection refused"), StorageTransientException),
        (requests.ConnectTimeout("connect timed out"), StorageTransientException),
        (requests.ReadTimeout("read timed out"), StorageTransientException),
        (requests.exceptions.ChunkedEncodingError("connection broken"), StorageTransientException),
        (requests.exceptions.ProxyError("proxy unreachable"), StorageTransientException),
        (requests.exceptions.SSLError("certificate verify failed"), StorageException),
        (requests.TooManyRedirects("30 redirects"), StorageException),
        (requests.exceptions.InvalidURL("no host"), StorageException),
    ],
)
def test_transport_errors_become_storage_errors_with_their_cause(
    storage: OneDriveStorage, graph: FakeGraph, error: Exception, expected: type[Exception]
) -> None:
    graph.fail_with = error
    with pytest.raises(expected) as caught:
        storage.stat("a.txt")
    assert type(caught.value) is expected
    assert caught.value.__cause__ is error
    assert str(caught.value) == f"onedrive:///a.txt: {type(error).__name__}"


def test_an_answer_that_is_not_a_json_object_is_a_storage_error(
    storage: OneDriveStorage, graph: FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(graph, "_on_item", lambda request, *_: graph_answer(request, 200, [1, 2]))
    with pytest.raises(StorageException, match="unexpected JSON"):
        storage.stat("a.txt")
    monkeypatch.setattr(
        graph, "_on_item", lambda request, *_: graph_answer(request, 200, content=b"<html>")
    )
    with pytest.raises(StorageException, match="not JSON"):
        storage.stat("a.txt")


def test_an_uninitialised_client_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(StorageUnavailableException, match="later_init") as caught:
        OneDriveStorage(OneDriveClient()).exists("a.txt")
    assert isinstance(caught.value.__cause__, OneDriveException)
    monkeypatch.setattr(onedrive_instance, "_session", None)
    with pytest.raises(StorageUnavailableException, match="device_code_login"):
        OneDriveStorage().write_bytes("a.txt", b"x")


def test_a_closed_client_is_unavailable(storage: OneDriveStorage, client: OneDriveClient) -> None:
    storage.write_bytes("a.txt", b"x")
    client.close()
    with pytest.raises(StorageUnavailableException):
        storage.read_bytes("a.txt")


# ---------------------------------------------------------------------- identity and URIs


def test_uri_for(client: OneDriveClient) -> None:
    assert OneDriveStorage(client).uri_for("") == "onedrive:///"
    assert OneDriveStorage(client).uri_for("/reports//q1.csv") == "onedrive:///reports/q1.csv"
    rooted = OneDriveStorage(client, root="/backups//2026/")
    assert rooted.root == "backups/2026"
    assert rooted.uri_for("") == "onedrive:///backups/2026"
    assert rooted.uri_for("q1.csv") == "onedrive:///backups/2026/q1.csv"


def test_a_root_confines_the_backend_to_one_folder(
    client: OneDriveClient, graph: FakeGraph
) -> None:
    graph.add_file("other/keep.txt", b"k")
    tenant = OneDriveStorage(client, root="tenants/a")
    assert tenant.exists("") is False
    with pytest.raises(StorageNotFoundException, match="onedrive:///tenants/a does not exist"):
        tenant.write_bytes("docs/a.txt", b"x")
    OneDriveStorage(client).mkdir("tenants/a")
    tenant.write_bytes("docs/a.txt", b"x")
    assert tenant.stat("").is_dir is True
    assert graph.paths() == [
        "other",
        "other/keep.txt",
        "tenants",
        "tenants/a",
        "tenants/a/docs",
        "tenants/a/docs/a.txt",
    ]
    assert [info.path for info in tenant.list_dir("", recursive=True)] == ["docs", "docs/a.txt"]
    tenant.delete("docs", recursive=True)
    assert graph.paths() == ["other", "other/keep.txt", "tenants", "tenants/a"]
    with pytest.raises(StorageURIException):
        OneDriveStorage(client, root="tenants/../other")


def test_equality_and_repr(client: OneDriveClient, graph: FakeGraph) -> None:
    assert OneDriveStorage(client) == OneDriveStorage(client, root="/")
    assert OneDriveStorage(client) != OneDriveStorage(client, root="a")
    assert OneDriveStorage(client) != OneDriveStorage(_client(graph))
    assert OneDriveStorage(client) != OneDriveStorage()
    first, second = OneDriveStorage(), OneDriveStorage()
    assert first == second
    assert len({OneDriveStorage(client), OneDriveStorage(client)}) == 1
    assert repr(OneDriveStorage(client, root="a/b")) == "OneDriveStorage(root='a/b')"
    assert OneDriveStorage.scheme == ONEDRIVE_SCHEME == "onedrive"
    assert OneDriveStorage.capabilities.to_dict() == {
        "directories": True,
        "modified_at": True,
        "etag": True,
        "version": False,
        "content_type": True,
        "metadata": False,
    }


def test_onedrive_uris_use_the_shared_client(
    monkeypatch: pytest.MonkeyPatch, client: OneDriveClient, graph: FakeGraph, tmp_path: Path
) -> None:
    monkeypatch.setattr(onedrive_instance, "_session", client.require_session())
    resolver = StorageResolver()
    resolver.register_scheme(ONEDRIVE_SCHEME, onedrive_factory)
    report = File("onedrive:///reports/q1.csv", resolver=resolver)
    report.write(b"a,b\n")
    assert graph.at("reports/q1.csv").data == b"a,b\n"
    assert resolver.resolve("onedrive:///reports/q1.csv") == (OneDriveStorage(), "reports/q1.csv")
    report.copy_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    File(tmp_path / "q1.csv", resolver=resolver).copy_to("onedrive:///archive/2026/q1.csv")
    report.move_to("onedrive:///archive/q1.csv")
    assert graph.paths() == [
        "archive",
        "archive/2026",
        "archive/2026/q1.csv",
        "archive/q1.csv",
        "reports",
    ]
    assert "onedrive" in resolver.schemes()


def test_a_onedrive_uri_takes_no_authority() -> None:
    resolver = StorageResolver()
    resolver.register_scheme(ONEDRIVE_SCHEME, onedrive_factory)
    with pytest.raises(StorageURIException, match=r"'onedrive:///reports/q1\.csv'") as caught:
        resolver.resolve("onedrive://reports/q1.csv")
    assert "'reports' as its authority" in str(caught.value)
    with pytest.raises(StorageURIException, match="'onedrive:///reports'"):
        resolver.resolve("onedrive://reports")


# ---------------------------------------------------------------------- the client and requests


def test_graph_send_returns_a_failed_response_instead_of_raising(
    client: OneDriveClient, graph: FakeGraph
) -> None:
    graph.fail_with = 503
    response = client.graph_send("GET", "/me/drive/root")
    assert (response.status_code, response.ok) == (503, False)
    with pytest.raises(OneDriveException, match="503"):
        client.graph_request("GET", "/me/drive/root")
    graph.fail_with = requests.ConnectionError("down")
    with pytest.raises(requests.ConnectionError):
        client.graph_send("GET", "/me/drive/root")
    with pytest.raises(OneDriveException, match="graph request failed"):
        client.graph_request("GET", "/me/drive/root")


def test_graph_send_can_leave_the_bearer_token_out(
    client: OneDriveClient, graph: FakeGraph
) -> None:
    graph.sessions[f"{UPLOAD_ORIGIN}/session/9"] = ("a.bin", bytearray())
    headers = {"Content-Range": "bytes 0-2/3"}
    response = client.graph_send(
        "PUT", f"{UPLOAD_ORIGIN}/session/9", authorized=False, data=b"abc", headers=headers
    )
    assert response.status_code == 201
    assert headers == {"Content-Range": "bytes 0-2/3"}
    assert "Authorization" not in graph.seen[-1].headers
    # The session keeps its token for the next Graph call.
    assert client.graph_send("GET", "/me/drive/root:/a.bin").json()["size"] == 3
    assert graph.seen[-1].headers["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_requests_has_what_the_adapter_relies_on() -> None:
    """The stand-in is a transport; this names what the adapter needs of requests itself."""
    assert {"method", "url", "params", "data", "headers", "json", "timeout", "stream"} <= set(
        inspect.signature(requests.Session.request).parameters
    )
    assert "chunk_size" in inspect.signature(requests.Response.iter_content).parameters
    assert callable(requests.Response.__enter__)
    assert issubclass(requests.ConnectTimeout, (requests.ConnectionError, requests.Timeout))
    assert issubclass(requests.exceptions.SSLError, requests.ConnectionError)
    assert issubclass(requests.exceptions.JSONDecodeError, ValueError)
    for error in (requests.ConnectionError, requests.Timeout, requests.TooManyRedirects):
        assert issubclass(error, requests.RequestException)
    assert not issubclass(requests.exceptions.ChunkedEncodingError, requests.ConnectionError)
