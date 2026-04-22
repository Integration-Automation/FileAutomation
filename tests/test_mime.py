"""Tests for automation_file.local.mime."""

from __future__ import annotations

from pathlib import Path

from automation_file.local.mime import detect_from_bytes, detect_mime


def test_detect_from_extension(tmp_path: Path) -> None:
    path = tmp_path / "doc.html"
    path.write_text("<html/>", encoding="utf-8")
    assert detect_mime(path) == "text/html"


def test_detect_png_by_magic(tmp_path: Path) -> None:
    path = tmp_path / "noext"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    assert detect_mime(path) == "image/png"


def test_detect_pdf_by_magic(tmp_path: Path) -> None:
    path = tmp_path / "no_extension"
    path.write_bytes(b"%PDF-1.7\n...")
    assert detect_mime(path) == "application/pdf"


def test_detect_zip_by_magic(tmp_path: Path) -> None:
    path = tmp_path / "no_ext"
    path.write_bytes(b"PK\x03\x04rest")
    assert detect_mime(path) == "application/zip"


def test_detect_webp_riff(tmp_path: Path) -> None:
    path = tmp_path / "pic"
    path.write_bytes(b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00\x00")
    assert detect_mime(path) == "image/webp"


def test_detect_wav_riff(tmp_path: Path) -> None:
    path = tmp_path / "sound"
    path.write_bytes(b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00\x00")
    assert detect_mime(path) == "audio/wav"


def test_unknown_falls_back_to_octet_stream(tmp_path: Path) -> None:
    path = tmp_path / "mystery"
    path.write_bytes(b"\x00\x01\x02randombytes")
    assert detect_mime(path) == "application/octet-stream"


def test_detect_from_bytes_png() -> None:
    assert detect_from_bytes(b"\x89PNG\r\n\x1a\n") == "image/png"


def test_detect_from_bytes_unknown_returns_octet_stream() -> None:
    assert detect_from_bytes(b"\x00\x01abc") == "application/octet-stream"
