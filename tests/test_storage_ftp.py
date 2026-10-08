"""FTPStorage: the storage contract against an FTP server held in memory.

The session is a real ``ftplib.FTP`` connected to the in-memory server of
``tests/ftp_stand_in.py``, so ftplib builds the commands, parses the replies and
raises its own exceptions. The server comes in the two kinds the adapter tells
apart: one that offers ``MLST`` / ``MLSD`` and one that has to be probed with
``CWD``, ``SIZE``, ``MDTM`` and ``NLST``.
"""

from __future__ import annotations

import errno
import ftplib  # nosec B402 - the sessions under test lead to an in-memory server
import inspect
import io
import posixpath
import re
import ssl
from pathlib import Path
from typing import Any

import pytest

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.remote.ftp.client import FTPClient, ftp_instance
from automation_file.storage import File, Storage, StorageBackend, StorageResolver
from automation_file.storage.ftp_storage import FTP_SCHEME, FTPS_SCHEME, FTPStorage, ftp_factory
from tests._insecure_fixtures import insecure_url
from tests.ftp_stand_in import MODIFIED, FakeFTP, FakeFTPS, FakeFTPServer
from tests.storage_contract import StorageContract

HOST = "files.example"


def ftp(rest: str) -> str:
    """Return the ``ftp`` URI of ``rest``.

    Assembled from parts, so that no clear-text scheme literal is written in this
    module (SonarCloud python:S5332). The URIs lead to the in-memory server.
    """
    return insecure_url(FTP_SCHEME, rest)


def connected(
    session: ftplib.FTP | None, host: str | None = HOST, port: int | None = 21
) -> FTPClient:
    """Return an ``FTPClient`` whose session is ``session``, as ``later_init`` leaves it."""
    client = FTPClient()
    client._ftp = session
    client._host = host
    client._port = port
    return client


def storage_on(server: FakeFTPServer, root: str = "/") -> FTPStorage:
    return FTPStorage(connected(FakeFTP(server)), root=root)


class TestFTPStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return storage_on(FakeFTPServer())


class TestFTPStorageWithoutMlstContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return storage_on(FakeFTPServer(mlst=False))


class TestRootedFTPStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        server = FakeFTPServer()
        server.mkdir("/srv")
        server.mkdir("/srv/data")
        server.write("/srv/keep.txt", b"keep")
        return storage_on(server, "/srv/data")


class TestRootedFTPStorageWithoutMlstContract(StorageContract):
    """The probed kind as vsftpd and older servers behave: paths from NLST, 550 when empty."""

    @pytest.fixture
    def backend(self) -> StorageBackend:
        server = FakeFTPServer(mlst=False, nlst_paths=True, empty_nlst_refused=True)
        server.mkdir("/home")
        server.mkdir("/srv")
        server.mkdir("/srv/data")
        server.write("/srv/keep.txt", b"keep")
        server.cwd = "/home"
        return storage_on(server, "/srv/data")


class TestFTPStorageThatCannotRenameOverAFileContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return storage_on(FakeFTPServer(rename_replaces=False))


@pytest.fixture
def server() -> FakeFTPServer:
    return FakeFTPServer()


@pytest.fixture
def storage(server: FakeFTPServer) -> FTPStorage:
    return storage_on(server)


@pytest.fixture
def plain_server() -> FakeFTPServer:
    """A server without MLST, whose client stands in a home directory."""
    server = FakeFTPServer(mlst=False)
    server.mkdir("/home")
    server.cwd = "/home"
    return server


@pytest.fixture
def shared(monkeypatch: pytest.MonkeyPatch, server: FakeFTPServer) -> FakeFTPServer:
    """Make a session with ``server`` the open session of the shared ``ftp_instance``."""
    monkeypatch.setattr(ftp_instance, "_ftp", FakeFTP(server))
    monkeypatch.setattr(ftp_instance, "_host", HOST)
    monkeypatch.setattr(ftp_instance, "_port", 21)
    return server


@pytest.fixture
def resolver() -> StorageResolver:
    table = StorageResolver()
    table.register_scheme(FTP_SCHEME, ftp_factory)
    table.register_scheme(FTPS_SCHEME, ftp_factory)
    return table


# ---------------------------------------------------------------------- a server with MLST


def test_stat_reads_the_facts_of_an_mlst_reply(storage: FTPStorage, server: FakeFTPServer) -> None:
    server.mkdir("/reports")
    server.write("/reports/q1 final.csv", b"a,b\n")
    info = storage.stat("reports/q1 final.csv")
    assert (info.path, info.is_dir, info.size) == ("reports/q1 final.csv", False, 4)
    assert info.modified_at == MODIFIED
    assert (info.etag, info.version, info.content_type, dict(info.metadata)) == (
        None,
        None,
        None,
        {},
    )
    directory = storage.stat("reports")
    assert (directory.is_dir, directory.size, directory.modified_at) == (True, None, MODIFIED)
    assert server.commands[-1] == "MLST /reports"
    assert storage.capabilities.to_dict() == {
        "directories": True,
        "modified_at": True,
        "etag": False,
        "version": False,
        "content_type": False,
        "metadata": False,
    }


def test_the_server_is_asked_for_its_features_once_for_each_session(server: FakeFTPServer) -> None:
    session = FakeFTP(server)
    client = connected(session)
    FTPStorage(client).write_bytes("a.txt", b"x")
    FTPStorage(client, root="/").list_dir()
    assert server.commands[:2] == ["FEAT", "OPTS MLST type;size;modify;"]
    assert server.verbs().count("FEAT") == 1
    FTPStorage(connected(FakeFTP(server))).exists("a.txt")
    assert server.verbs().count("FEAT") == 2
    assert not {"CWD", "PWD", "SIZE", "MDTM", "NLST"} & set(server.verbs())


def test_a_listing_skips_the_directory_itself_and_reads_a_link_as_a_file(
    storage: FTPStorage, server: FakeFTPServer
) -> None:
    server.mkdir("/dir")
    server.write("/dir/a.txt", b"abc")
    server.mkdir("/dir/sub")
    server.extra_listing = ["type=OS.unix=slink:/elsewhere;size=10;modify=20261008023015; link"]
    assert [(info.path, info.is_dir, info.size) for info in storage.list_dir("dir")] == [
        ("dir/a.txt", False, 3),
        ("dir/link", False, 10),
        ("dir/sub", True, None),
    ]


@pytest.mark.parametrize(
    "reply",
    ["250 Nothing to see", "250-Listing\ntype=file;size=3; /a.txt\n250 End"],
)
def test_an_mlst_reply_without_an_entry_line_is_an_error(
    storage: FTPStorage, server: FakeFTPServer, reply: str
) -> None:
    storage.exists("a.txt")
    server.refusals["MLST"] = reply
    with pytest.raises(StorageException) as caught:
        storage.stat("a.txt")
    assert type(caught.value) is StorageException
    assert isinstance(caught.value.__cause__, ftplib.error_reply)


def test_facts_a_server_leaves_out_stay_unknown(storage: FTPStorage, server: FakeFTPServer) -> None:
    storage.exists("a.txt")
    server.refusals["MLST"] = "250-Listing\n modify=2026; /a.txt\n250 End"
    info = storage.stat("a.txt")
    assert (info.is_dir, info.size, info.modified_at) == (False, None, None)


# ---------------------------------------------------------------------- a server without MLST


def test_a_server_without_mlst_is_probed(plain_server: FakeFTPServer) -> None:
    storage = storage_on(plain_server)
    plain_server.mkdir("/reports")
    plain_server.write("/reports/q1.csv", b"a,b\n")
    info = storage.stat("reports/q1.csv")
    assert (info.is_dir, info.size) == (False, 4)
    assert info.modified_at == MODIFIED.replace(microsecond=0)
    assert plain_server.commands == [
        "FEAT",
        "PWD",
        "TYPE I",
        "CWD /reports/q1.csv",
        "SIZE /reports/q1.csv",
        "MDTM /reports/q1.csv",
    ]
    plain_server.commands.clear()
    directory = storage.stat("reports")
    assert (directory.is_dir, directory.size, directory.modified_at) == (True, None, None)
    assert plain_server.commands == ["PWD", "TYPE I", "CWD /reports", "CWD /home"]
    assert storage.exists("reports/nope.csv") is False
    assert not {"MLST", "MLSD", "OPTS"} & set(plain_server.verbs())


def test_probing_puts_the_working_directory_back(plain_server: FakeFTPServer) -> None:
    storage = storage_on(plain_server)
    for path in ("dir/sub/a.txt", "dir/b.txt"):
        storage.write_bytes(path, b"x")
    assert [(info.path, info.is_dir) for info in storage.list_dir("dir")] == [
        ("dir/b.txt", False),
        ("dir/sub", True),
    ]
    storage.delete("dir", recursive=True)
    assert plain_server.cwd == "/home"
    assert plain_server.paths() == ["/home"]


def test_a_server_without_feat_is_probed() -> None:
    server = FakeFTPServer(mlst=False)
    server.refusals["FEAT"] = "502 Command not implemented."
    storage = storage_on(server)
    assert storage.write_bytes("a.txt", b"abc").size == 3
    assert "MLST" not in server.verbs()


def test_a_server_that_will_not_switch_the_facts_on_is_probed() -> None:
    server = FakeFTPServer()
    server.refusals["OPTS"] = "501 Option not understood."
    storage = storage_on(server)
    assert storage.write_bytes("a.txt", b"abc").size == 3
    assert "MLST" not in server.verbs()


def test_a_listed_name_the_server_will_not_describe_is_still_listed(
    plain_server: FakeFTPServer,
) -> None:
    storage = storage_on(plain_server)
    plain_server.write("/locked.bin", b"secret")
    plain_server.refusals["SIZE"] = "550 Permission denied."
    listed = {info.path: info for info in storage.list_dir()}
    assert (listed["locked.bin"].is_dir, listed["locked.bin"].size) == (False, None)
    assert listed["home"].is_dir is True
    assert storage.exists("locked.bin") is False


def test_a_server_without_mdtm_reports_no_modification_time(plain_server: FakeFTPServer) -> None:
    storage = storage_on(plain_server)
    plain_server.refusals["MDTM"] = "502 Command not implemented."
    info = storage.write_bytes("a.txt", b"abc")
    assert (info.size, info.modified_at) == (3, None)


# ---------------------------------------------------------------------- paths and URIs


def test_every_path_is_joined_to_the_root(server: FakeFTPServer) -> None:
    server.mkdir("/srv")
    server.mkdir("/srv/data")
    server.write("/srv/keep.txt", b"keep")
    rooted = storage_on(server, "srv//data/")
    assert rooted.root == "/srv/data"
    rooted.write_bytes("docs/a.txt", b"x")
    assert server.paths() == [
        "/srv",
        "/srv/data",
        "/srv/data/docs",
        "/srv/data/docs/a.txt",
        "/srv/keep.txt",
    ]
    assert [info.path for info in rooted.list_dir("", recursive=True)] == ["docs", "docs/a.txt"]
    assert rooted.uri_for("docs/a.txt") == ftp("files.example/srv/data/docs/a.txt")
    rooted.delete("docs", recursive=True)
    assert server.paths() == ["/srv", "/srv/data", "/srv/keep.txt"]
    with pytest.raises(StorageURIException):
        storage_on(server, "/srv/../etc")


@pytest.mark.parametrize("path", ["a.txt\r\nDELE /b.txt", "dir/a\nb.txt", "a\r.txt"])
def test_a_path_with_a_line_break_is_refused(
    storage: FTPStorage, server: FakeFTPServer, path: str
) -> None:
    for call in (storage.exists, storage.delete, lambda name: storage.write_bytes(name, b"x")):
        with pytest.raises(StorageURIException, match="line break"):
            call(path)
    with pytest.raises(StorageURIException, match="line break"):
        storage_on(server, "/srv\r\nDELE /b.txt")
    assert server.commands == []


def test_uri_for_names_the_host_of_the_session(server: FakeFTPServer) -> None:
    session = FakeFTP(server)
    assert FTPStorage(connected(session)).uri_for("data/a.txt") == ftp("files.example/data/a.txt")
    assert FTPStorage(connected(session)).uri_for("") == ftp("files.example")
    assert FTPStorage(connected(session, port=2121)).uri_for("a.txt") == (
        ftp("files.example:2121/a.txt")
    )
    assert FTPStorage(connected(FakeFTPS(server))).uri_for("a.txt") == "ftps://files.example/a.txt"
    assert FTPStorage(connected(None, host=None, port=None)).uri_for("a.txt") == ftp("/a.txt")


def test_equality_and_repr(server: FakeFTPServer) -> None:
    client = connected(FakeFTP(server))
    assert FTPStorage(client) == FTPStorage(client)
    assert FTPStorage(client) != FTPStorage(client, root="/srv")
    assert FTPStorage(client) != FTPStorage(connected(FakeFTP(server)))
    assert FTPStorage() == FTPStorage(ftp_instance)
    assert len({FTPStorage(client), FTPStorage(client, root="/")}) == 1
    assert repr(FTPStorage(client, root="srv/data")) == "FTPStorage(root='/srv/data')"
    assert FTPStorage().client is ftp_instance


# ---------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    "reply,expected,cause",
    [
        ("530 Please login with USER and PASS.", StoragePermissionException, ftplib.error_perm),
        (
            "421 Service not available, closing control connection.",
            StorageTransientException,
            ftplib.error_temp,
        ),
        ("450 Requested file action not taken.", StorageTransientException, ftplib.error_temp),
        ("350 Unexpected", StorageException, ftplib.error_reply),
        ("999 Not a reply", StorageException, ftplib.error_proto),
    ],
)
def test_replies_become_storage_errors(
    storage: FTPStorage,
    server: FakeFTPServer,
    reply: str,
    expected: type[Exception],
    cause: type[Exception],
) -> None:
    server.write("/a.txt", b"x")
    assert storage.exists("a.txt") is True
    server.refusals["DELE"] = reply
    with pytest.raises(expected) as caught:
        storage.delete("a.txt")
    assert type(caught.value) is expected
    assert type(caught.value.__cause__) is cause
    assert str(caught.value.__cause__) == reply
    assert ftp("files.example/a.txt") in str(caught.value)


@pytest.mark.parametrize(
    "error,expected",
    [
        (TimeoutError("timed out"), StorageTransientException),
        (ConnectionResetError(errno.ECONNRESET, "reset by peer"), StorageTransientException),
        (BrokenPipeError(errno.EPIPE, "broken pipe"), StorageTransientException),
        (ssl.SSLError("decryption failed"), StorageException),
        (OSError("unexpected"), StorageException),
    ],
)
def test_connection_errors_become_storage_errors(
    storage: FTPStorage, server: FakeFTPServer, error: Exception, expected: type[Exception]
) -> None:
    server.send_error = error
    with pytest.raises(expected) as caught:
        storage.stat("a.txt")
    assert type(caught.value) is expected
    assert caught.value.__cause__ is error


@pytest.mark.parametrize("mlst", [True, False])
def test_a_name_in_another_encoding_is_a_storage_error(mlst: bool) -> None:
    server = FakeFTPServer(mlst=mlst)
    storage = storage_on(server)
    server.raw_listing = b"caf\xe9.txt\r\n"
    with pytest.raises(StorageException) as caught:
        storage.list_dir()
    assert type(caught.value) is StorageException
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)


def test_a_closed_connection_is_transient(storage: FTPStorage, server: FakeFTPServer) -> None:
    server.hung_up = True
    with pytest.raises(StorageTransientException) as caught:
        storage.list_dir()
    assert isinstance(caught.value.__cause__, EOFError)


def test_550_means_absent_in_a_lookup_and_refused_elsewhere(
    storage: FTPStorage, server: FakeFTPServer
) -> None:
    assert storage.exists("nope.txt") is False
    with pytest.raises(StorageNotFoundException, match=re.escape(ftp("files.example/nope"))):
        storage.list_dir("nope")
    server.write("/a.txt", b"x")
    for verb in ("DELE", "RETR"):
        server.refusals[verb] = "550 Permission denied."
    with pytest.raises(StoragePermissionException, match=r"denied \(550\)"):
        storage.delete("a.txt")
    with pytest.raises(StoragePermissionException):
        storage.read_bytes("a.txt")
    server.refusals["MLST"] = "550 Permission denied."
    assert storage.exists("a.txt") is False


def test_another_refusal_in_a_lookup_is_not_read_as_absent(
    storage: FTPStorage, server: FakeFTPServer, plain_server: FakeFTPServer
) -> None:
    refusal = "530 Please login with USER and PASS."
    storage.exists("a.txt")
    server.refusals["MLST"] = refusal
    with pytest.raises(StoragePermissionException, match=r"denied \(530\)"):
        storage.exists("a.txt")

    probed = storage_on(plain_server)
    plain_server.write("/a.txt", b"x")
    for verb in ("CWD", "SIZE", "NLST"):
        plain_server.refusals = {verb: refusal}
        with pytest.raises(StoragePermissionException, match=r"denied \(530\)"):
            probed.list_dir()


def test_a_session_must_be_open(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(StorageUnavailableException, match="later_init"):
        FTPStorage(FTPClient()).exists("a.txt")
    monkeypatch.setattr(ftp_instance, "_ftp", None)
    with pytest.raises(StorageUnavailableException, match="later_init") as caught:
        FTPStorage().write_bytes("a.txt", b"x")
    assert type(caught.value.__cause__).__name__ == "FTPException"


# ---------------------------------------------------------------------- uploads and moves


def test_an_upload_arrives_under_a_part_name_and_is_renamed(
    storage: FTPStorage, server: FakeFTPServer
) -> None:
    storage.write_bytes("a.txt", b"payload")
    stor, rename_from, rename_to = [
        command for command in server.commands if command[:4] in ("STOR", "RNFR", "RNTO")
    ]
    partial = stor.removeprefix("STOR ")
    assert posixpath.dirname(partial) == "/"
    assert posixpath.basename(partial).startswith(".a.txt.")
    assert partial.endswith(".part")
    assert (rename_from, rename_to) == (f"RNFR {partial}", "RNTO /a.txt")
    assert server.paths() == ["/a.txt"]


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("426 Connection closed; transfer aborted.", StorageTransientException),
        (
            "552 Requested file action aborted. Exceeded storage allocation.",
            StoragePermissionException,
        ),
    ],
)
def test_a_failed_upload_leaves_no_partial_file_and_keeps_the_target(
    storage: FTPStorage, server: FakeFTPServer, reply: str, expected: type[Exception]
) -> None:
    server.write("/a.txt", b"old")
    server.transfer_error = reply
    with pytest.raises(expected) as caught:
        storage.write_bytes("a.txt", b"new and longer")
    assert str(caught.value.__cause__) == reply
    assert server.verbs()[-1] == "DELE"
    assert server.paths() == ["/a.txt"]
    assert server.read("/a.txt") == b"old"


def test_a_refused_rename_leaves_no_partial_file_and_keeps_the_target(
    storage: FTPStorage, server: FakeFTPServer
) -> None:
    server.write("/a.txt", b"old")
    server.refusals["RNFR"] = "550 Permission denied."
    with pytest.raises(StoragePermissionException) as caught:
        storage.write_bytes("a.txt", b"new")
    assert str(caught.value.__cause__) == "550 Permission denied."
    assert server.paths() == ["/a.txt"]
    assert server.read("/a.txt") == b"old"


def test_the_upload_error_is_reported_when_the_cleanup_fails_too(
    storage: FTPStorage, server: FakeFTPServer
) -> None:
    server.transfer_error = "426 Connection closed; transfer aborted."
    server.refusals["DELE"] = "421 Timeout."
    with pytest.raises(StorageTransientException) as caught:
        storage.write_bytes("a.txt", b"payload")
    assert str(caught.value.__cause__) == server.transfer_error
    assert [posixpath.basename(path)[:7] for path in server.paths()] == [".a.txt."]


@pytest.fixture
def strict_server() -> FakeFTPServer:
    """A server that will not rename onto an existing file, as FTP servers on Windows do."""
    return FakeFTPServer(rename_replaces=False)


def test_a_server_that_will_not_rename_over_a_file_has_it_moved_aside(
    strict_server: FakeFTPServer,
) -> None:
    storage = storage_on(strict_server)
    storage.write_bytes("a.txt", b"first")
    assert "DELE" not in strict_server.verbs()
    strict_server.commands.clear()
    storage.write_bytes("a.txt", b"second")
    commands = strict_server.commands
    partial = next(c for c in commands if c.startswith("STOR ")).removeprefix("STOR ")
    aside = next(c for c in commands if c.endswith(".old")).removeprefix("RNTO ")
    assert posixpath.basename(aside).startswith(".a.txt.")
    assert commands[commands.index(f"RNFR {partial}") :] == [
        f"RNFR {partial}",
        "RNTO /a.txt",
        "RNFR /a.txt",
        f"RNTO {aside}",
        f"RNFR {partial}",
        "RNTO /a.txt",
        f"DELE {aside}",
        "MLST /a.txt",
    ]
    assert strict_server.paths() == ["/a.txt"]
    assert strict_server.read("/a.txt") == b"second"


def test_a_rename_refused_for_another_reason_keeps_the_target(
    storage: FTPStorage, server: FakeFTPServer
) -> None:
    server.refusals["RNTO"] = "553 Rename not allowed."
    with pytest.raises(StoragePermissionException) as caught:
        storage.write_bytes("new.txt", b"payload")
    assert str(caught.value.__cause__) == "553 Rename not allowed."
    assert server.paths() == []

    server.write("/a.txt", b"old")
    with pytest.raises(StoragePermissionException) as caught:
        storage.write_bytes("a.txt", b"payload")
    assert str(caught.value.__cause__) == "553 Rename not allowed."
    assert server.paths() == ["/a.txt"]
    assert server.read("/a.txt") == b"old"

    server.write("/b.txt", b"other")
    server.refusals = {"RNFR": "550 RNFR command failed."}
    with pytest.raises(StoragePermissionException):
        storage.move_from(storage, "b.txt", "a.txt")
    assert (server.read("/a.txt"), server.read("/b.txt")) == (b"old", b"other")
    assert "DELE" not in server.verbs()[-4:]


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("553 Could not rename.", StoragePermissionException),
        ("451 Requested action aborted: local error in processing.", StorageTransientException),
    ],
)
def test_the_old_file_is_put_back_when_the_rename_still_fails(
    strict_server: FakeFTPServer, reply: str, expected: type[Exception]
) -> None:
    storage = storage_on(strict_server)
    strict_server.write("/a.txt", b"old")
    # RNTO: onto the file (refused), the file aside, onto the freed name, the file back.
    strict_server.answer_the_nth("RNTO", 3, reply)
    with pytest.raises(expected) as caught:
        storage.write_bytes("a.txt", b"new")
    assert str(caught.value.__cause__) == reply
    assert strict_server.verbs().count("RNTO") == 4
    assert strict_server.paths() == ["/a.txt"]
    assert strict_server.read("/a.txt") == b"old"


def test_the_old_content_stays_aside_when_it_cannot_be_put_back(
    strict_server: FakeFTPServer,
) -> None:
    storage = storage_on(strict_server)
    strict_server.write("/a.txt", b"old")
    for ordinal in (3, 4):
        strict_server.answer_the_nth("RNTO", ordinal, "553 Could not rename.")
    with pytest.raises(StoragePermissionException):
        storage.write_bytes("a.txt", b"new")
    (aside,) = strict_server.paths()
    assert posixpath.basename(aside).startswith(".a.txt.")
    assert aside.endswith(".old")
    assert strict_server.read(aside) == b"old"


def test_a_move_within_one_session_is_a_rename(storage: FTPStorage, server: FakeFTPServer) -> None:
    storage.write_bytes("a.txt", b"payload")
    server.commands.clear()
    info = storage.move_from(storage, "a.txt", "moved/b.txt")
    assert (info.path, info.size) == ("moved/b.txt", 7)
    assert server.commands[-3:-1] == ["RNFR /a.txt", "RNTO /moved/b.txt"]
    assert not {"RETR", "STOR", "DELE"} & set(server.verbs())
    assert server.paths() == ["/moved", "/moved/b.txt"]

    archive = FTPStorage(storage.client, root="/moved")
    archive.move_from(storage, "moved/b.txt", "c.txt")
    assert server.paths() == ["/moved", "/moved/c.txt"]
    with pytest.raises(StorageException, match="same file"):
        archive.move_from(storage, "moved/c.txt", "c.txt")
    assert server.read("/moved/c.txt") == b"payload"


def test_a_move_between_two_sessions_is_copy_then_delete(
    storage: FTPStorage, server: FakeFTPServer
) -> None:
    other_server = FakeFTPServer()
    other = FTPStorage(connected(FakeFTP(other_server), host="backup.example"))
    storage.write_bytes("a.txt", b"payload")
    other.move_from(storage, "a.txt", "a.txt")
    assert other_server.read("/a.txt") == b"payload"
    assert server.paths() == []
    assert "RETR" in server.verbs()


def test_mkdir_accepts_a_directory_that_appeared_meanwhile(
    storage: FTPStorage, server: FakeFTPServer
) -> None:
    server.mkdir("/dir")
    storage._mkdir("dir")
    server.write("/a.txt", b"x")
    with pytest.raises(StoragePermissionException):
        storage._mkdir("a.txt")


# ---------------------------------------------------------------------- symbolic links


@pytest.fixture(params=[True, False], ids=["mlst", "probed"])
def linked(request: pytest.FixtureRequest) -> tuple[FTPStorage, FakeFTPServer]:
    """``/data`` with a link to a file and a link to a directory outside it, on both kinds."""
    server = FakeFTPServer(mlst=request.param)
    storage = storage_on(server)
    for path in ("outside/keep.txt", "data/real.txt"):
        storage.write_bytes(path, b"content")
    server.link("/data/file-link", "real.txt")
    server.link("/data/dir-link", "/outside")
    return storage, server


def test_reading_follows_a_link(linked: tuple[FTPStorage, FakeFTPServer]) -> None:
    storage, _ = linked
    assert storage.read_bytes("data/file-link") == b"content"
    assert storage.read_bytes("data/dir-link/keep.txt") == b"content"
    assert [info.name for info in storage.list_dir("data")] == [
        "dir-link",
        "file-link",
        "real.txt",
    ]


def test_deleting_never_follows_a_link(linked: tuple[FTPStorage, FakeFTPServer]) -> None:
    storage, server = linked
    storage.delete("data/dir-link", recursive=True)
    assert "/data/dir-link" not in server.entries
    assert server.read("/outside/keep.txt") == b"content"
    storage.delete("data/file-link")
    assert server.read("/data/real.txt") == b"content"

    server.link("/data/dir-link", "/outside")
    storage.delete("data", recursive=True)
    assert server.paths() == ["/outside", "/outside/keep.txt"]


def test_a_recursive_delete_asks_for_no_more_than_it_needs() -> None:
    server = FakeFTPServer(mlst=False)
    storage = storage_on(server)
    for path in ("dir/a.txt", "dir/sub/b.txt"):
        storage.write_bytes(path, b"x")
    server.commands.clear()
    storage.delete("dir", recursive=True)
    assert server.commands[server.commands.index("DELE /dir") :] == [
        "DELE /dir",
        "TYPE A",
        "NLST /dir",
        "DELE /dir/a.txt",
        "DELE /dir/sub",
        "TYPE A",
        "NLST /dir/sub",
        "DELE /dir/sub/b.txt",
        "RMD /dir/sub",
        "RMD /dir",
    ]
    assert server.paths() == []


# ---------------------------------------------------------------------- ftp:// and ftps:// URIs


def test_ftp_uris_use_the_shared_session(
    shared: FakeFTPServer, resolver: StorageResolver, tmp_path: Path
) -> None:
    report = File(ftp("files.example/reports/q1.csv"), resolver=resolver)
    report.write(b"a,b\n")
    assert shared.read("/reports/q1.csv") == b"a,b\n"
    assert resolver.resolve(ftp("files.example/reports/q1.csv")) == (
        FTPStorage(),
        "reports/q1.csv",
    )
    report.copy_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    File(tmp_path / "q1.csv", resolver=resolver).move_to(ftp("/archive/2026/q1.csv"))
    assert shared.read("/archive/2026/q1.csv") == b"a,b\n"
    archive = Storage(ftp("files.example/archive"), resolver=resolver)
    assert [info.path for info in archive.list_dir(recursive=True)] == ["2026", "2026/q1.csv"]
    archive.delete("2026", recursive=True)
    assert shared.paths() == ["/archive", "/reports", "/reports/q1.csv"]


@pytest.mark.parametrize(
    "uri",
    [
        ftp("/data/a.txt"),
        ftp("files.example/data/a.txt"),
        ftp("FILES.example/data/a.txt"),
        ftp("files.example:21/data/a.txt"),
    ],
)
def test_a_uri_may_name_no_host_or_the_connected_one(
    shared: FakeFTPServer, resolver: StorageResolver, uri: str
) -> None:
    assert resolver.resolve(uri) == (FTPStorage(), "data/a.txt")


@pytest.mark.parametrize(
    "uri,named",
    [
        (ftp("backup.example/data/a.txt"), "backup.example"),
        (ftp("files.example:2121/data/a.txt"), "files.example:2121"),
    ],
)
def test_a_uri_for_another_host_is_refused(
    shared: FakeFTPServer, resolver: StorageResolver, uri: str, named: str
) -> None:
    with pytest.raises(StorageURIException) as caught:
        resolver.resolve(uri)
    message = str(caught.value)
    assert repr(named) in message
    assert "'files.example:21'" in message
    assert f'Storage.mount("ftp://{named}", FTPStorage(client))' in message


def test_ftps_needs_an_ftps_session(
    shared: FakeFTPServer, resolver: StorageResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ftp_instance.tls is False
    for uri in ("ftps://files.example/data/a.txt", "ftps:///data/a.txt"):
        with pytest.raises(StorageURIException, match="tls=True"):
            resolver.resolve(uri)
    with pytest.raises(StorageURIException, match=re.escape("backup.example")):
        resolver.resolve("ftps://backup.example/data/a.txt")

    monkeypatch.setattr(ftp_instance, "_ftp", FakeFTPS(shared))
    assert ftp_instance.tls is True
    for uri in ("ftps://files.example/data/a.txt", "ftps:///data/a.txt", ftp("/data/a.txt")):
        assert resolver.resolve(uri) == (FTPStorage(), "data/a.txt")
    File("ftps://files.example/data/a.txt", resolver=resolver).write(b"x")
    assert shared.read("/data/a.txt") == b"x"
    assert resolver.resolve("ftps:///data/a.txt")[0].uri_for("data/a.txt") == (
        "ftps://files.example/data/a.txt"
    )


def test_any_host_resolves_until_a_session_is_open(
    monkeypatch: pytest.MonkeyPatch, resolver: StorageResolver
) -> None:
    for name in ("_ftp", "_host", "_port"):
        monkeypatch.setattr(ftp_instance, name, None)
    for uri in (ftp("anywhere.example/data/a.txt"), "ftps://anywhere.example/data/a.txt"):
        backend, path = resolver.resolve(uri)
        assert (backend, path) == (FTPStorage(), "data/a.txt")
        with pytest.raises(StorageUnavailableException, match="later_init"):
            backend.exists(path)


def test_another_host_is_reached_through_a_mount(
    shared: FakeFTPServer, resolver: StorageResolver
) -> None:
    backup = FakeFTPServer()
    resolver.mount(
        ftp("backup.example"), FTPStorage(connected(FakeFTP(backup), host="backup.example"))
    )
    File(ftp("files.example/a.txt"), resolver=resolver).write(b"payload")
    File(ftp("files.example/a.txt"), resolver=resolver).copy_to(
        File(ftp("backup.example/copies/a.txt"), resolver=resolver)
    )
    assert backup.read("/copies/a.txt") == b"payload"
    assert shared.paths() == ["/a.txt"]


# ---------------------------------------------------------------------- the real ftplib


@pytest.mark.parametrize(
    "method,arguments",
    [
        ("sendcmd", ("MLST /a",)),
        ("voidcmd", ("TYPE I",)),
        ("mlsd", ("/a",)),
        ("nlst", ("/a",)),
        ("size", ("/a",)),
        ("pwd", ()),
        ("cwd", ("/a",)),
        ("storbinary", ("STOR /a", io.BytesIO())),
        ("retrbinary", ("RETR /a", print)),
        ("delete", ("/a",)),
        ("mkd", ("/a",)),
        ("rmd", ("/a",)),
        ("rename", ("/a", "/b")),
    ],
)
def test_ftplib_has_the_calls_the_adapter_makes(method: str, arguments: tuple[Any, ...]) -> None:
    for session_type in (ftplib.FTP, ftplib.FTP_TLS):
        inspect.signature(getattr(session_type, method)).bind(None, *arguments)


def test_ftplib_has_the_seams_the_stand_in_replaces() -> None:
    assert list(inspect.signature(ftplib.FTP.ntransfercmd).parameters) == ["self", "cmd", "rest"]
    assert list(inspect.signature(ftplib.FTP.putline).parameters) == ["self", "line"]
    assert list(inspect.signature(ftplib.FTP.getline).parameters) == ["self"]
    session = ftplib.FTP()  # nosec B321 - never connected: only its attributes are read
    assert (session.sock, session.file, session.encoding) == (None, None, "utf-8")
    assert ftplib.error_perm("550 No such file").args[0][:3] == "550"
    for error in (ftplib.error_perm, ftplib.error_temp, ftplib.error_reply, ftplib.error_proto):
        assert issubclass(error, ftplib.Error)
        assert not issubclass(error, OSError)
