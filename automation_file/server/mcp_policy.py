"""The permission model of the semantic MCP tools.

An :class:`MCPPolicy` is built once, when the server starts, and never changes.
It says:

* **where** a tool may work: the allowed roots, as storage URIs. Without a root
  every tool that touches storage refuses.
* **what** it may do there: reading only, unless writing is switched on;
  replacing an existing file and deleting need a permission of their own.
* **how much**: the bytes ``file_read`` returns, the entries a listing returns,
  the size of a file written from a tool call, the bytes a content search reads.
* **which actions** a pipeline created or run through MCP may call, and which
  of the fourteen tools are offered at all.

:class:`StorageGuard` is the resolver the tools reach storage through. A
location inside a local root is served by a ``LocalStorage`` confined to that
root, so the storage layer's own ``safe_join`` check refuses a link or an
absolute path that leaves it. For every other backend the scheme, the authority
and the path are compared segment by segment: ``s3://bucket/team`` allows
``s3://bucket/team/a.csv`` and not ``s3://bucket/team-b/a.csv``.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any

from automation_file.exceptions import (
    MCPServerException,
    PathTraversalException,
    StoragePermissionException,
    StorageURIException,
)
from automation_file.storage.backend import StorageBackend
from automation_file.storage.local_storage import LocalStorage
from automation_file.storage.resolver import StorageResolver, default_resolver
from automation_file.storage.uri import (
    LOCAL_SCHEME,
    StorageURI,
    URILike,
    normalize_path,
    parse_storage_uri,
)

#: The fourteen semantic tools, in the order ``tools/list`` returns them.
SEMANTIC_TOOL_NAMES: tuple[str, ...] = (
    "file_read",
    "file_write",
    "file_copy",
    "file_move",
    "file_search",
    "file_checksum",
    "file_verify",
    "storage_list",
    "storage_copy",
    "pipeline_create",
    "pipeline_run",
    "pipeline_status",
    "integrity_status",
    "audit_search",
)

DEFAULT_MAX_READ_BYTES = 256 * 1024
DEFAULT_MAX_WRITE_BYTES = 1024 * 1024
DEFAULT_MAX_RESULTS = 200
DEFAULT_MAX_SEARCH_BYTES = 8 * 1024 * 1024
DEFAULT_ACTOR = "mcp"

#: ``MCPPermissionException.code`` values: why a call was refused.
NO_ROOT = "no_root"
OUTSIDE_ROOT = "outside_root"
READ_ONLY = "read_only"
OVERWRITE_NOT_ALLOWED = "overwrite_not_allowed"
DELETE_NOT_ALLOWED = "delete_not_allowed"
TOOL_DISABLED = "tool_disabled"
ACTION_NOT_ALLOWED = "action_not_allowed"
LIMIT_EXCEEDED = "limit_exceeded"

#: ``MCPToolException.kind`` values: why a call could not be carried out.
INVALID_ARGUMENTS = "invalid_arguments"
NOT_FOUND = "not_found"
ALREADY_EXISTS = "already_exists"
NOT_CONFIGURED = "not_configured"

_WINDOWS = os.sep == "\\"
_DEVICE_NUMBERS = "123456789"
_WINDOWS_DEVICES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *(f"COM{number}" for number in _DEVICE_NUMBERS),
        *(f"LPT{number}" for number in _DEVICE_NUMBERS),
    }
)
_LIMITS = ("max_read_bytes", "max_write_bytes", "max_results", "max_search_bytes")
_HOW_TO_ADD_A_ROOT = (
    "start the server with --root <storage URI or directory> (repeatable), "
    "or pass MCPPolicy(roots=[...])"
)


class MCPPermissionException(MCPServerException):
    """Raised when the policy refuses a call. ``code`` names the rule that refused it."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class MCPLocationException(MCPPermissionException, StoragePermissionException):
    """Raised when a storage location is outside what the policy allows.

    It is a storage error as well, so a tree copy records it for the one file it
    concerns and carries on with the others.
    """


class MCPToolException(MCPServerException):
    """Raised when a semantic tool cannot do what it was asked. ``kind`` says why."""

    def __init__(self, message: str, kind: str = INVALID_ARGUMENTS) -> None:
        super().__init__(message)
        self.kind = kind


def _root_uri(value: URILike) -> StorageURI:
    try:
        return parse_storage_uri(value)
    except StorageURIException as error:
        # The value is not repeated: a URI refused for carrying credentials must not be echoed.
        raise MCPServerException(f"invalid storage location in the policy: {error}") from error


def _as_uris(values: Any) -> tuple[StorageURI, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, os.PathLike, StorageURI)):
        values = (values,)
    return tuple(dict.fromkeys(_root_uri(value) for value in values))


def _as_names(values: Any, what: str) -> frozenset[str] | None:
    if values is None:
        return None
    names = (values,) if isinstance(values, str) else tuple(values)
    wrong = [name for name in names if not (isinstance(name, str) and name.strip())]
    if wrong:
        raise MCPServerException(f"{what}: expected names, got {wrong!r}")
    return frozenset(name.strip() for name in names)


def _positive(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MCPServerException(f"{name} must be an integer of 1 or more, got {value!r}")
    return value


def _segments(uri: StorageURI) -> tuple[str, ...]:
    """Return the path of ``uri`` as segments; a Windows local path may use backslashes."""
    text = uri.path
    if _WINDOWS and uri.scheme == LOCAL_SCHEME:
        text = normalize_path(text.replace("\\", "/"))
    return tuple(text.split("/")) if text else ()


def _comparable(uri: StorageURI, segments: tuple[str, ...]) -> tuple[str, ...]:
    """Fold the case of local segments the way the filesystem compares them."""
    if uri.scheme != LOCAL_SCHEME:
        return segments
    return tuple(os.path.normcase(segment) for segment in segments)


def names_windows_device(relative: str) -> bool:
    """Return whether a path below a local root is a device or a data stream to Windows.

    ``reports/CON`` is the console and ``a.txt:hidden`` an alternate data stream,
    wherever they are written: neither is a file in the directory it seems to be in.
    """
    for segment in relative.split("/"):
        stem = segment.partition(".")[0].rstrip(" ").upper()
        if ":" in segment or stem in _WINDOWS_DEVICES:
            return True
    return False


def path_below(root: StorageURI, uri: StorageURI) -> str | None:
    """Return the path of ``uri`` below ``root``, or ``None`` when it is not at or below it.

    The comparison is by whole segments, so ``team`` is not above ``team-b``.
    """
    if (root.scheme, root.authority) != (uri.scheme, uri.authority):
        return None
    base, wanted = _segments(root), _segments(uri)
    if _comparable(uri, wanted)[: len(base)] != _comparable(root, base):
        return None
    return "/".join(wanted[len(base) :])


@dataclass(frozen=True)
class MCPPolicy:
    """What the semantic MCP tools may do. Immutable; the defaults allow nothing to change.

    ``roots`` are storage URIs or local directories. ``pipeline_dir`` is where
    ``pipeline_create`` keeps definitions; without one they live in memory until
    the server stops. ``pipeline_actions`` replaces the default set of actions a
    pipeline may call (the ``FA_storage_*`` actions the permissions cover), and
    ``tools`` names the semantic tools to offer (all fourteen when ``None``).
    """

    roots: Collection[URILike] = ()
    allow_write: bool = False
    allow_overwrite: bool = False
    allow_delete: bool = False
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES
    max_write_bytes: int = DEFAULT_MAX_WRITE_BYTES
    max_results: int = DEFAULT_MAX_RESULTS
    max_search_bytes: int = DEFAULT_MAX_SEARCH_BYTES
    pipeline_dir: URILike | None = None
    pipeline_actions: Collection[str] | None = None
    tools: Collection[str] | None = None
    actor: str = DEFAULT_ACTOR

    def __post_init__(self) -> None:
        object.__setattr__(self, "roots", _as_uris(self.roots))
        for name in _LIMITS:
            _positive(name, getattr(self, name))
        if (self.allow_overwrite or self.allow_delete) and not self.allow_write:
            raise MCPServerException(
                "allow_overwrite and allow_delete need allow_write (--allow-write): a "
                "read-only server cannot replace or delete anything"
            )
        if self.pipeline_dir is not None:
            object.__setattr__(self, "pipeline_dir", _root_uri(self.pipeline_dir))
        object.__setattr__(
            self, "pipeline_actions", _as_names(self.pipeline_actions, "pipeline_actions")
        )
        tools = _as_names(self.tools, "tools")
        unknown = sorted(set(tools or ()) - set(SEMANTIC_TOOL_NAMES))
        if unknown:
            raise MCPServerException(
                f"unknown semantic tool(s) {unknown}; known: {list(SEMANTIC_TOOL_NAMES)}"
            )
        object.__setattr__(self, "tools", tools)
        if not (isinstance(self.actor, str) and self.actor.strip()):
            raise MCPServerException(f"actor must be a non-empty string, got {self.actor!r}")

    # ------------------------------------------------------------------ locations

    @property
    def root_uris(self) -> tuple[StorageURI, ...]:
        """The allowed roots as parsed storage URIs."""
        return tuple(parse_storage_uri(root) for root in self.roots)

    def candidates(self, uri: StorageURI) -> list[tuple[StorageURI, str]]:
        """Return every allowed root at or above ``uri`` with the path below it, outermost first.

        Raises :class:`MCPLocationException` when no root is configured or none
        contains ``uri``.
        """
        roots = self.root_uris
        if not roots:
            raise MCPLocationException(
                f"no storage location is allowed on this server: {_HOW_TO_ADD_A_ROOT}", NO_ROOT
            )
        found: list[tuple[StorageURI, str]] = []
        for root in roots:
            relative = path_below(root, uri)
            if relative is not None:
                found.append((root, relative))
        if not found:
            allowed = ", ".join(str(root) for root in roots)
            raise MCPLocationException(
                f"{uri} is outside the allowed locations ({allowed})", OUTSIDE_ROOT
            )
        return sorted(found, key=lambda entry: len(entry[0].path))

    def is_root(self, uri: StorageURI) -> bool:
        """Return whether ``uri`` is one of the allowed roots itself."""
        return any(path_below(root, uri) == "" for root in self.root_uris)

    # ------------------------------------------------------------------ permissions

    def enabled_tools(self) -> tuple[str, ...]:
        """Return the semantic tools this policy offers, in catalogue order."""
        if self.tools is None:
            return SEMANTIC_TOOL_NAMES
        return tuple(name for name in SEMANTIC_TOOL_NAMES if name in self.tools)

    def require_tool(self, tool: str) -> None:
        if tool not in self.enabled_tools():
            raise MCPPermissionException(f"{tool} is switched off on this server", TOOL_DISABLED)

    def require_write(self, tool: str) -> None:
        if not self.allow_write:
            raise MCPPermissionException(
                f"{tool} changes something and this server is read-only: start it with "
                "--allow-write, or pass MCPPolicy(allow_write=True)",
                READ_ONLY,
            )

    def require_overwrite(self, tool: str) -> None:
        self.require_write(tool)
        if not self.allow_overwrite:
            raise MCPPermissionException(
                f"{tool} would replace an existing file and this server does not allow it: "
                "start it with --allow-overwrite, or pass MCPPolicy(allow_overwrite=True)",
                OVERWRITE_NOT_ALLOWED,
            )

    def require_delete(self, tool: str) -> None:
        self.require_write(tool)
        if not self.allow_delete:
            raise MCPPermissionException(
                f"{tool} deletes something and this server does not allow it: start it "
                "with --allow-delete, or pass MCPPolicy(allow_delete=True)",
                DELETE_NOT_ALLOWED,
            )

    def clamp_results(self, wanted: int | None) -> int:
        """Return how many entries a call may return: ``wanted``, at most ``max_results``."""
        return self.max_results if wanted is None else min(wanted, self.max_results)

    # ------------------------------------------------------------------ description

    def describe(self) -> dict[str, Any]:
        """Return the policy as a JSON-friendly mapping."""
        actions = self.pipeline_actions
        return {
            "roots": [str(root) for root in self.root_uris],
            "allow_write": self.allow_write,
            "allow_overwrite": self.allow_overwrite,
            "allow_delete": self.allow_delete,
            "max_read_bytes": self.max_read_bytes,
            "max_write_bytes": self.max_write_bytes,
            "max_results": self.max_results,
            "max_search_bytes": self.max_search_bytes,
            "pipeline_dir": None if self.pipeline_dir is None else str(self.pipeline_dir),
            "pipeline_actions": None if actions is None else sorted(actions),
            "tools": list(self.enabled_tools()),
            "actor": self.actor,
        }

    def summary(self) -> str:
        """Return the policy in a few sentences, for the ``instructions`` of the handshake."""
        roots = ", ".join(str(root) for root in self.root_uris)
        switches = (
            ("writing", self.allow_write),
            ("replacing existing files", self.allow_overwrite),
            ("deleting (a move deletes its source)", self.allow_delete),
        )
        allowed = [name for name, enabled in switches if enabled]
        refused = [name for name, enabled in switches if not enabled]
        lines = [
            "Semantic tools take storage URIs (<scheme>://<authority>/<path>) or absolute "
            "local paths.",
            f"Allowed locations: {roots}." if roots else "No location is allowed yet.",
            f"Allowed: reading{''.join(f', {name}' for name in allowed)}.",
        ]
        if refused:
            lines.append(f"Refused: {', '.join(refused)}.")
        lines.append(
            "Tools that change something take dry_run=true to report what they would do. "
            "Every result carries a correlation_id that audit_search accepts."
        )
        return " ".join(lines)


class StorageGuard(StorageResolver):
    """A resolver that serves only the locations a policy allows."""

    def __init__(self, policy: MCPPolicy, inner: StorageResolver | None = None) -> None:
        super().__init__(defaults=False)
        self._policy = policy
        self._inner = inner if inner is not None else default_resolver
        self._confined: dict[StorageURI, LocalStorage] = {}
        self._confined_lock = threading.Lock()

    @property
    def policy(self) -> MCPPolicy:
        return self._policy

    @property
    def inner(self) -> StorageResolver:
        """The resolver that knows the backends; the guard only decides what may be asked."""
        return self._inner

    def resolve(self, uri: URILike) -> tuple[StorageBackend, str]:
        """Return the backend and path of ``uri``, or raise :class:`MCPLocationException`."""
        parsed = parse_storage_uri(uri)
        candidates = self._policy.candidates(parsed)
        backend, path = self._inner.resolve(parsed)
        if not isinstance(backend, LocalStorage):
            return backend, path
        for root, relative in candidates:
            try:
                return self._confine(root, relative, backend, path)
            except PathTraversalException:
                continue
        raise MCPLocationException(
            f"{parsed} leaves the allowed location through a link or an absolute path",
            OUTSIDE_ROOT,
        )

    def _confine(
        self, root: StorageURI, relative: str, backend: LocalStorage, path: str
    ) -> tuple[StorageBackend, str]:
        """Serve a local location from a backend confined to ``root``.

        A mount of its own below the root, and a root that is the backend's own
        root, are already confined by the backend that serves them.
        """
        root_backend, root_path = self._inner.resolve(root)
        if (
            root_path
            and isinstance(root_backend, LocalStorage)
            and root_backend.root == backend.root
        ):
            backend = self._confined_backend(root, root_backend.local_path(root_path))
            path = relative
        if backend.root is None:
            return backend, path  # the root is the whole filesystem: nothing to confine to
        if _WINDOWS and names_windows_device(path):
            raise MCPLocationException(
                f"{root.joinpath(relative)} names a Windows device or a data stream, not a "
                "file in the allowed location",
                OUTSIDE_ROOT,
            )
        backend.local_path(path)
        return backend, path

    def _confined_backend(self, root: StorageURI, directory: os.PathLike[str]) -> LocalStorage:
        with self._confined_lock:
            backend = self._confined.get(root)
            if backend is None:
                backend = self._confined[root] = LocalStorage(directory)
            return backend


def names_from(values: Iterable[str]) -> frozenset[str]:
    """Return the non-empty, stripped names of ``values`` (for comma-separated flags)."""
    return frozenset(name.strip() for name in values if name.strip())
