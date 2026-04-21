"""AES-256-GCM file encryption helpers.

``encrypt_file(source, target, key)`` writes a self-describing envelope::

    magic    = b"FA-AESG"     7 bytes
    version  = 0x01           1 byte
    flags    = 0x00           1 byte (reserved)
    aad_len  = uint32 BE      4 bytes
    nonce    = 12 bytes
    aad      = <aad_len>
    ciphertext + tag          (rest — GCM tag is the trailing 16 bytes)

``decrypt_file`` reads the same format, verifies the tag, and writes the
plaintext to ``target``. Tampering (bit flips anywhere in the envelope
except ``aad_len``) surfaces as :class:`CryptoException`.

GCM has a hard plaintext limit of roughly 64 GiB per ``(key, nonce)``
pair; since each encrypt generates a fresh nonce, the practical cap is
per-file and is much larger than typical automation payloads. For files
approaching that size, split before calling ``encrypt_file``.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

_MAGIC = b"FA-AESG"
_VERSION = 0x01
_NONCE_SIZE = 12
_HEADER_FIXED_SIZE = len(_MAGIC) + 2 + 4  # magic + version + flags + aad_len
_VALID_KEY_SIZES = frozenset({16, 24, 32})
_DEFAULT_PBKDF2_ITERATIONS = 200_000


class CryptoException(FileAutomationException):
    """Raised when encryption / decryption fails (including on tamper)."""


def generate_key(*, bits: int = 256) -> bytes:
    """Return cryptographically random bytes suitable for AES-GCM."""
    if bits not in (128, 192, 256):
        raise CryptoException(f"bits must be 128 / 192 / 256, got {bits}")
    return os.urandom(bits // 8)


def key_from_password(
    password: str,
    salt: bytes,
    *,
    iterations: int = _DEFAULT_PBKDF2_ITERATIONS,
    bits: int = 256,
) -> bytes:
    """Derive a symmetric key from ``password`` via PBKDF2-HMAC-SHA256."""
    if not password:
        raise CryptoException("password must be non-empty")
    if len(salt) < 16:
        raise CryptoException("salt must be at least 16 bytes")
    if bits not in (128, 192, 256):
        raise CryptoException(f"bits must be 128 / 192 / 256, got {bits}")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=bits // 8,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_file(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    key: bytes,
    *,
    associated_data: bytes = b"",
) -> dict[str, int]:
    """Encrypt ``source`` to ``target`` under AES-GCM. Returns a size summary."""
    _validate_key(key)
    if not isinstance(associated_data, (bytes, bytearray)):
        raise CryptoException("associated_data must be bytes")
    src = Path(source)
    if not src.is_file():
        raise CryptoException(f"source file not found: {src}")

    plaintext = src.read_bytes()
    nonce = os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(bytes(key))
    ciphertext = aesgcm.encrypt(nonce, plaintext, bytes(associated_data) or None)

    envelope = _build_header(associated_data, nonce) + ciphertext
    dst = Path(target)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(envelope)
    file_automation_logger.info(
        "encrypt_file: %s -> %s (%d -> %d bytes)",
        src,
        dst,
        len(plaintext),
        len(envelope),
    )
    return {"plaintext_bytes": len(plaintext), "ciphertext_bytes": len(envelope)}


def decrypt_file(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    key: bytes,
) -> dict[str, int]:
    """Decrypt ``source`` to ``target``. Raises on invalid tag / header."""
    _validate_key(key)
    src = Path(source)
    if not src.is_file():
        raise CryptoException(f"source file not found: {src}")
    envelope = src.read_bytes()
    nonce, aad, ciphertext = _parse_envelope(envelope)
    aesgcm = AESGCM(bytes(key))
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad or None)
    except InvalidTag as err:
        raise CryptoException("authentication failed: wrong key or tampered data") from err

    dst = Path(target)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(plaintext)
    file_automation_logger.info(
        "decrypt_file: %s -> %s (%d -> %d bytes)",
        src,
        dst,
        len(envelope),
        len(plaintext),
    )
    return {"ciphertext_bytes": len(envelope), "plaintext_bytes": len(plaintext)}


def _validate_key(key: bytes) -> None:
    if not isinstance(key, (bytes, bytearray)):
        raise CryptoException("key must be bytes")
    if len(key) not in _VALID_KEY_SIZES:
        raise CryptoException(
            f"key length must be 16 / 24 / 32 bytes, got {len(key)}",
        )


def _build_header(aad: bytes, nonce: bytes) -> bytes:
    aad_len = len(aad).to_bytes(4, "big")
    return _MAGIC + bytes([_VERSION, 0x00]) + aad_len + nonce + bytes(aad)


def _parse_envelope(envelope: bytes) -> tuple[bytes, bytes, bytes]:
    if len(envelope) < _HEADER_FIXED_SIZE + _NONCE_SIZE + 16:
        raise CryptoException("ciphertext envelope is shorter than the fixed header")
    if not envelope.startswith(_MAGIC):
        raise CryptoException("not an AES-GCM envelope (bad magic)")
    version = envelope[len(_MAGIC)]
    if version != _VERSION:
        raise CryptoException(f"unsupported envelope version {version}")
    aad_len = int.from_bytes(envelope[_HEADER_FIXED_SIZE - 4 : _HEADER_FIXED_SIZE], "big")
    nonce_start = _HEADER_FIXED_SIZE
    nonce_end = nonce_start + _NONCE_SIZE
    aad_end = nonce_end + aad_len
    if aad_end > len(envelope):
        raise CryptoException("envelope truncated before aad end")
    nonce = envelope[nonce_start:nonce_end]
    aad = envelope[nonce_end:aad_end]
    ciphertext = envelope[aad_end:]
    return nonce, aad, ciphertext
