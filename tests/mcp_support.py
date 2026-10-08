"""Helpers shared by the tests of the semantic MCP tools."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from automation_file.audit import MemoryAuditStore, audit_trail, configure_audit
from automation_file.integrity import actions as integrity_actions
from automation_file.pipeline import MemoryRunStore, set_default_run_store
from automation_file.server.mcp_policy import MCPPolicy
from automation_file.server.mcp_tools import SemanticToolkit, ToolOutcome
from automation_file.storage import clear_memory_stores

BOX = "memory://box"
INBOX = f"{BOX}/in"


def link_directory(link: Path, target: Path) -> None:
    """Make ``link`` lead to the directory ``target``, or skip the test when that is impossible.

    A symbolic link where the platform allows one; on Windows without that
    privilege a junction, which needs none and is followed the same way.
    """
    with contextlib.suppress(OSError, NotImplementedError):
        link.symlink_to(target, target_is_directory=True)
        return
    if os.name != "nt":
        pytest.skip("symbolic links cannot be created here")
    import _winapi

    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError:
        pytest.skip("neither a symbolic link nor a junction can be created here")


def remove_link(link: Path) -> None:
    """Remove what :func:`link_directory` made, leaving its target alone."""
    with contextlib.suppress(OSError):
        if link.is_symlink():
            link.unlink()
        else:
            os.rmdir(link)


def toolkit(**policy: Any) -> SemanticToolkit:
    """Return a toolkit whose policy allows the ``memory://box/in`` tree unless told otherwise."""
    policy.setdefault("roots", (INBOX,))
    return SemanticToolkit(MCPPolicy(**policy))


def writable(**policy: Any) -> SemanticToolkit:
    """Return a toolkit that may write below ``memory://box/in``."""
    return toolkit(allow_write=True, **policy)


def succeed(outcome: ToolOutcome) -> dict[str, Any]:
    """Return the payload of an outcome that must not be an error."""
    assert outcome.is_error is False, outcome.payload
    return outcome.payload


def refused(outcome: ToolOutcome, code: str) -> dict[str, Any]:
    """Return the error of an outcome the policy must have refused with ``code``."""
    assert outcome.is_error is True, outcome.payload
    error = outcome.payload["error"]
    assert (error["type"], error["code"]) == ("permission_denied", code), error
    return error


def failed(outcome: ToolOutcome, kind: str) -> dict[str, Any]:
    """Return the error of an outcome that must have failed as ``kind``."""
    assert outcome.is_error is True, outcome.payload
    error = outcome.payload["error"]
    assert error["type"] == kind, error
    return error


@contextlib.contextmanager
def clean_state() -> Iterator[None]:
    """Give a test empty memory stores and a run store of its own, and take both away after."""
    clear_memory_stores()
    previous = set_default_run_store(MemoryRunStore())
    try:
        yield
    finally:
        set_default_run_store(previous)
        integrity_actions.stop_all_monitors()
        audit_trail.close()
        clear_memory_stores()


def audited() -> MemoryAuditStore:
    """Point the process-wide audit trail at a fresh in-memory store and return the store."""
    store = MemoryAuditStore()
    configure_audit(store)
    return store
