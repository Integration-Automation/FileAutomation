"""Tests for download_file resume + checksum integration."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import requests

from automation_file.remote import http_download


class _FakeResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}
        self.status_code = 206 if chunks else 200

    def raise_for_status(self) -> None: ...

    def iter_content(self, chunk_size: int) -> list[bytes]:
        del chunk_size  # matches requests.Response API; value not needed in the fake
        return list(self._chunks)


@pytest.fixture(name="patch_validator")
def _patch_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_download, "validate_http_url", lambda _url: None, raising=True)


def _patch_requests(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict[str, Any],
    chunks: list[bytes],
) -> None:
    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse(chunks)

    monkeypatch.setattr(requests, "get", fake_get, raising=True)


@pytest.mark.usefixtures("patch_validator")
def test_download_resume_sends_range_header_and_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "big.bin"
    part = tmp_path / "big.bin.part"
    part.write_bytes(b"ALREADY-")  # 8 bytes pre-downloaded

    captured: dict[str, Any] = {}
    _patch_requests(monkeypatch, captured, [b"AFTER"])

    ok = http_download.download_file("https://example.com/big.bin", str(target), resume=True)

    assert ok is True
    assert target.read_bytes() == b"ALREADY-AFTER"
    assert not part.exists()  # renamed
    assert captured["headers"] == {"Range": "bytes=8-"}


@pytest.mark.usefixtures("patch_validator")
def test_download_without_resume_skips_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "big.bin"
    captured: dict[str, Any] = {}
    _patch_requests(monkeypatch, captured, [b"CONTENT"])

    ok = http_download.download_file("https://example.com/big.bin", str(target), resume=False)

    assert ok is True
    assert target.read_bytes() == b"CONTENT"
    assert not (tmp_path / "big.bin.part").exists()
    assert captured["headers"] is None


@pytest.mark.usefixtures("patch_validator")
def test_download_fresh_resume_without_existing_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "big.bin"
    captured: dict[str, Any] = {}
    _patch_requests(monkeypatch, captured, [b"PAYLOAD"])

    ok = http_download.download_file("https://example.com/big.bin", str(target), resume=True)

    assert ok is True
    assert target.read_bytes() == b"PAYLOAD"
    assert captured["headers"] is None  # no Range since nothing pre-downloaded


@pytest.mark.usefixtures("patch_validator")
def test_download_verifies_sha256_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"verified"
    target = tmp_path / "v.bin"
    captured: dict[str, Any] = {}
    _patch_requests(monkeypatch, captured, [payload])

    digest = hashlib.sha256(payload).hexdigest()
    ok = http_download.download_file(
        "https://example.com/v.bin", str(target), expected_sha256=digest
    )

    assert ok is True
    assert target.exists()


@pytest.mark.usefixtures("patch_validator")
def test_download_checksum_mismatch_removes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "v.bin"
    captured: dict[str, Any] = {}
    _patch_requests(monkeypatch, captured, [b"bad"])

    ok = http_download.download_file(
        "https://example.com/v.bin", str(target), expected_sha256="0" * 64
    )

    assert ok is False
    assert not target.exists()
