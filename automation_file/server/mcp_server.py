"""Model Context Protocol (MCP) server bridge.

Exposes every :class:`~automation_file.core.action_registry.ActionRegistry`
entry as an MCP tool over JSON-RPC 2.0. The default transport is stdio —
one JSON message per line — because that's what MCP host implementations
(Claude Desktop, MCP CLIs) consume today.

Scope
-----
* ``initialize``              — handshake, returns ``serverInfo`` + capabilities
* ``notifications/initialized`` — acknowledged as a no-op
* ``tools/list``              — lists registered actions as MCP tools
* ``tools/call``              — dispatches through the action registry

Errors surface as JSON-RPC error objects with a ``MCPServerException`` chain
in the data field, so hosts can render them without having to parse the
exception string.
"""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Callable, Iterable
from typing import Any, TextIO

from automation_file.core.action_executor import executor
from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import MCPServerException
from automation_file.logging_config import file_automation_logger

_JSONRPC_VERSION = "2.0"
_PROTOCOL_VERSION = "2024-11-05"

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


class MCPServer:
    """Bridge between an MCP host and an :class:`ActionRegistry`."""

    def __init__(
        self,
        registry: ActionRegistry | None = None,
        *,
        name: str = "automation_file",
        version: str = "1.0.0",
    ) -> None:
        self._registry = registry if registry is not None else executor.registry
        self._name = name
        self._version = version
        self._initialized = False

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch a single decoded JSON-RPC message.

        Returns the response dict for request messages, or ``None`` for
        notifications (which get no reply). Protocol-level errors return a
        JSON-RPC error object rather than raising.
        """
        if not isinstance(message, dict) or message.get("jsonrpc") != _JSONRPC_VERSION:
            return _error_response(None, _INVALID_REQUEST, "invalid JSON-RPC envelope")

        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}

        if not isinstance(method, str):
            return _error_response(msg_id, _INVALID_REQUEST, "missing method")

        is_notification = msg_id is None
        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "notifications/initialized":
                self._initialized = True
                return None
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            else:
                return _error_response(msg_id, _METHOD_NOT_FOUND, f"unknown method: {method}")
        except MCPServerException as error:
            return _error_response(msg_id, _INVALID_PARAMS, str(error))
        except Exception as error:
            file_automation_logger.warning("mcp_server: internal error: %r", error)
            return _error_response(msg_id, _INTERNAL_ERROR, f"{type(error).__name__}: {error}")

        if is_notification:
            return None
        return {"jsonrpc": _JSONRPC_VERSION, "id": msg_id, "result": result}

    def serve_stdio(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        """Run the server over newline-delimited JSON on ``stdin`` / ``stdout``."""
        reader = stdin if stdin is not None else sys.stdin
        writer = stdout if stdout is not None else sys.stdout
        for line in reader:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                message = json.loads(stripped)
            except json.JSONDecodeError as error:
                self._write(writer, _error_response(None, _PARSE_ERROR, f"bad json: {error}"))
                continue
            response = self.handle_message(message)
            if response is not None:
                self._write(writer, response)

    def _handle_initialize(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self._name, "version": self._version},
        }

    def _handle_tools_list(self) -> dict[str, Any]:
        tools = []
        for name, command in sorted(self._registry.event_dict.items()):
            tools.append(
                {
                    "name": name,
                    "description": _describe(command),
                    "inputSchema": _schema_for(command),
                }
            )
        return {"tools": tools}

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            raise MCPServerException("tools/call requires a string 'name'")
        if not isinstance(arguments, dict):
            raise MCPServerException("'arguments' must be an object")
        command = self._registry.resolve(name)
        if command is None:
            raise MCPServerException(f"unknown tool: {name}")
        try:
            value = command(**arguments)
        except TypeError as error:
            raise MCPServerException(f"bad arguments for {name}: {error}") from error
        return {
            "content": [{"type": "text", "text": _serialise(value)}],
            "isError": False,
        }

    @staticmethod
    def _write(writer: TextIO, response: dict[str, Any]) -> None:
        writer.write(json.dumps(response, default=repr) + "\n")
        writer.flush()


def _error_response(msg_id: object, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": _JSONRPC_VERSION,
        "id": msg_id,
        "error": {"code": code, "message": message},
    }


def _describe(command: Callable[..., Any]) -> str:
    doc = inspect.getdoc(command) or ""
    return doc.splitlines()[0] if doc else "Registered automation_file action."


def _schema_for(command: Callable[..., Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(command)
    except (TypeError, ValueError):
        return {"type": "object", "properties": {}, "additionalProperties": True}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if parameter.name in {"self", "cls"}:
            continue
        properties[parameter.name] = _json_schema_for(parameter.annotation)
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    return schema


def _json_schema_for(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty:
        return {}
    mapping: dict[type, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    if isinstance(annotation, type) and annotation in mapping:
        return {"type": mapping[annotation]}
    return {}


def _serialise(value: Any) -> str:
    try:
        return json.dumps(value, default=repr)
    except (TypeError, ValueError):
        return repr(value)


def tools_from_registry(registry: ActionRegistry) -> Iterable[dict[str, Any]]:
    """Yield MCP-shaped tool descriptors for every entry in ``registry``.

    Exposed separately so GUIs and tests can render the same catalogue
    without instantiating :class:`MCPServer`.
    """
    server = MCPServer(registry)
    yield from server._handle_tools_list()["tools"]
