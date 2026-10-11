"""Who is acting and which run an event belongs to, carried through ``contextvars``.

A pipeline run, a scheduler firing or a server request opens a scope; everything
that happens inside it -- events, audit records, storage operations -- picks up
the same correlation ID and actor without passing them through every call.
Threads started by ``concurrent.futures`` do not inherit a context on their own:
the code that fans work out re-enters the scope in each worker.
"""

from __future__ import annotations

import contextlib
import getpass
import uuid
from collections.abc import Iterator
from contextvars import ContextVar

_UNKNOWN_ACTOR = "unknown"
_correlation_id: ContextVar[str | None] = ContextVar("fa_correlation_id", default=None)
_actor: ContextVar[str | None] = ContextVar("fa_actor", default=None)


def new_correlation_id() -> str:
    """Return a fresh correlation ID (32 hex characters)."""
    return uuid.uuid4().hex


def current_correlation_id() -> str | None:
    """Return the correlation ID of the enclosing scope, or ``None`` outside any scope."""
    return _correlation_id.get()


def _process_user() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):
        return _UNKNOWN_ACTOR


def current_actor() -> str:
    """Return the actor of the enclosing scope; the process's user outside any scope."""
    return _actor.get() or _process_user()


@contextlib.contextmanager
def correlation_scope(correlation_id: str | None = None) -> Iterator[str]:
    """Run a block under one correlation ID and yield it.

    Without an argument the enclosing scope's ID is kept, or a new one is made
    when there is none, so nested scopes share the outermost run's ID.
    """
    chosen = correlation_id or _correlation_id.get() or new_correlation_id()
    token = _correlation_id.set(chosen)
    try:
        yield chosen
    finally:
        _correlation_id.reset(token)


@contextlib.contextmanager
def actor_scope(actor: str) -> Iterator[str]:
    """Run a block on behalf of ``actor`` (a user, ``"scheduler"``, ``"mcp"`` ...)."""
    token = _actor.set(actor)
    try:
        yield actor
    finally:
        _actor.reset(token)
