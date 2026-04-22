"""Opt-in variable substitution for action list payloads.

When ``execute_action(..., substitute=True)`` is used, every string inside
the action list is scanned for ``${kind}`` / ``${kind:arg}`` placeholders
before dispatch. The following kinds are supported:

* ``${env:NAME}`` — value of the ``NAME`` environment variable (empty when unset)
* ``${date:FMT}`` — ``datetime.now().strftime(FMT)``; bare ``${date}`` yields ISO
* ``${uuid}`` — a fresh ``uuid.uuid4().hex``
* ``${cwd}`` — ``os.getcwd()``

Unknown kinds raise :class:`SubstitutionException` so typos surface loudly
rather than leaking literal ``${...}`` into paths.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime

from automation_file.exceptions import FileAutomationException

_PATTERN = re.compile(r"\$\{([a-zA-Z_]\w*)(?::([^}]*))?\}", re.ASCII)


class SubstitutionException(FileAutomationException):
    """Raised when a ``${...}`` reference names an unknown kind."""


def substitute(payload: object) -> object:
    """Return a deep copy of ``payload`` with every ``${...}`` expanded."""
    if isinstance(payload, str):
        return _expand(payload)
    if isinstance(payload, list):
        return [substitute(item) for item in payload]
    if isinstance(payload, dict):
        return {key: substitute(value) for key, value in payload.items()}
    if isinstance(payload, tuple):
        return tuple(substitute(item) for item in payload)
    return payload


def _expand(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        arg = match.group(2)
        handler = _HANDLERS.get(kind)
        if handler is None:
            raise SubstitutionException(f"unknown substitution kind: {match.group(0)}")
        return handler(arg)

    return _PATTERN.sub(replace, text)


def _env(arg: str | None) -> str:
    if not arg:
        raise SubstitutionException("${env:NAME} requires a variable name")
    return os.environ.get(arg, "")


def _date(arg: str | None) -> str:
    fmt = arg or "%Y-%m-%dT%H:%M:%S"
    return datetime.now().strftime(fmt)


def _uuid(_arg: str | None) -> str:
    return uuid.uuid4().hex


def _cwd(_arg: str | None) -> str:
    return os.getcwd()


_HANDLERS: dict[str, Callable[[str | None], str]] = {
    "env": _env,
    "date": _date,
    "uuid": _uuid,
    "cwd": _cwd,
}
