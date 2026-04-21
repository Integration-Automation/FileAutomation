"""Tests for AES-GCM file encryption helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file import (
    CryptoException,
    build_default_registry,
    decrypt_file,
    encrypt_file,
    generate_key,
    key_from_password,
)


def test_generate_key_default_length() -> None:
    assert len(generate_key()) == 32


def test_generate_key_rejects_bad_size() -> None:
    with pytest.raises(CryptoException):
        generate_key(bits=111)


def test_round_trip_preserves_plaintext(tmp_path: Path) -> None:
    key = generate_key()
    source = tmp_path / "plain.bin"
    source.write_bytes(b"top-secret payload\n")
    enc = tmp_path / "cipher.bin"
    dec = tmp_path / "restored.bin"
    summary = encrypt_file(source, enc, key)
    assert summary["plaintext_bytes"] == source.stat().st_size
    decrypt_file(enc, dec, key)
    assert dec.read_bytes() == source.read_bytes()


def test_ciphertext_differs_between_calls(tmp_path: Path) -> None:
    key = generate_key()
    source = tmp_path / "plain.bin"
    source.write_bytes(b"same data")
    enc_a = tmp_path / "a.bin"
    enc_b = tmp_path / "b.bin"
    encrypt_file(source, enc_a, key)
    encrypt_file(source, enc_b, key)
    assert enc_a.read_bytes() != enc_b.read_bytes()


def test_wrong_key_fails(tmp_path: Path) -> None:
    good = generate_key()
    bad = generate_key()
    source = tmp_path / "plain.bin"
    source.write_bytes(b"x" * 128)
    enc = tmp_path / "cipher.bin"
    encrypt_file(source, enc, good)
    with pytest.raises(CryptoException, match="authentication"):
        decrypt_file(enc, tmp_path / "dec.bin", bad)


def test_tampered_ciphertext_fails(tmp_path: Path) -> None:
    key = generate_key()
    source = tmp_path / "plain.bin"
    source.write_bytes(b"x" * 128)
    enc = tmp_path / "cipher.bin"
    encrypt_file(source, enc, key)
    contents = bytearray(enc.read_bytes())
    contents[-1] ^= 0x01
    enc.write_bytes(bytes(contents))
    with pytest.raises(CryptoException, match="authentication"):
        decrypt_file(enc, tmp_path / "dec.bin", key)


def test_associated_data_roundtrip(tmp_path: Path) -> None:
    key = generate_key()
    source = tmp_path / "plain.bin"
    source.write_bytes(b"hello")
    enc = tmp_path / "cipher.bin"
    encrypt_file(source, enc, key, associated_data=b"file=plain.bin")
    dec = tmp_path / "dec.bin"
    decrypt_file(enc, dec, key)
    assert dec.read_bytes() == b"hello"


def test_invalid_key_size(tmp_path: Path) -> None:
    source = tmp_path / "plain.bin"
    source.write_bytes(b"x")
    with pytest.raises(CryptoException, match="key length"):
        encrypt_file(source, tmp_path / "out", b"\x00" * 10)


def test_missing_source_raises(tmp_path: Path) -> None:
    with pytest.raises(CryptoException, match="source file"):
        encrypt_file(tmp_path / "absent", tmp_path / "out", generate_key())


def test_bad_magic_rejected(tmp_path: Path) -> None:
    garbage = tmp_path / "junk.bin"
    garbage.write_bytes(b"NOT-A-REAL-ENVELOPE" + b"\x00" * 64)
    with pytest.raises(CryptoException, match="magic"):
        decrypt_file(garbage, tmp_path / "out.bin", generate_key())


def test_key_from_password_deterministic() -> None:
    salt = b"\x00" * 16
    key_a = key_from_password("passphrase", salt, iterations=1_000)
    key_b = key_from_password("passphrase", salt, iterations=1_000)
    assert key_a == key_b
    assert len(key_a) == 32


def test_key_from_password_requires_nonempty_password() -> None:
    with pytest.raises(CryptoException, match="non-empty"):
        key_from_password("", b"\x00" * 16)


def test_key_from_password_rejects_short_salt() -> None:
    with pytest.raises(CryptoException, match="salt"):
        key_from_password("pw", b"\x00" * 8)


def test_key_from_password_round_trip(tmp_path: Path) -> None:
    salt = b"sixteen-byte-saltX"
    key = key_from_password("strong-password", salt, iterations=1_000)
    source = tmp_path / "plain.txt"
    source.write_text("hello", encoding="utf-8")
    enc = tmp_path / "cipher.bin"
    encrypt_file(source, enc, key)
    dec = tmp_path / "dec.txt"
    decrypt_file(enc, dec, key)
    assert dec.read_text(encoding="utf-8") == "hello"


def test_encrypt_decrypt_actions_registered() -> None:
    registry = build_default_registry()
    assert "FA_encrypt_file" in registry
    assert "FA_decrypt_file" in registry
