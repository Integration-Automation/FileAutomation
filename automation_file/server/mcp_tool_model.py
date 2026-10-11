"""What a semantic MCP tool is made of: a descriptor, checked arguments and a session.

A :class:`SemanticTool` pairs a hand-written JSON input schema with a plain
function ``handler(session, arguments) -> dict``. The schema is what an MCP host
shows its model, so every description says what the argument means; the same
schema checks the arguments before the handler runs
(:func:`checked_arguments`). A :class:`ToolSession` carries what every handler
needs: the policy and the guarded way to storage.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from automation_file.server.mcp_policy import MCPPolicy, MCPToolException, StorageGuard
from automation_file.storage.file import File
from automation_file.storage.storage import Storage

if TYPE_CHECKING:
    from automation_file.core.action_registry import ActionRegistry

URI_HELP = (
    "A storage URI, <scheme>://<authority>/<path>: local:///srv/reports/a.csv, "
    "s3://bucket/2026/a.csv, sftp://host/inbox/a.csv, memory://name/a.csv. An absolute "
    "local path works too. It must be inside a location this server allows."
)
DRY_RUN_HELP = "When true, change nothing and report what the call would do."
OVERWRITE_HELP = (
    "Replace a file that already exists at the target. Off by default; the server must "
    "allow overwriting as well."
)
MAX_RESULTS_HELP = "Return at most this many entries. The server caps it."

_JSON_TYPES: Mapping[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}
_BOOLEAN = "boolean"


def text(description: str, **extra: Any) -> dict[str, Any]:
    """Return the schema of a string argument."""
    return {"type": "string", "description": description, **extra}


def flag(description: str, default: bool = False) -> dict[str, Any]:
    """Return the schema of a boolean argument."""
    return {"type": _BOOLEAN, "description": description, "default": default}


def whole(description: str, minimum: int = 1, **extra: Any) -> dict[str, Any]:
    """Return the schema of an integer argument."""
    return {"type": "integer", "description": description, "minimum": minimum, **extra}


def arguments_schema(
    properties: Mapping[str, Mapping[str, Any]], required: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Return the input schema of a tool: an object that takes exactly ``properties``."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {name: dict(spec) for name, spec in properties.items()},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


@dataclass
class ToolSession:
    """What a tool handler works with. ``state`` holds what a tool module keeps per server."""

    policy: MCPPolicy
    guard: StorageGuard
    registry: ActionRegistry
    state: dict[str, Any] = field(default_factory=dict)

    def file(self, uri: str) -> File:
        """Return the :class:`File` at ``uri``, reachable only inside the allowed locations."""
        return File(uri, resolver=self.guard)

    def storage(self, uri: str) -> Storage:
        """Return the :class:`Storage` at ``uri``, reachable only inside the allowed locations."""
        return Storage(uri, resolver=self.guard)


ToolHandler = Callable[[ToolSession, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class SemanticTool:
    """One semantic tool. ``changes`` marks a tool that needs writing and takes ``dry_run``."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: ToolHandler
    changes: bool = False

    def descriptor(self) -> dict[str, Any]:
        """Return the tool as ``tools/list`` describes it."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": copy.deepcopy(dict(self.input_schema)),
        }


def _type_problem(name: str, spec: Mapping[str, Any], value: object) -> str | None:
    wanted = spec["type"]
    is_boolean = isinstance(value, bool)
    if is_boolean != (wanted == _BOOLEAN) or not isinstance(value, _JSON_TYPES[wanted]):
        return f"'{name}' must be of type {wanted}"
    return None


def _value_problem(name: str, spec: Mapping[str, Any], value: Any) -> str | None:
    if "enum" in spec and value not in spec["enum"]:
        return f"'{name}' must be one of {', '.join(map(str, spec['enum']))}"
    if "minimum" in spec and value < spec["minimum"]:
        return f"'{name}' must be {spec['minimum']} or more"
    if "minLength" in spec and len(value) < spec["minLength"]:
        return f"'{name}' must not be empty"
    if "maxLength" in spec and len(value) > spec["maxLength"]:
        return f"'{name}' is longer than {spec['maxLength']} characters"
    return None


def checked_arguments(tool: SemanticTool, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``arguments`` checked against the tool's schema, with its defaults filled in.

    An argument given as ``null`` counts as left out. Raises
    :class:`MCPToolException` naming every problem; argument values are never
    part of the message.
    """
    properties: Mapping[str, Mapping[str, Any]] = tool.input_schema["properties"]
    given = {name: value for name, value in arguments.items() if value is not None}
    problems = [
        f"'{name}' is not an argument of {tool.name}" for name in given if name not in properties
    ]
    problems.extend(
        f"'{name}' is required"
        for name in tool.input_schema.get("required", ())
        if name not in given
    )
    for name, value in given.items():
        spec = properties.get(name)
        if spec is None:
            continue
        problem = _type_problem(name, spec, value) or _value_problem(name, spec, value)
        if problem is not None:
            problems.append(problem)
    if problems:
        raise MCPToolException(f"{tool.name}: {'; '.join(problems)}")
    defaults = {name: spec["default"] for name, spec in properties.items() if "default" in spec}
    return {**defaults, **given}
