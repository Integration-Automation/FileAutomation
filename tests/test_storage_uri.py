"""Storage URI syntax: parsing, normalisation, and what is rejected."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from automation_file.exceptions import StorageURIException
from automation_file.storage import (
    StorageURI,
    local_path_to_uri,
    normalize_path,
    parse_storage_uri,
)

_WINDOWS = os.sep == "\\"


@pytest.mark.parametrize(
    "text,scheme,authority,path",
    [
        ("local:///data/report.csv", "local", "", "data/report.csv"),
        ("local:///C:/data/report.csv", "local", "", "C:/data/report.csv"),
        ("s3://bucket/report.csv", "s3", "bucket", "report.csv"),
        ("s3://bucket", "s3", "bucket", ""),
        ("s3://bucket/", "s3", "bucket", ""),
        ("azure://container/dir/report.csv", "azure", "container", "dir/report.csv"),
        ("gdrive://folder/report.csv", "gdrive", "folder", "report.csv"),
        ("dropbox:///reports/report.csv", "dropbox", "", "reports/report.csv"),
        ("sftp://server/data/report.csv", "sftp", "server", "data/report.csv"),
        ("sftp://server:2222/data/report.csv", "sftp", "server:2222", "data/report.csv"),
        ("ftp://server/data/report.csv", "ftp", "server", "data/report.csv"),
        ("webdav://server/files/report.csv", "webdav", "server", "files/report.csv"),
        ("smb://server/share/report.csv", "smb", "server", "share/report.csv"),
        ("memory://scratch/a.txt", "memory", "scratch", "a.txt"),
    ],
)
def test_parse_splits_scheme_authority_and_path(
    text: str, scheme: str, authority: str, path: str
) -> None:
    uri = parse_storage_uri(text)
    assert (uri.scheme, uri.authority, uri.path) == (scheme, authority, path)


@pytest.mark.parametrize(
    "text",
    [
        "local:///data/report.csv",
        "local:///",
        "s3://bucket/report.csv",
        "s3://bucket",
        "sftp://server:2222/data/report.csv",
        "dropbox:///reports/report.csv",
    ],
)
def test_str_round_trips(text: str) -> None:
    assert str(parse_storage_uri(text)) == text
    assert parse_storage_uri(str(parse_storage_uri(text))) == parse_storage_uri(text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("S3://bucket/Key.CSV", "s3://bucket/Key.CSV"),
        ("file:///data/a.txt", "local:///data/a.txt"),
        ("az://container/blob", "azure://container/blob"),
        ("AZ://Container/Blob", "azure://Container/Blob"),
    ],
)
def test_scheme_is_lower_cased_and_aliases_resolve(text: str, expected: str) -> None:
    assert str(parse_storage_uri(text)) == expected


def test_the_path_is_taken_literally() -> None:
    uri = parse_storage_uri("s3://bucket/reports/Q1 #3?.csv%20")
    assert uri.path == "reports/Q1 #3?.csv%20"
    assert uri.name == "Q1 #3?.csv%20"


def test_unicode_paths_are_kept() -> None:
    assert parse_storage_uri("s3://bucket/資料/報告.csv").path == "資料/報告.csv"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("", ""),
        ("/", ""),
        ("a/b", "a/b"),
        ("/a/b/", "a/b"),
        ("a//b", "a/b"),
        ("./a/./b/.", "a/b"),
        ("a/...", "a/..."),
        ("a/..b/c..", "a/..b/c.."),
    ],
)
def test_normalize_path(path: str, expected: str) -> None:
    assert normalize_path(path) == expected


@pytest.mark.parametrize("path", ["..", "../a", "a/../b", "a/b/..", "/../etc/passwd"])
def test_normalize_path_rejects_parent_segments(path: str) -> None:
    with pytest.raises(StorageURIException, match=r"'\.\.'"):
        normalize_path(path)


def test_normalize_path_rejects_nul() -> None:
    with pytest.raises(StorageURIException, match="NUL"):
        normalize_path("a\x00b")


@pytest.mark.parametrize("text", ["s3://bucket/../other", "local:///data/../../etc/passwd"])
def test_parse_rejects_parent_segments(text: str) -> None:
    with pytest.raises(StorageURIException):
        parse_storage_uri(text)


@pytest.mark.parametrize("text", ["", "   "])
def test_parse_rejects_empty_text(text: str) -> None:
    with pytest.raises(StorageURIException, match="empty"):
        parse_storage_uri(text)


def test_parse_rejects_bytes() -> None:
    raw: Any = b"s3://bucket/key"
    with pytest.raises(StorageURIException, match="bytes"):
        parse_storage_uri(raw)


@pytest.mark.parametrize(
    "text",
    ["sftp://user@server/data", "sftp://user:secret@server/data", "s3://key:secret@bucket/k"],
)
def test_parse_rejects_credentials_without_echoing_them(text: str) -> None:
    with pytest.raises(StorageURIException, match="credentials") as caught:
        parse_storage_uri(text)
    assert "secret" not in str(caught.value)
    assert "user" not in str(caught.value).replace("user information", "")


@pytest.mark.parametrize("text", ["s3://bad bucket/key", "sftp://ser\\ver/data"])
def test_parse_rejects_a_malformed_authority(text: str) -> None:
    with pytest.raises(StorageURIException, match="authority"):
        parse_storage_uri(text)


@pytest.mark.parametrize(
    "text,spelling",
    [
        ("sftp:/remote/a.csv", "sftp://"),
        ("s3:bucket/key", "s3://"),
        ("local:C:\\data\\a.csv", "local://"),
        ("backup:2026.tar", "./backup:2026.tar"),
    ],
)
def test_scheme_like_text_without_slashes_is_ambiguous(text: str, spelling: str) -> None:
    with pytest.raises(StorageURIException, match="ambiguous") as caught:
        parse_storage_uri(text)
    assert spelling in str(caught.value)


def test_a_relative_path_becomes_an_absolute_local_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    uri = parse_storage_uri("reports/a.csv")
    assert uri.scheme == "local"
    assert uri == local_path_to_uri(tmp_path / "reports" / "a.csv")
    assert uri.path.endswith("reports/a.csv")


def test_a_dot_prefix_names_a_local_file_with_a_colon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert parse_storage_uri("./backup:2026.tar").name == "backup:2026.tar"


def test_a_path_object_is_always_local(tmp_path: Path) -> None:
    uri = parse_storage_uri(tmp_path / "a.txt")
    assert uri.scheme == "local"
    assert uri.name == "a.txt"
    assert uri == parse_storage_uri(str(tmp_path / "a.txt"))


def test_parent_segments_of_a_local_path_are_collapsed_not_rejected(tmp_path: Path) -> None:
    assert parse_storage_uri(str(tmp_path / "a" / ".." / "b.txt")) == local_path_to_uri(
        tmp_path / "b.txt"
    )


def test_a_storage_uri_passes_through() -> None:
    uri = StorageURI("s3", "bucket", "key")
    assert parse_storage_uri(uri) is uri


@pytest.mark.skipif(not _WINDOWS, reason="drive letters and UNC paths are Windows syntax")
def test_windows_paths() -> None:
    assert str(parse_storage_uri("C:\\data\\a.csv")) == "local:///C:/data/a.csv"
    assert str(parse_storage_uri("C:/data/a.csv")) == "local:///C:/data/a.csv"
    assert (
        str(parse_storage_uri("\\\\server\\share\\dir\\a.csv")) == "local://server/share/dir/a.csv"
    )


@pytest.mark.skipif(_WINDOWS, reason="POSIX absolute paths")
def test_posix_paths() -> None:
    assert str(parse_storage_uri("/data/a.csv")) == "local:///data/a.csv"
    assert parse_storage_uri("/data/back\\slash.csv").name == "back\\slash.csv"


def test_storage_uri_validates_on_construction() -> None:
    assert StorageURI("S3", "bucket", "/a//b/").path == "a/b"
    assert StorageURI("FILE").scheme == "local"
    with pytest.raises(StorageURIException, match="scheme"):
        StorageURI("not a scheme", "bucket")
    with pytest.raises(StorageURIException, match="scheme"):
        StorageURI("", "bucket")
    with pytest.raises(StorageURIException):
        StorageURI("s3", "bucket", "a/../b")


def test_name_parent_and_joinpath() -> None:
    uri = parse_storage_uri("s3://bucket/a/b/c.txt")
    assert uri.name == "c.txt"
    assert str(uri.parent) == "s3://bucket/a/b"
    assert str(uri.parent.parent.parent) == "s3://bucket"
    assert uri.parent.parent.parent.parent == StorageURI("s3", "bucket")
    assert str(StorageURI("s3", "bucket").joinpath("a", "b/c.txt")) == "s3://bucket/a/b/c.txt"
    assert str(uri.joinpath("")) == "s3://bucket/a/b/c.txt"
    with pytest.raises(StorageURIException):
        uri.joinpath("..")


def test_storage_uri_is_hashable_and_comparable() -> None:
    assert parse_storage_uri("s3://bucket/a") == parse_storage_uri("S3://bucket//a/")
    assert len({parse_storage_uri("s3://bucket/a"), parse_storage_uri("s3://bucket/a/")}) == 1
    assert parse_storage_uri("s3://bucket/a") != parse_storage_uri("s3://Bucket/a")
