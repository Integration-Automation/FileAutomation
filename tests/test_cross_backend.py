"""Cross-backend copy tests.

Network-backed backends aren't exercised — these tests verify URI parsing,
local-to-local round trips, and error paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file import (
    CrossBackendException,
    build_default_registry,
    copy_between,
)
from automation_file.remote import cross_backend


def test_local_to_local_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "source.bin"
    dst = tmp_path / "nested" / "dest.bin"
    src.write_bytes(b"payload-123")
    assert copy_between(str(src), str(dst)) is True
    assert dst.read_bytes() == b"payload-123"


def test_local_scheme_prefix(tmp_path: Path) -> None:
    src = tmp_path / "a.bin"
    dst = tmp_path / "b.bin"
    src.write_bytes(b"prefixed")
    assert copy_between(f"local:{src}", f"local:{dst}") is True
    assert dst.read_bytes() == b"prefixed"


def test_missing_local_source_returns_false(tmp_path: Path) -> None:
    missing = tmp_path / "nope.bin"
    dst = tmp_path / "dest.bin"
    assert copy_between(str(missing), str(dst)) is False
    assert not dst.exists()


def test_unknown_source_scheme_raises() -> None:
    # The target path is unused — the call must fail on the source scheme
    # before touching the filesystem.
    unused_target = "/tmp/x"  # NOSONAR python:S5443
    with pytest.raises(CrossBackendException):
        copy_between("gopher://a/b", unused_target)


def test_unknown_target_scheme_raises(tmp_path: Path) -> None:
    src = tmp_path / "x"
    src.write_bytes(b"x")
    with pytest.raises(CrossBackendException):
        copy_between(str(src), "gopher://a/b")


def test_s3_uri_without_key_raises() -> None:
    with pytest.raises(CrossBackendException):
        cross_backend._split_bucket("bucket-only", "s3")


def test_default_registry_contains_copy_between() -> None:
    registry = build_default_registry()
    assert "FA_copy_between" in registry


def test_split_parses_s3_uri() -> None:
    scheme, remainder = cross_backend._split("s3://my-bucket/path/to/file.txt")
    assert scheme == "s3"
    assert remainder == "my-bucket/path/to/file.txt"


def test_split_parses_azure_uri() -> None:
    scheme, remainder = cross_backend._split("azure://container/blob.bin")
    assert scheme == "azure"
    assert remainder == "container/blob.bin"


def test_split_parses_sftp_uri() -> None:
    scheme, remainder = cross_backend._split("sftp:/remote/dir/file.bin")
    assert scheme == "sftp"
    assert remainder == "remote/dir/file.bin"


def test_split_parses_http_uri_preserves_full_url() -> None:
    scheme, remainder = cross_backend._split("https://example.org/foo")
    assert scheme == "https"
    assert remainder.startswith("https://")
