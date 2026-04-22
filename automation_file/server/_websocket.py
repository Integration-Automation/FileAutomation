"""Minimal server-side WebSocket helpers (RFC 6455).

Scope is intentionally narrow: we only need to (a) complete the opening
handshake and (b) send server-to-client text frames. We never parse inbound
frames beyond detecting a close — the ``/progress`` stream is write-only.

Keeping this off the ``websockets`` third-party dep preserves the stdlib
footprint of the HTTP server.
"""

from __future__ import annotations

import base64
import hashlib
import os
import struct
from typing import Any

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def compute_accept_key(sec_websocket_key: str) -> str:
    """Return the ``Sec-WebSocket-Accept`` value for ``sec_websocket_key``.

    RFC 6455 mandates SHA-1 + a fixed GUID for the opening handshake — the
    digest only proves the server understood the handshake, it is not a
    security primitive. ``usedforsecurity=False`` tells static analysers to
    skip the standard SHA-1 "insecure hash" warning.
    """
    digest = hashlib.sha1(  # nosec B324 nosemgrep NOSONAR RFC6455 handshake
        (sec_websocket_key + _GUID).encode("ascii"),
        usedforsecurity=False,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def send_text(wfile: Any, message: str) -> None:
    """Write a single FIN text frame (server -> client, unmasked)."""
    data = message.encode("utf-8")
    header = bytearray([0x81])
    length = len(data)
    if length < 126:
        header.append(length)
    elif length < (1 << 16):
        header.append(126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(127)
        header.extend(struct.pack(">Q", length))
    wfile.write(bytes(header) + data)
    wfile.flush()


def send_close(wfile: Any, code: int = 1000) -> None:
    """Write a close frame (server -> client, unmasked)."""
    payload = struct.pack(">H", code)
    wfile.write(bytes([0x88, len(payload)]) + payload)
    wfile.flush()


def read_frame_opcode(rfile: Any) -> int | None:
    """Peek at one frame header and return its opcode, or ``None`` on EOF.

    The progress stream is write-only, but we still consume any client frame
    (ping / close) so the TCP buffer does not fill up. Inbound client frames
    are always masked per RFC 6455.
    """
    header = rfile.read(2)
    if len(header) < 2:
        return None
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    masked = bool(header[1] & 0x80)
    if length == 126:
        extra = rfile.read(2)
        if len(extra) < 2:
            return None
        length = struct.unpack(">H", extra)[0]
    elif length == 127:
        extra = rfile.read(8)
        if len(extra) < 8:
            return None
        length = struct.unpack(">Q", extra)[0]
    if masked and len(rfile.read(4)) < 4:
        return None
    remaining = length
    while remaining > 0:
        chunk = rfile.read(min(remaining, 4096))
        if not chunk:
            return None
        remaining -= len(chunk)
    return opcode


def generate_key() -> str:
    """Produce a random ``Sec-WebSocket-Key`` value (used by tests)."""
    return base64.b64encode(os.urandom(16)).decode("ascii")
