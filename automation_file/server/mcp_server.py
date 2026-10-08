"""Model Context Protocol (MCP) server.

Speaks JSON-RPC 2.0 over stdio, one JSON message per line, which is what MCP
hosts (Claude Desktop, Claude Code, MCP CLIs) consume. It offers two sets of
tools:

* the **semantic tools** (:mod:`automation_file.server.mcp_tools`): fourteen
  stable, task-shaped names such as ``file_read`` and ``pipeline_run``, bound to
  an :class:`~automation_file.server.mcp_policy.MCPPolicy` that says where they
  may work and what they may change;
* the **bridge**: every entry of an
  :class:`~automation_file.core.action_registry.ActionRegistry` as a tool of its
  own (``FA_*``), with a schema derived from its signature. It is on by default
  and ``bridge=False`` leaves only the semantic tools.

Scope
-----
* ``initialize``              — handshake, returns ``serverInfo`` + capabilities
* ``notifications/initialized`` — acknowledged as a no-op
* ``tools/list``              — the semantic tools, then the registered actions
* ``tools/call``              — runs a semantic tool, or dispatches through the registry

A protocol error, an unknown tool and a bridge call that fails surface as
JSON-RPC error objects. A semantic tool that is refused or fails answers with a
result whose ``isError`` is true and whose text says why, so the model sees it.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Any, TextIO

from automation_file.core.action_executor import executor
from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import MCPServerException, StorageURIException
from automation_file.logging_config import file_automation_logger
from automation_file.server.action_acl import nested_action_names
from automation_file.server.mcp_policy import MCPPolicy, names_from
from automation_file.server.mcp_tools import SemanticToolkit

_JSONRPC_VERSION = "2.0"
_PROTOCOL_VERSION = "2024-11-05"

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

_NO_TOOLS = "none"
#: CLI destination -> ``MCPPolicy`` field, for the flags that carry one value.
_POLICY_VALUES = (
    "max_read_bytes",
    "max_write_bytes",
    "max_results",
    "max_search_bytes",
    "pipeline_dir",
)
_POLICY_SWITCHES = ("allow_write", "allow_overwrite", "allow_delete")


class MCPServer:
    """An MCP server over an :class:`ActionRegistry` and an :class:`MCPPolicy`.

    ``policy`` governs the semantic tools; without one they are read-only and no
    location is allowed. ``bridge=False`` stops offering the registry's actions
    as tools.
    """

    def __init__(
        self,
        registry: ActionRegistry | None = None,
        *,
        name: str = "automation_file",
        version: str = "1.0.0",
        policy: MCPPolicy | None = None,
        bridge: bool = True,
    ) -> None:
        self._registry = registry if registry is not None else executor.registry
        self._name = name
        self._version = version
        self._bridge = bridge
        self._toolkit = SemanticToolkit(policy, self._registry)
        self._initialized = False

    @property
    def toolkit(self) -> SemanticToolkit:
        """The semantic tools of this server, bound to its policy."""
        return self._toolkit

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
        except Exception as error:  # pylint: disable=broad-exception-caught
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

    def _handle_initialize(self, params: object) -> dict[str, Any]:
        client = params.get("clientInfo") if isinstance(params, dict) else None
        self._toolkit.set_client(client.get("name") if isinstance(client, dict) else None)
        result: dict[str, Any] = {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self._name, "version": self._version},
        }
        if self._toolkit.policy.enabled_tools():
            result["instructions"] = self._toolkit.instructions()
        return result

    def _handle_tools_list(self) -> dict[str, Any]:
        tools = self._toolkit.descriptors()
        if self._bridge:
            # A registered action that took a semantic name would be unreachable: leave it out.
            tools.extend(
                tool for tool in _catalogue(self._registry) if not self._toolkit.owns(tool["name"])
            )
        return {"tools": tools}

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            raise MCPServerException("tools/call requires a string 'name'")
        if not isinstance(arguments, dict):
            raise MCPServerException("'arguments' must be an object")
        if self._toolkit.owns(name):
            return self._toolkit.call(name, arguments).to_mcp()
        command = self._registry.resolve(name) if self._bridge else None
        if command is None:
            raise MCPServerException(f"unknown tool: {name}")
        self._require_exposed(name, arguments)
        try:
            value = command(**arguments)
        except TypeError as error:
            raise MCPServerException(f"bad arguments for {name}: {error}") from error
        return {
            "content": [{"type": "text", "text": _serialise(value)}],
            "isError": False,
        }

    def _require_exposed(self, name: str, arguments: dict[str, Any]) -> None:
        """Refuse a call whose arguments name an action this server does not expose.

        A tool such as ``FA_execute_action`` or ``FA_pipeline_run`` runs the actions
        its arguments name through the shared executor, whatever this server's
        registry was narrowed to. Without the check an allow list would stop at the
        tool name.
        """
        for nested in nested_action_names(arguments, executor.registry.event_dict):
            if self._registry.resolve(nested) is None:
                raise MCPServerException(
                    f"{name} names the action {nested}, which this server does not expose"
                )

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
    yield from _catalogue(registry)


def _catalogue(registry: ActionRegistry) -> Iterable[dict[str, Any]]:
    for name, command in sorted(registry.event_dict.items()):
        yield {
            "name": name,
            "description": _describe(command),
            "inputSchema": _schema_for(command),
        }


def _filtered_registry(source: ActionRegistry, allowed: Sequence[str]) -> ActionRegistry:
    filtered = ActionRegistry()
    missing: list[str] = []
    for name in allowed:
        command = source.resolve(name)
        if command is None:
            missing.append(name)
            continue
        filtered.register(name, command)
    if missing:
        raise MCPServerException("unknown action(s) in allow list: " + ", ".join(sorted(missing)))
    return filtered


def add_semantic_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the flags of the semantic tools to ``parser``: the policy and ``--no-bridge``.

    A command line that wraps this one (``python -m automation_file mcp``) adds
    them to its own parser with this function and passes them on with
    :func:`semantic_argv`, so the two never differ.
    """
    group = parser.add_argument_group(
        "semantic tools",
        "file_read, file_write, storage_copy, pipeline_run and the others. Without --root "
        "they refuse every storage location, and without --allow-write they only read.",
    )
    group.add_argument(
        "--root",
        action="append",
        default=None,
        metavar="URI",
        help="a location the semantic tools may work in: a storage URI or a local "
        "directory (repeatable)",
    )
    group.add_argument("--allow-write", action="store_true", help="let the tools create files")
    group.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="let them replace a file that exists (needs --allow-write)",
    )
    group.add_argument(
        "--allow-delete",
        action="store_true",
        help="let them delete; a move deletes its source (needs --allow-write)",
    )
    for flag, meaning in (
        ("--max-read-bytes", "most bytes file_read returns in one call"),
        ("--max-write-bytes", "largest content file_write and pipeline_create accept"),
        ("--max-results", "most entries a listing, a search or audit_search returns"),
        ("--max-search-bytes", "most bytes one content search reads"),
    ):
        group.add_argument(flag, type=int, default=None, metavar="N", help=meaning)
    group.add_argument(
        "--pipeline-dir",
        default=None,
        metavar="URI",
        help="where pipeline_create keeps definitions: a storage URI or a local directory "
        "(default: in memory, until the server stops)",
    )
    group.add_argument(
        "--pipeline-actions",
        default=None,
        metavar="NAMES",
        help="comma-separated actions a pipeline run through MCP may call (default: the "
        "FA_storage_* actions the permissions cover)",
    )
    group.add_argument(
        "--tools",
        default=None,
        metavar="NAMES",
        help=f"comma-separated semantic tools to offer, or '{_NO_TOOLS}' (default: all fourteen)",
    )
    group.add_argument(
        "--no-bridge",
        action="store_true",
        help="do not offer the registered FA_* actions as tools; only the semantic tools",
    )


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="automation_file_mcp",
        description="Serve the semantic tools and the automation_file action registry as "
        "an MCP server over stdio.",
    )
    parser.add_argument(
        "--name", default="automation_file", help="serverInfo.name reported at handshake"
    )
    parser.add_argument(
        "--version", default="1.0.0", help="serverInfo.version reported at handshake"
    )
    parser.add_argument(
        "--allowed-actions",
        default=None,
        help=(
            "comma-separated allow list of action names (e.g. "
            "'FA_list_dir,FA_file_checksum'); defaults to every registered action"
        ),
    )
    add_semantic_arguments(parser)
    return parser


def semantic_argv(args: argparse.Namespace) -> list[str]:
    """Return the flags of :func:`add_semantic_arguments` that ``args`` holds, as arguments again.

    A flag that was not given is left out, so a command line without any of them
    gives an empty list.
    """
    argv: list[str] = []
    for root in args.root or ():
        argv.extend(["--root", root])
    argv.extend(_flag(name) for name in _POLICY_SWITCHES if getattr(args, name))
    for name in (*_POLICY_VALUES, "pipeline_actions", "tools"):
        value = getattr(args, name)
        if value is not None:
            argv.extend([_flag(name), str(value)])
    if args.no_bridge:
        argv.append("--no-bridge")
    return argv


def _flag(destination: str) -> str:
    return "--" + destination.replace("_", "-")


def _policy_options(args: argparse.Namespace) -> dict[str, Any]:
    """Return the ``MCPPolicy`` fields the command line set; an absent flag is left out."""
    options: dict[str, Any] = {name: True for name in _POLICY_SWITCHES if getattr(args, name)}
    for name in _POLICY_VALUES:
        value = getattr(args, name)
        if value is not None:
            options[name] = value
    if args.root:
        options["roots"] = tuple(args.root)
    if args.pipeline_actions is not None:
        options["pipeline_actions"] = names_from(args.pipeline_actions.split(","))
    if args.tools is not None:
        chosen = "" if args.tools.strip().lower() == _NO_TOOLS else args.tools
        options["tools"] = names_from(chosen.split(","))
    return options


def _server_options(args: argparse.Namespace) -> dict[str, Any]:
    """Return the keyword arguments of :class:`MCPServer` that differ from its defaults."""
    options: dict[str, Any] = {}
    policy = _policy_options(args)
    if policy:
        options["policy"] = MCPPolicy(**policy)
    if args.no_bridge:
        options["bridge"] = False
    return options


def _cli(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point for the MCP stdio server."""
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    registry = executor.registry
    if args.allowed_actions:
        names = [name.strip() for name in args.allowed_actions.split(",") if name.strip()]
        registry = _filtered_registry(registry, names)
    try:
        server = MCPServer(registry, name=args.name, version=args.version, **_server_options(args))
    except (MCPServerException, StorageURIException) as error:
        parser.error(str(error))
    file_automation_logger.info(
        "mcp_server: serving over stdio (name=%s version=%s bridge=%s actions=%d)",
        args.name,
        args.version,
        "off" if args.no_bridge else "on",
        len(registry.event_dict),
    )
    server.serve_stdio()
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
