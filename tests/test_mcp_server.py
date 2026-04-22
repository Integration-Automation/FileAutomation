"""Tests for the MCP server bridge."""

from __future__ import annotations

import io
import json

import pytest

from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import MCPServerException
from automation_file.server.mcp_server import (
    MCPServer,
    _cli,
    _filtered_registry,
    tools_from_registry,
)


def _make_registry() -> ActionRegistry:
    registry = ActionRegistry()

    def echo(message: str, repeat: int = 1) -> str:
        """Echo ``message`` back, optionally repeated."""
        return message * repeat

    def add(a: int, b: int) -> int:
        return a + b

    registry.register("echo", echo)
    registry.register("add", add)
    return registry


def test_initialize_returns_server_info() -> None:
    server = MCPServer(_make_registry(), name="test", version="9.9.9")
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert response is not None
    assert response["id"] == 1
    result = response["result"]
    assert result["serverInfo"] == {"name": "test", "version": "9.9.9"}
    assert "tools" in result["capabilities"]


def test_initialized_notification_returns_none() -> None:
    server = MCPServer(_make_registry())
    out = server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert out is None


def test_tools_list_advertises_registered_actions() -> None:
    server = MCPServer(_make_registry())
    response = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert response is not None
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert {"echo", "add"} <= names
    echo_tool = next(tool for tool in response["result"]["tools"] if tool["name"] == "echo")
    assert "Echo" in echo_tool["description"]
    assert echo_tool["inputSchema"]["type"] == "object"
    assert "message" in echo_tool["inputSchema"]["properties"]
    assert echo_tool["inputSchema"]["required"] == ["message"]


def test_tools_call_dispatches_registered_action() -> None:
    server = MCPServer(_make_registry())
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "add", "arguments": {"a": 2, "b": 5}},
        }
    )
    assert response is not None
    assert response["result"]["isError"] is False
    assert response["result"]["content"][0]["type"] == "text"
    assert response["result"]["content"][0]["text"] == "7"


def test_tools_call_reports_unknown_tool() -> None:
    server = MCPServer(_make_registry())
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        }
    )
    assert response is not None
    assert response["error"]["code"] == -32602
    assert "unknown tool" in response["error"]["message"]


def test_tools_call_reports_bad_arguments() -> None:
    server = MCPServer(_make_registry())
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "add", "arguments": {"a": 1}},
        }
    )
    assert response is not None
    assert response["error"]["code"] == -32602


def test_unknown_method_returns_method_not_found() -> None:
    server = MCPServer(_make_registry())
    response = server.handle_message({"jsonrpc": "2.0", "id": 6, "method": "no/such"})
    assert response is not None
    assert response["error"]["code"] == -32601


def test_invalid_envelope_returns_invalid_request() -> None:
    server = MCPServer(_make_registry())
    response = server.handle_message({"jsonrpc": "1.0", "method": "initialize"})
    assert response is not None
    assert response["error"]["code"] == -32600


def test_serve_stdio_consumes_stream() -> None:
    server = MCPServer(_make_registry())
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"message": "hi", "repeat": 2}},
            }
        )
        + "\n"
    )
    stdout = io.StringIO()
    server.serve_stdio(stdin=stdin, stdout=stdout)
    lines = [line for line in stdout.getvalue().splitlines() if line]
    assert len(lines) == 2
    init, call = (json.loads(line) for line in lines)
    assert init["id"] == 1 and "serverInfo" in init["result"]
    assert call["id"] == 2
    assert call["result"]["content"][0]["text"] == '"hihi"'


def test_tools_from_registry_helper_yields_all_tools() -> None:
    tools = list(tools_from_registry(_make_registry()))
    assert {tool["name"] for tool in tools} == {"echo", "add"}


def test_serve_stdio_handles_malformed_json() -> None:
    server = MCPServer(_make_registry())
    stdin = io.StringIO("not-json\n")
    stdout = io.StringIO()
    server.serve_stdio(stdin=stdin, stdout=stdout)
    reply = json.loads(stdout.getvalue().strip())
    assert reply["error"]["code"] == -32700


def test_filtered_registry_keeps_only_allowed_actions() -> None:
    filtered = _filtered_registry(_make_registry(), ["add"])
    assert set(filtered.event_dict.keys()) == {"add"}


def test_filtered_registry_raises_on_unknown_name() -> None:
    with pytest.raises(MCPServerException, match="unknown action"):
        _filtered_registry(_make_registry(), ["add", "does_not_exist"])


def test_cli_serves_whitelisted_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeServer:
        def __init__(self, registry: ActionRegistry, *, name: str, version: str) -> None:
            captured["tools"] = set(registry.event_dict.keys())
            captured["name"] = name
            captured["version"] = version

        def serve_stdio(self) -> None:
            captured["served"] = True

    stub_registry = _make_registry()
    monkeypatch.setattr("automation_file.server.mcp_server.executor.registry", stub_registry)
    monkeypatch.setattr("automation_file.server.mcp_server.MCPServer", _FakeServer)

    rc = _cli(["--allowed-actions", "echo", "--name", "t", "--version", "2.0.0"])
    assert rc == 0
    assert captured["tools"] == {"echo"}
    assert captured["name"] == "t"
    assert captured["version"] == "2.0.0"
    assert captured["served"] is True
