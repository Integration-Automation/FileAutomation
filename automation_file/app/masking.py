"""Keep secrets out of every view.

A user interface shows events, audit records, run parameters and configuration
summaries, and any of them may carry a token, a password or a webhook URL.
:func:`mask_secrets` returns a copy that is safe to render:

* a value stored under a name that says it is a secret (``password``,
  ``token``, ``api_key``, ``authorization`` ...) becomes :data:`MASK`;
* a value stored under a name that says it is a URL (``url``, ``webhook_url``)
  keeps its scheme and host and loses the rest, because the path of a webhook
  URL is the credential;
* in any other text, the user information of a URL (``user:password@``) and
  the token after ``Bearer`` are removed.

Storage URIs are left alone: they cannot carry credentials. Nothing here decides
what is logged; it is the last line of defence for what is displayed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MASK = "********"

_SECRET_WORDS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "api_key",
    "access_key",
    "accesskey",
    "private_key",
    "credential",
    "authorization",
    "connection_string",
    "signature",
    "cookie",
)
_URL_WORDS = ("url", "webhook")
_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@'\"]+@")
_HTTP_URL = re.compile(r"(?i)\b(https?://)(?:[^/\s@'\"]*@)?([^/\s'\"?#]+)[^\s'\")]*")
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")


def _folded(name: object) -> str:
    return name.strip().lower().replace("-", "_") if isinstance(name, str) else ""


def is_secret_name(name: object) -> bool:
    """Return whether a field called ``name`` holds a secret."""
    folded = _folded(name)
    return any(word in folded for word in _SECRET_WORDS)


def is_url_name(name: object) -> bool:
    """Return whether a field called ``name`` holds a URL that may carry a credential."""
    parts = _folded(name).split("_")
    return any(word in parts for word in _URL_WORDS)


def mask_url(url: str) -> str:
    """Return ``url`` reduced to its scheme and host; text without an HTTP URL becomes the mask."""
    reduced, found = _HTTP_URL.subn(rf"\1\2/{MASK}", url)
    return reduced if found else MASK


def mask_text(text: str) -> str:
    """Return ``text`` without URL credentials and without bearer tokens."""
    cleaned = _CREDENTIALS.sub(rf"\1{MASK}@", text)
    return _BEARER.sub(rf"\1 {MASK}", cleaned)


def _masked_value(name: object, value: Any) -> Any:
    if is_secret_name(name):
        return value if value in (None, "") else MASK
    if is_url_name(name) and isinstance(value, str) and value:
        return mask_url(value)
    return mask_secrets(value)


def mask_secrets(value: Any) -> Any:
    """Return a copy of ``value`` that is safe to show.

    Mappings, lists and tuples are walked; tuples come back as lists, so the
    result is JSON-friendly. Any other value is returned as it is.
    """
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, Mapping):
        return {key: _masked_value(key, item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_secrets(item) for item in value]
    return value
