"""Network-binding guards shared by every embedded action server."""

from __future__ import annotations

import ipaddress
import socket


def ensure_loopback(host: str) -> None:
    """Raise ``ValueError`` if ``host`` resolves to a non-loopback address.

    Every resolved A / AAAA record must be loopback. The explicit error message
    names the opt-out flag so callers are reminded that exposing a server
    dispatching arbitrary registry commands is equivalent to a remote REPL.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise ValueError(f"cannot resolve host: {host}") from error
    for info in infos:
        ip_obj = ipaddress.ip_address(info[4][0])
        if not ip_obj.is_loopback:
            raise ValueError(
                f"host {host} resolves to non-loopback {ip_obj}; pass allow_non_loopback=True "
                "if exposure is intentional"
            )
