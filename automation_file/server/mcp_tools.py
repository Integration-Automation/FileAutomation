"""Semantic MCP tools: stable, task-shaped names over the storage layer.

The ``FA_*`` bridge exposes every registered action as a tool. The fourteen
tools here are what an AI client is meant to use instead: ``file_read``,
``file_write``, ``file_copy``, ``file_move``, ``file_search``,
``file_checksum``, ``file_verify``, ``storage_list``, ``storage_copy``,
``pipeline_create``, ``pipeline_run``, ``pipeline_status``, ``integrity_status``
and ``audit_search``. They work on storage URIs, never on a backend SDK, and
every call passes an :class:`~automation_file.server.mcp_policy.MCPPolicy`.

.. code-block:: python

    from automation_file.server.mcp_policy import MCPPolicy
    from automation_file.server.mcp_tools import SemanticToolkit

    toolkit = SemanticToolkit(MCPPolicy(roots=["local:///srv/reports"], allow_write=True))
    outcome = toolkit.call("file_write", {"uri": "local:///srv/reports/a.txt", "content": "hi"})
    outcome.is_error            # False
    outcome.payload["sha256"]   # the digest of what was written
    outcome.correlation_id      # ties the audit records of this call together

:meth:`SemanticToolkit.call` never raises for something a client did: a refused
or failed call comes back as a :class:`ToolOutcome` with ``is_error`` set and an
``error`` that says why. Each call runs inside ``correlation_scope()`` and
``actor_scope(...)`` and is reported as one ``mcp.tool.completed`` or
``mcp.tool.failed`` event, so the audit trail, when it is configured, ties the
storage operations to the call.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from automation_file.core.action_executor import executor
from automation_file.core.action_registry import ActionRegistry
from automation_file.events import (
    Event,
    Severity,
    actor_scope,
    correlation_scope,
    current_correlation_id,
    emit,
)
from automation_file.exceptions import (
    FileAutomationException,
    PathTraversalException,
    StorageAlreadyExistsException,
    StorageChecksumException,
    StorageNotEmptyException,
    StorageNotFoundException,
    StoragePathTypeException,
    StorageUnsupportedException,
    StorageURIException,
)
from automation_file.logging_config import file_automation_logger
from automation_file.pipeline.errors import PipelineDefinitionException
from automation_file.server import (
    mcp_file_tools,
    mcp_pipeline_tools,
    mcp_report_tools,
    mcp_storage_tools,
)
from automation_file.server.mcp_policy import (
    ALREADY_EXISTS,
    NOT_FOUND,
    OUTSIDE_ROOT,
    SEMANTIC_TOOL_NAMES,
    MCPPermissionException,
    MCPPolicy,
    MCPToolException,
    StorageGuard,
)
from automation_file.server.mcp_tool_model import SemanticTool, ToolSession, checked_arguments
from automation_file.storage.resolver import StorageResolver
from automation_file.storage.uri import parse_storage_uri

EVENT_SOURCE = "mcp"
STATUS_OK = "ok"
STATUS_REFUSED = "refused"
STATUS_ERROR = "error"
PERMISSION_DENIED = "permission_denied"
INVALID_URI = "invalid_uri"
INVALID_DEFINITION = "invalid_definition"
CHECKSUM_MISMATCH = "checksum_mismatch"
FAILED = "failed"
INTERNAL_ERROR = "internal_error"
_MAX_CLIENT_NAME = 64
_CLIENT_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_PIPELINE_PREFIX = "pipeline_"
_LOG_LEVELS = {
    Severity.INFO: logging.INFO,
    Severity.WARNING: logging.WARNING,
    Severity.ERROR: logging.ERROR,
    Severity.CRITICAL: logging.ERROR,
}
_ERROR_TYPES: tuple[tuple[type[BaseException], str], ...] = (
    (StorageNotFoundException, NOT_FOUND),
    (StorageAlreadyExistsException, ALREADY_EXISTS),
    (StorageURIException, INVALID_URI),
    (StorageChecksumException, CHECKSUM_MISMATCH),
)
#: Failures that say something about the request, not about the storage or the server.
_CALLER_MISTAKES: tuple[type[BaseException], ...] = (
    MCPToolException,
    PipelineDefinitionException,
    StorageNotFoundException,
    StorageAlreadyExistsException,
    StoragePathTypeException,
    StorageNotEmptyException,
    StorageURIException,
    StorageUnsupportedException,
)

_TOOLS_BY_NAME: dict[str, SemanticTool] = {
    tool.name: tool
    for module in (mcp_file_tools, mcp_storage_tools, mcp_pipeline_tools, mcp_report_tools)
    for tool in module.TOOLS
}
#: The fourteen tools in catalogue order.
SEMANTIC_TOOLS: tuple[SemanticTool, ...] = tuple(
    _TOOLS_BY_NAME[name] for name in SEMANTIC_TOOL_NAMES
)


@dataclass(frozen=True, kw_only=True)
class MCPToolCompleted(Event):
    """A semantic tool call did what it was asked."""

    type: ClassVar[str] = "mcp.tool.completed"


@dataclass(frozen=True, kw_only=True)
class MCPToolFailed(Event):
    """A semantic tool call was refused by the policy or failed. ``status`` says which."""

    type: ClassVar[str] = "mcp.tool.failed"
    severity: Severity = Severity.WARNING


@dataclass(frozen=True)
class ToolOutcome:
    """What one call returned: a JSON-friendly ``payload`` and whether it is an error."""

    tool: str
    payload: dict[str, Any]
    is_error: bool = False

    @property
    def correlation_id(self) -> str:
        return str(self.payload["correlation_id"])

    def to_mcp(self) -> dict[str, Any]:
        """Return the ``tools/call`` result: the payload as one JSON text block."""
        encoded = json.dumps(self.payload, ensure_ascii=False, default=str)
        return {"content": [{"type": "text", "text": encoded}], "isError": self.is_error}


@dataclass(frozen=True)
class _Failure:
    """A call that did not succeed: what the client is told and what the event keeps."""

    status: str
    severity: Severity
    error: dict[str, Any]
    recorded: str


def _refusal(code: str, message: str) -> _Failure:
    error = {"type": PERMISSION_DENIED, "code": code, "message": message}
    return _Failure(STATUS_REFUSED, Severity.WARNING, error, f"{code}: {message}")


def _described(kind: str, error: Exception) -> dict[str, Any]:
    return {"type": kind, "message": str(error), "exception": type(error).__name__}


def _severity_of(error: Exception) -> Severity:
    """Say how much attention a failed call needs.

    A mistake of the caller (a missing file, an existing target, a wrong
    argument) is information. A digest that does not match is an error. Anything
    else the library reported is a warning.
    """
    if isinstance(error, StorageChecksumException):
        return Severity.ERROR
    return Severity.INFO if isinstance(error, _CALLER_MISTAKES) else Severity.WARNING


def _failed(kind: str, error: Exception, **details: Any) -> _Failure:
    described = {**_described(kind, error), **details}
    recorded = f"{type(error).__name__}: {error}"
    return _Failure(STATUS_ERROR, _severity_of(error), described, recorded)


def _failure(error: Exception) -> _Failure:
    """Sort an exception into a refusal, a failed call or an internal error."""
    if isinstance(error, MCPPermissionException):
        return _refusal(error.code, str(error))
    if isinstance(error, PathTraversalException):
        return _refusal(OUTSIDE_ROOT, "the location leaves the allowed location through a link")
    if isinstance(error, MCPToolException):
        return _failed(error.kind, error)
    if isinstance(error, PipelineDefinitionException):
        return _failed(INVALID_DEFINITION, error, problems=list(error.problems))
    if isinstance(error, FileAutomationException):
        kind = next((name for cls, name in _ERROR_TYPES if isinstance(error, cls)), FAILED)
        return _failed(kind, error)
    # Not an error this library raises on purpose. The client is told what it was; the event
    # and the log keep only its type, because its text may quote what was being handled.
    return _Failure(
        STATUS_ERROR, Severity.ERROR, _described(INTERNAL_ERROR, error), type(error).__name__
    )


_PARTIAL = _Failure(
    STATUS_ERROR,
    Severity.WARNING,
    {"type": FAILED, "message": "the call finished with failures; the result says which"},
    "finished with failures",
)


def _shown_uri(value: object) -> str | None:
    """Return a storage URI argument in its normal form, or ``None`` when it is not one."""
    if not isinstance(value, str):
        return None
    try:
        return str(parse_storage_uri(value))
    except StorageURIException:
        return None


def _subject_of(
    tool: SemanticTool, arguments: Mapping[str, Any], body: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the payload keys that say what a call was about. Content is never among them."""
    details: dict[str, Any] = {}
    resource = _shown_uri(arguments.get("target")) or _shown_uri(arguments.get("uri"))
    if resource is not None:
        details["resource"] = resource
    source = _shown_uri(arguments.get("source"))
    if source is not None:
        details["source_uri"] = source
    for key in ("run_id", "dry_run"):
        if key in body:
            details[key] = body[key]
    if tool.name.startswith(_PIPELINE_PREFIX) and "name" in body:
        details["pipeline"] = body["name"]
    return details


class SemanticToolkit:
    """The semantic tools of one server, bound to its policy.

    ``registry`` is where the non-storage actions of the policy's pipeline allow
    list are looked up (default: the shared executor's registry). ``resolver``
    is the storage resolver behind the guard (default: the process-wide one).
    """

    def __init__(
        self,
        policy: MCPPolicy | None = None,
        registry: ActionRegistry | None = None,
        *,
        resolver: StorageResolver | None = None,
    ) -> None:
        self._policy = policy if policy is not None else MCPPolicy()
        self._session = ToolSession(
            policy=self._policy,
            guard=StorageGuard(self._policy, resolver),
            registry=registry if registry is not None else executor.registry,
        )
        self._client: str | None = None
        mcp_pipeline_tools.check_pipeline_actions(self._session)

    @property
    def policy(self) -> MCPPolicy:
        return self._policy

    @property
    def session(self) -> ToolSession:
        """What the tool handlers work with; pass it to a handler to call one directly."""
        return self._session

    @property
    def actor(self) -> str:
        """Who the calls are made as: the policy's actor, with the client's name once known."""
        return f"{self._policy.actor}:{self._client}" if self._client else self._policy.actor

    def set_client(self, name: object) -> None:
        """Remember the client's self-reported name. It labels the actor; it proves nothing."""
        cleaned = _CLIENT_NAME.sub("_", name).strip("_") if isinstance(name, str) else ""
        self._client = cleaned[:_MAX_CLIENT_NAME] or None

    @staticmethod
    def owns(name: str) -> bool:
        """Return whether ``name`` is one of the fourteen semantic tools, offered or not."""
        return name in _TOOLS_BY_NAME

    def descriptors(self) -> list[dict[str, Any]]:
        """Return the offered tools as ``tools/list`` describes them, in catalogue order."""
        return [_TOOLS_BY_NAME[name].descriptor() for name in self._policy.enabled_tools()]

    def instructions(self) -> str:
        """Return what a client should know before its first call: the policy in words."""
        return self._policy.summary()

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> ToolOutcome:
        """Run the semantic tool ``name`` and return its outcome.

        Raises :class:`MCPToolException` only for a name that is not a semantic
        tool. Everything else, a refusal by the policy included, is an outcome
        with ``is_error`` set.
        """
        tool = _TOOLS_BY_NAME.get(name)
        if tool is None:
            raise MCPToolException(f"unknown semantic tool: {name[:64]!r}", NOT_FOUND)
        given = dict(arguments or {})
        with correlation_scope() as correlation_id, actor_scope(self.actor):
            started = time.perf_counter()
            body: dict[str, Any] = {}
            failure: _Failure | None = None
            try:
                self._policy.require_tool(name)
                body = tool.handler(self._session, checked_arguments(tool, given))
            except Exception as error:  # pylint: disable=broad-exception-caught
                # Dispatcher boundary: whatever a tool raises becomes the outcome of this call.
                failure = _failure(error)
            if failure is None and body.get("ok") is False:
                failure = _PARTIAL
            duration = round((time.perf_counter() - started) * 1000, 3)
            self._report(tool, _subject_of(tool, given, body), failure, duration)
            payload: dict[str, Any] = {"tool": name, "correlation_id": correlation_id, **body}
            if failure is not None:
                payload["error"] = failure.error
            return ToolOutcome(name, payload, is_error=failure is not None)

    @staticmethod
    def _report(
        tool: SemanticTool, subject: Mapping[str, Any], failure: _Failure | None, duration: float
    ) -> None:
        """Publish the event of one call and log a refusal or a failure.

        The event holds the storage URIs the call was about and nothing else of
        its arguments: no content, no parameters, no digest. The log line holds
        the tool, the reason code and the correlation ID.
        """
        status = STATUS_OK if failure is None else failure.status
        title = f"{tool.name} {status}"
        payload: dict[str, Any] = {
            "action": tool.name,
            "status": status,
            "duration_ms": duration,
            **subject,
        }
        if failure is None:
            emit(MCPToolCompleted(source=EVENT_SOURCE, subject=title, payload=payload))
            return
        code = failure.error.get("code", failure.error["type"])
        payload.update(error=failure.recorded, code=code)
        file_automation_logger.log(
            _LOG_LEVELS[failure.severity],
            "mcp_tools: %s %s (%s) correlation_id=%s",
            tool.name,
            status,
            code,
            current_correlation_id(),
        )
        emit(
            MCPToolFailed(
                source=EVENT_SOURCE, subject=title, severity=failure.severity, payload=payload
            )
        )
