"""``copy_between`` on the storage layer: storage URIs, the older spellings, and what fails how."""

# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=unused-argument  # a fixture is requested for its effect; a stand-in keeps the real signature

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from automation_file import CrossBackendException, Storage, copy_between, execute_action
from automation_file.exceptions import StorageUnavailableException
from automation_file.remote import cross_backend
from automation_file.storage import MemoryStorage, clear_memory_stores, memory_store, observe
from automation_file.storage.types import FileInfo

MOUNTS = ("s3://legacy-bucket", "azure://legacy-container", "dropbox://", "vault://down")


class _Unavailable(MemoryStorage):
    """A backend whose client was never initialised."""

    def _stat(self, path: str) -> FileInfo | None:
        raise StorageUnavailableException("the vault client is not initialised")


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    clear_memory_stores()
    yield
    for prefix in MOUNTS:
        Storage.unmount(prefix)
    clear_memory_stores()


def test_storage_uris_of_any_scheme_are_copied(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    assert copy_between(str(source), "memory://xb/in/a.bin") is True
    assert copy_between("memory://xb/in/a.bin", "memory://xb/out/b.bin") is True
    assert copy_between("memory://xb/out/b.bin", f"local:{tmp_path / 'back' / 'c.bin'}") is True
    assert (tmp_path / "back" / "c.bin").read_bytes() == b"payload"


def test_an_existing_target_is_replaced(tmp_path: Path) -> None:
    store = memory_store("xb")
    store.write_bytes("a.txt", b"new")
    store.write_bytes("b.txt", b"old")
    assert copy_between("memory://xb/a.txt", "memory://xb/b.txt") is True
    assert store.read_bytes("b.txt") == b"new"


def test_a_local_path_may_contain_parent_segments(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    roundabout = tmp_path / "sub" / ".." / "a.bin"
    assert copy_between(str(roundabout), str(tmp_path / "sub" / ".." / "b.bin")) is True
    assert (tmp_path / "b.bin").read_bytes() == b"x"


def test_the_copy_is_a_storage_operation_others_can_observe() -> None:
    memory_store("xb").write_bytes("a.txt", b"x")
    seen: list[observe.StorageOperation] = []
    observe.add_listener(seen.append)
    try:
        assert copy_between("memory://xb/a.txt", "memory://xb/b.txt") is True
    finally:
        observe.remove_listener(seen.append)
    copies = [operation for operation in seen if operation.operation == "copy"]
    assert [(operation.uri, operation.status) for operation in copies] == [
        ("memory://xb/b.txt", "ok")
    ]


@pytest.mark.parametrize(
    "spelling",
    ["s3://legacy-bucket/reports/q1.csv", "s3:legacy-bucket/reports/q1.csv"],
)
def test_both_s3_spellings_reach_the_bucket(spelling: str) -> None:
    bucket = MemoryStorage()
    Storage.mount("s3://legacy-bucket", bucket)
    memory_store("xb").write_bytes("q1.csv", b"1,2")
    assert copy_between("memory://xb/q1.csv", spelling) is True
    assert bucket.read_bytes("reports/q1.csv") == b"1,2"
    assert copy_between(spelling, "memory://xb/back.csv") is True
    assert memory_store("xb").read_bytes("back.csv") == b"1,2"


def test_az_and_dropbox_spellings_are_translated() -> None:
    container, dropbox = MemoryStorage(), MemoryStorage()
    Storage.mount("azure://legacy-container", container)
    Storage.mount("dropbox://", dropbox)
    memory_store("xb").write_bytes("a.txt", b"x")
    assert copy_between("memory://xb/a.txt", "az://legacy-container/docs/a.txt") is True
    assert container.read_bytes("docs/a.txt") == b"x"
    assert copy_between("memory://xb/a.txt", "dropbox:/team/a.txt") is True
    assert dropbox.read_bytes("team/a.txt") == b"x"


def test_a_bucket_location_needs_a_key() -> None:
    memory_store("xb").write_bytes("a.txt", b"x")
    with pytest.raises(CrossBackendException, match="<container>/<key>"):
        copy_between("memory://xb/a.txt", "s3://legacy-bucket")


@pytest.mark.parametrize("scheme", ["sftp", "ftp"])
def test_one_slash_means_relative_to_the_login_directory(
    monkeypatch: pytest.MonkeyPatch, scheme: str
) -> None:
    home = MemoryStorage()
    asked: list[str] = []

    def _login_directory(name: str) -> MemoryStorage:
        asked.append(name)
        return home

    monkeypatch.setattr(cross_backend, "_in_login_directory", _login_directory)
    memory_store("xb").write_bytes("a.txt", b"x")
    assert copy_between("memory://xb/a.txt", f"{scheme}:/inbox/a.txt") is True
    assert copy_between("memory://xb/a.txt", f"{scheme}:inbox/b.txt") is True
    assert sorted(info.path for info in home.list_dir("inbox")) == ["inbox/a.txt", "inbox/b.txt"]
    assert asked == [scheme, scheme]


def test_the_login_directory_is_asked_of_the_open_session(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("paramiko")
    from automation_file.remote.sftp.client import sftp_instance

    session = SimpleNamespace(normalize=lambda path: "/home/ops" if path == "." else path)
    monkeypatch.setattr(sftp_instance, "require_sftp", lambda: session)
    backend: Any = cross_backend._in_login_directory("sftp")
    assert backend.root == "/home/ops"


def test_a_session_that_is_not_open_is_reported_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from automation_file.remote.ftp.client import ftp_instance

    monkeypatch.setattr(ftp_instance, "_ftp", None)
    memory_store("xb").write_bytes("a.txt", b"x")
    with pytest.raises(StorageUnavailableException, match="not initialised"):
        copy_between("memory://xb/a.txt", "ftp:/inbox/a.txt")


def test_two_slashes_name_a_host_and_go_to_the_storage_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def _resolve(uri: str, role: str) -> tuple[MemoryStorage, str]:
        seen.append(uri)
        return memory_store("xb"), "a.txt" if role == "source" else "landed.txt"

    monkeypatch.setattr(cross_backend, "_resolve", _resolve)
    memory_store("xb").write_bytes("a.txt", b"x")
    assert copy_between("memory://xb/a.txt", "sftp://nas.example/srv/a.txt") is True
    assert seen == ["sftp://nas.example/srv/a.txt", "memory://xb/a.txt"]


def test_an_http_source_is_fetched_with_the_validated_downloader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[str] = []

    def _download(url: str, target: str) -> bool:
        fetched.append(url)
        Path(target).write_bytes(b"from the web")
        return True

    monkeypatch.setattr("automation_file.remote.http_download.download_file", _download)
    assert copy_between("https://example.org/a.bin", "memory://xb/web/a.bin") is True
    assert fetched == ["https://example.org/a.bin"]
    assert memory_store("xb").read_bytes("web/a.bin") == b"from the web"


def test_a_refused_download_is_false_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "automation_file.remote.http_download.download_file", lambda url, target: False
    )
    assert copy_between("https://example.org/a.bin", "memory://xb/web/a.bin") is False
    assert not memory_store("xb").exists("web/a.bin")


def test_http_is_never_a_target() -> None:
    memory_store("xb").write_bytes("a.txt", b"x")
    with pytest.raises(CrossBackendException, match="unknown target backend: 'https'"):
        copy_between("memory://xb/a.txt", "https://example.org/upload")


def test_a_failed_transfer_is_false_and_an_uninitialised_backend_raises() -> None:
    assert copy_between("memory://xb/absent.txt", "memory://xb/b.txt") is False
    memory_store("xb").write_bytes("a.txt", b"x")
    assert copy_between("memory://xb/a.txt", "memory://xb/a.txt") is False
    assert memory_store("xb").read_bytes("a.txt") == b"x"
    Storage.mount("vault://down", _Unavailable())
    with pytest.raises(StorageUnavailableException, match="not initialised"):
        copy_between("vault://down/a.txt", "memory://xb/b.txt")


def test_the_action_takes_the_same_locations() -> None:
    memory_store("xb").write_bytes("a.txt", b"x")
    results = execute_action(
        [["FA_copy_between", {"source": "memory://xb/a.txt", "target": "memory://xb/b.txt"}]]
    )
    assert list(results.values()) == [True]
    assert memory_store("xb").read_bytes("b.txt") == b"x"
