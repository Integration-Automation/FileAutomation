"""The semantic tools over JSON-RPC, next to the ``FA_*`` bridge, and the server's flags."""

# pylint: disable=unnecessary-lambda  # the lambda is looked up late, when it is called
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import argparse
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import MCPServerException
from automation_file.server.mcp_policy import (
    DEFAULT_MAX_READ_BYTES,
    SEMANTIC_TOOL_NAMES,
    MCPPolicy,
)
from automation_file.server.mcp_server import (
    MCPServer,
    _build_cli_parser,
    _cli,
    _server_options,
    add_semantic_arguments,
    semantic_argv,
)
from automation_file.storage import File, parse_storage_uri
from tests.mcp_support import INBOX, clean_state

A = f"{INBOX}/a.txt"


@pytest.fixture(autouse=True)
def _state() -> Iterator[None]:
    with clean_state():
        File(A).write("alpha")
        yield


def _registry() -> ActionRegistry:
    def echo(message: str, repeat: int = 1) -> str:
        """Echo ``message`` back, optionally repeated."""
        return message * repeat

    def add(a: int, b: int) -> int:
        return a + b

    return ActionRegistry({"echo": echo, "add": add})


def _server(*, bridge: bool = True, **policy: Any) -> MCPServer:
    policy.setdefault("roots", (INBOX,))
    return MCPServer(_registry(), policy=MCPPolicy(**policy), bridge=bridge)


def _request(server: MCPServer, method: str, params: dict | None = None) -> dict:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": 7, "method": method}
    if params is not None:
        message["params"] = params
    response = server.handle_message(message)
    assert response is not None
    assert response["id"] == 7
    return response


def _call(server: MCPServer, name: str, arguments: dict | None = None) -> dict:
    params: dict[str, Any] = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    return _request(server, "tools/call", params)


def _payload(response: dict) -> dict:
    """Return the JSON document a semantic tool answered with."""
    result = response["result"]
    assert [block["type"] for block in result["content"]] == ["text"]
    return json.loads(result["content"][0]["text"])


def _names(server: MCPServer) -> list[str]:
    return [tool["name"] for tool in _request(server, "tools/list")["result"]["tools"]]


# ---------------------------------------------------------------------- tools/list


def test_tools_list_returns_the_semantic_tools_first_and_then_the_bridge() -> None:
    assert _names(_server()) == [*SEMANTIC_TOOL_NAMES, "add", "echo"]


def test_a_server_without_a_policy_still_lists_both_sets() -> None:
    names = _names(MCPServer(_registry()))
    assert names[:14] == list(SEMANTIC_TOOL_NAMES)
    assert names[14:] == ["add", "echo"]


def test_the_default_server_lists_the_semantic_tools_before_every_registered_action() -> None:
    names = _names(MCPServer())
    assert names[:14] == list(SEMANTIC_TOOL_NAMES)
    assert "FA_storage_copy" in names[14:]
    assert names[14:] == sorted(names[14:])
    assert len(names) == len(set(names))


def test_the_listed_schemas_are_hand_written_and_closed() -> None:
    tools = {tool["name"]: tool for tool in _request(_server(), "tools/list")["result"]["tools"]}
    for name in SEMANTIC_TOOL_NAMES:
        schema = tools[name]["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert tools[name]["description"]
        assert all("description" in spec for spec in schema["properties"].values())
    copy = tools["file_copy"]["inputSchema"]
    assert copy["required"] == ["source", "target"]
    assert set(copy["properties"]) == {"source", "target", "overwrite", "verify", "dry_run"}
    assert copy["properties"]["dry_run"] == {
        "type": "boolean",
        "description": "When true, change nothing and report what the call would do.",
        "default": False,
    }
    assert tools["file_read"]["inputSchema"]["properties"]["offset"]["minimum"] == 0
    assert tools["pipeline_create"]["inputSchema"]["properties"]["definition"]["type"] == "object"
    assert "required" not in tools["audit_search"]["inputSchema"]
    # The bridge keeps the schema it derives from a signature.
    assert tools["echo"]["inputSchema"]["additionalProperties"] is True
    assert tools["echo"]["inputSchema"]["required"] == ["message"]


def test_without_the_bridge_only_the_semantic_tools_are_listed() -> None:
    assert _names(_server(bridge=False)) == list(SEMANTIC_TOOL_NAMES)


def test_the_tool_list_of_the_policy_narrows_what_is_listed() -> None:
    server = _server(tools=["storage_list", "file_read"])
    assert _names(server) == ["file_read", "storage_list", "add", "echo"]
    assert _names(_server(tools=[], bridge=False)) == []


def test_a_registered_action_with_a_semantic_name_is_not_listed_twice() -> None:
    registry = _registry()
    registry.register("file_read", lambda uri: "from the registry")
    server = MCPServer(registry, policy=MCPPolicy(roots=[INBOX]))
    assert _names(server).count("file_read") == 1
    assert _payload(_call(server, "file_read", {"uri": A}))["content"] == "alpha"


# ---------------------------------------------------------------------- tools/call


def test_a_semantic_call_answers_with_a_json_document() -> None:
    response = _call(_server(), "file_read", {"uri": A})
    assert response["result"]["isError"] is False
    payload = _payload(response)
    assert payload["tool"] == "file_read"
    assert payload["content"] == "alpha"
    assert len(payload["correlation_id"]) == 32


def test_a_refused_call_is_a_tool_error_with_a_reason_not_a_protocol_error() -> None:
    response = _call(_server(), "file_write", {"uri": f"{INBOX}/b.txt", "content": "x"})
    assert "error" not in response
    assert response["result"]["isError"] is True
    payload = _payload(response)
    assert payload["error"]["type"] == "permission_denied"
    assert payload["error"]["code"] == "read_only"
    assert "--allow-write" in payload["error"]["message"]
    assert len(payload["correlation_id"]) == 32
    assert not File(f"{INBOX}/b.txt").exists()


def test_a_failed_call_and_wrong_arguments_are_tool_errors_too() -> None:
    server = _server()
    missing = _payload(_call(server, "file_read", {"uri": f"{INBOX}/absent.txt"}))
    assert missing["error"]["type"] == "not_found"
    wrong = _call(server, "file_read", {"uri": A, "offset": "three"})
    assert wrong["result"]["isError"] is True
    assert _payload(wrong)["error"]["type"] == "invalid_arguments"
    none = _call(server, "file_read")
    assert "'uri' is required" in _payload(none)["error"]["message"]


def test_a_location_outside_the_roots_is_refused_over_json_rpc() -> None:
    File("memory://box/in-b/a.txt").write("neighbour")
    payload = _payload(_call(_server(), "file_read", {"uri": "memory://box/in-b/a.txt"}))
    assert payload["error"]["code"] == "outside_root"
    assert "neighbour" not in json.dumps(payload)


def test_a_server_without_a_root_says_how_to_configure_one() -> None:
    payload = _payload(_call(MCPServer(_registry()), "storage_list", {"uri": INBOX}))
    assert payload["error"]["code"] == "no_root"
    assert "--root" in payload["error"]["message"]


def test_a_disabled_semantic_tool_is_refused_and_never_falls_through_to_the_bridge() -> None:
    registry = _registry()
    registry.register("file_read", lambda uri: "from the registry")
    server = MCPServer(registry, policy=MCPPolicy(roots=[INBOX], tools=["storage_list"]))
    payload = _payload(_call(server, "file_read", {"uri": A}))
    assert payload["error"]["code"] == "tool_disabled"


def test_arguments_that_are_not_an_object_are_a_protocol_error() -> None:
    response = _call(_server(), "file_read", ["memory://box/in/a.txt"])  # type: ignore[arg-type]
    assert response["error"]["code"] == -32602
    assert "'arguments' must be an object" in response["error"]["message"]


def test_the_bridge_still_dispatches_registered_actions() -> None:
    server = _server()
    response = _call(server, "add", {"a": 2, "b": 5})
    assert response["result"] == {"content": [{"type": "text", "text": "7"}], "isError": False}
    assert _call(server, "add", {"a": 1})["error"]["code"] == -32602
    assert "unknown tool" in _call(server, "nope", {})["error"]["message"]


def test_without_the_bridge_a_registered_action_is_an_unknown_tool() -> None:
    server = _server(bridge=False)
    response = _call(server, "add", {"a": 2, "b": 5})
    assert response["error"] == {"code": -32602, "message": "unknown tool: add"}
    assert _payload(_call(server, "file_read", {"uri": A}))["content"] == "alpha"


def test_a_whole_exchange_over_stdio() -> None:
    server = _server(allow_write=True)
    target = f"{INBOX}/b.txt"
    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "file_copy", "arguments": {"source": A, "target": target}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"message": "hi"}},
        },
    ]
    stdout = io.StringIO()
    server.serve_stdio(io.StringIO("".join(json.dumps(frame) + "\n" for frame in frames)), stdout)
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2, 3]
    assert _payload(replies[1])["done"] is True
    assert replies[2]["result"]["content"][0]["text"] == '"hi"'
    assert File(target).read() == b"alpha"


# ---------------------------------------------------------------------- the handshake


def test_initialize_describes_the_policy_in_its_instructions() -> None:
    result = _request(_server(), "initialize", {})["result"]
    assert result["serverInfo"] == {"name": "automation_file", "version": "1.0.0"}
    assert INBOX in result["instructions"]
    assert "Refused: writing" in result["instructions"]
    assert "instructions" not in _request(_server(tools=[]), "initialize", {})["result"]


def test_the_client_name_of_the_handshake_labels_the_actor() -> None:
    server = _server()
    assert server.toolkit.actor == "mcp"
    _request(server, "initialize", {"clientInfo": {"name": "claude-desktop", "version": "1"}})
    assert server.toolkit.actor == "mcp:claude-desktop"
    _request(server, "initialize", {"clientInfo": "not an object"})
    assert server.toolkit.actor == "mcp"


# ---------------------------------------------------------------------- pipelines and the registry


def test_a_pipeline_action_the_server_does_not_expose_is_refused_at_start() -> None:
    with pytest.raises(MCPServerException, match="FA_run_shell"):
        MCPServer(_registry(), policy=MCPPolicy(pipeline_actions=["FA_run_shell"]))
    server = MCPServer(_registry(), policy=MCPPolicy(pipeline_actions=["echo"]))
    assert server.toolkit.policy.pipeline_actions == frozenset({"echo"})


def test_a_pipeline_runs_over_json_rpc_with_a_listed_action() -> None:
    server = MCPServer(
        _registry(),
        policy=MCPPolicy(
            roots=[INBOX], allow_write=True, pipeline_actions=["FA_storage_copy", "echo"]
        ),
        bridge=False,
    )
    definition = {
        "schema_version": 1,
        "tasks": {
            "copy": {"action": ["FA_storage_copy", {"source": A, "target": f"{INBOX}/c.txt"}]},
            "say": {"action": ["echo", {"message": "done"}], "depends_on": ["copy"]},
        },
    }
    created = _payload(_call(server, "pipeline_create", {"name": "job", "definition": definition}))
    assert created["stored"] is True
    run = _payload(_call(server, "pipeline_run", {"name": "job"}))
    assert run["status"] == "succeeded"
    assert run["run"]["tasks"]["say"]["result"] == "done"
    status = _payload(_call(server, "pipeline_status", {"run_id": run["run_id"]}))
    assert status["runs"][0]["status"] == "succeeded"
    assert File(f"{INBOX}/c.txt").read() == b"alpha"


# ---------------------------------------------------------------------- the command line


def _options(*argv: str) -> dict[str, Any]:
    return _server_options(_build_cli_parser().parse_args(list(argv)))


def test_without_a_semantic_flag_the_server_gets_its_defaults() -> None:
    assert _options() == {}
    assert _options("--name", "x", "--allowed-actions", "echo") == {}


def test_the_flags_build_the_policy(tmp_path: Path) -> None:
    options = _options(
        "--root",
        str(tmp_path),
        "--root",
        "s3://bucket/team",
        "--allow-write",
        "--allow-overwrite",
        "--allow-delete",
        "--max-read-bytes",
        "1000",
        "--max-write-bytes",
        "2000",
        "--max-results",
        "30",
        "--max-search-bytes",
        "4000",
        "--pipeline-dir",
        str(tmp_path / "pipelines"),
        "--pipeline-actions",
        "FA_storage_copy, FA_storage_verify,",
        "--tools",
        "file_read,storage_list",
        "--no-bridge",
    )
    assert options["bridge"] is False
    policy = options["policy"]
    assert policy.root_uris == (parse_storage_uri(tmp_path), parse_storage_uri("s3://bucket/team"))
    assert (policy.allow_write, policy.allow_overwrite, policy.allow_delete) == (True, True, True)
    assert (policy.max_read_bytes, policy.max_write_bytes) == (1000, 2000)
    assert (policy.max_results, policy.max_search_bytes) == (30, 4000)
    assert policy.pipeline_dir == parse_storage_uri(tmp_path / "pipelines")
    assert policy.pipeline_actions == frozenset({"FA_storage_copy", "FA_storage_verify"})
    assert policy.enabled_tools() == ("file_read", "storage_list")


def test_one_flag_leaves_the_other_defaults_alone() -> None:
    policy = _options("--root", "memory://box/in")["policy"]
    assert policy.allow_write is False
    assert policy.max_read_bytes == DEFAULT_MAX_READ_BYTES
    assert policy.pipeline_actions is None
    assert policy.tools is None
    assert "bridge" not in _options("--root", "memory://box/in")
    assert _options("--no-bridge") == {"bridge": False}


def test_tools_none_switches_every_semantic_tool_off() -> None:
    assert _options("--tools", "none")["policy"].enabled_tools() == ()
    assert _options("--tools", "")["policy"].enabled_tools() == ()
    assert _options("--pipeline-actions", "")["policy"].pipeline_actions == frozenset()


@pytest.mark.parametrize(
    "argv",
    [
        ["--allow-overwrite"],
        ["--allow-delete"],
        ["--tools", "file_read,file_delete"],
        ["--max-results", "0"],
        ["--root", "sftp://user:secret@host/data"],
        ["--pipeline-actions", "FA_no_such_action"],
    ],
)
def test_a_wrong_flag_ends_the_command_with_a_usage_error(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        _cli(argv)
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert "error:" in captured.err
    assert "secret" not in captured.err
    assert captured.out == ""


def test_a_wrapping_command_line_adds_and_forwards_the_same_flags(tmp_path: Path) -> None:
    wrapper = argparse.ArgumentParser(prog="wrapper")
    add_semantic_arguments(wrapper)
    assert semantic_argv(wrapper.parse_args([])) == []
    argv = [
        "--no-bridge",
        "--tools",
        "file_read,storage_list",
        "--allow-delete",
        "--root",
        "memory://box/in",
        "--max-results",
        "30",
        "--pipeline-actions",
        "FA_storage_copy,FA_storage_verify",
        "--allow-write",
        "--root",
        str(tmp_path),
        "--pipeline-dir",
        "memory://box/definitions",
        "--max-read-bytes",
        "1000",
    ]
    forwarded = semantic_argv(wrapper.parse_args(argv))
    assert sorted(forwarded) == sorted(argv)
    assert forwarded[:4] == ["--root", "memory://box/in", "--root", str(tmp_path)]
    assert _options(*forwarded) == _options(*argv)
    assert semantic_argv(wrapper.parse_args(["--tools", ""])) == ["--tools", ""]


def test_the_cli_starts_a_server_with_the_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    served: list[MCPServer] = []
    monkeypatch.setattr(MCPServer, "serve_stdio", lambda self: served.append(self))
    assert _cli(["--root", INBOX, "--allow-write", "--no-bridge", "--name", "files"]) == 0
    server = served[0]
    assert server.toolkit.policy.allow_write is True
    assert _names(server) == list(SEMANTIC_TOOL_NAMES)
    assert _request(server, "initialize", {})["result"]["serverInfo"]["name"] == "files"
