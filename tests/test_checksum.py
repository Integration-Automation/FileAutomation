"""Tests for automation_file.core.checksum."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from automation_file.core.checksum import (
    ChecksumMismatchException,
    file_checksum,
    verify_checksum,
)
from automation_file.exceptions import FileNotExistsException


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_file_checksum_sha256(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_bytes(b"hello world")
    assert file_checksum(target) == _sha256(b"hello world")


def test_file_checksum_streams_large_file(tmp_path: Path) -> None:
    target = tmp_path / "big.bin"
    payload = b"\x00" * (3 * 1024 * 1024 + 17)
    target.write_bytes(payload)
    assert file_checksum(target, chunk_size=4096) == _sha256(payload)


def test_file_checksum_md5(tmp_path: Path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"hi")
    # Verifies the library accepts any hashlib algorithm — not a security use of MD5.
    expected = hashlib.md5(b"hi").hexdigest()  # NOSONAR python:S4790
    assert file_checksum(target, algorithm="md5") == expected


def test_file_checksum_unknown_algorithm(tmp_path: Path) -> None:
    target = tmp_path / "a.bin"
    target.write_bytes(b"hi")
    with pytest.raises(ValueError):
        file_checksum(target, algorithm="definitely-not-a-hash")


def test_file_checksum_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotExistsException):
        file_checksum(tmp_path / "nope")


def test_verify_checksum_match(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_bytes(b"hello world")
    assert verify_checksum(target, _sha256(b"hello world")) is True


def test_verify_checksum_is_case_insensitive(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_bytes(b"hello world")
    assert verify_checksum(target, _sha256(b"hello world").upper()) is True


def test_verify_checksum_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_bytes(b"hello world")
    assert verify_checksum(target, "0" * 64) is False


def test_checksum_mismatch_exception_exists() -> None:
    assert issubclass(ChecksumMismatchException, Exception)


def test_checksum_actions_registered() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    assert "FA_file_checksum" in registry
    assert "FA_verify_checksum" in registry
