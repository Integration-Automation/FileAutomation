"""SSRF guard for outbound HTTP requests.

``validate_http_url`` rejects non-http(s) schemes, resolves the host, and
rejects private / loopback / link-local / reserved IP ranges. Every remote
function that accepts a user-supplied URL must pass it through here first.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from automation_file.exceptions import UrlValidationException

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _require_host(url: str) -> str:
    if not isinstance(url, str) or not url:
        raise UrlValidationException("url must be a non-empty string")
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UrlValidationException(f"disallowed scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise UrlValidationException("url must contain a host")
    return host


def _resolve_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise UrlValidationException(f"cannot resolve host: {host}") from error
    return [str(info[4][0]) for info in infos]


def _is_disallowed_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_reserved
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
    )


def validate_http_url(url: str) -> str:
    """Return ``url`` if safe; raise :class:`UrlValidationException` otherwise."""
    host = _require_host(url)
    for ip_str in _resolve_ips(host):
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError as error:
            raise UrlValidationException(f"cannot parse resolved ip: {ip_str}") from error
        if _is_disallowed_ip(ip_obj):
            raise UrlValidationException(f"disallowed ip: {ip_str}")
    return url
