"""The semantic file and storage tools, called without the JSON-RPC layer."""

from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file import Event, event_bus
from automation_file.exceptions import StorageTransientException
from automation_file.logging_config import file_automation_logger
from automation_file.server.mcp_policy import (
    DELETE_NOT_ALLOWED,
    LIMIT_EXCEEDED,
    NO_ROOT,
    OUTSIDE_ROOT,
    OVERWRITE_NOT_ALLOWED,
    READ_ONLY,
    SEMANTIC_TOOL_NAMES,
    TOOL_DISABLED,
    MCPPolicy,
    MCPToolException,
)
from automation_file.server.mcp_tools import (
    SEMANTIC_TOOLS,
    MCPToolCompleted,
    MCPToolFailed,
    SemanticToolkit,
)
from automation_file.storage import File, Storage
from tests.mcp_support import (
    BOX,
    INBOX,
    audited,
    clean_state,
    failed,
    link_directory,
    refused,
    remove_link,
    succeed,
    toolkit,
    writable,
)

A = f"{INBOX}/a.txt"
B = f"{INBOX}/b.txt"
OUTSIDE = f"{BOX}/in-b/a.txt"
STORAGE_TOOLS = (
    ("file_read", {"uri": A}),
    ("file_search", {"uri": INBOX}),
    ("file_checksum", {"uri": A}),
    ("file_verify", {"uri": A, "expected": "00"}),
    ("storage_list", {"uri": INBOX}),
)
CHANGING_TOOLS = (
    ("file_write", {"uri": B, "content": "x"}),
    ("file_copy", {"source": A, "target": B}),
    ("file_move", {"source": A, "target": B}),
    ("storage_copy", {"source": A, "target": B}),
)


@pytest.fixture(autouse=True)
def _state() -> Iterator[None]:
    with clean_state():
        File(A).write("alpha\nbeta needle\ngamma\n")
        yield


@pytest.fixture
def events() -> Iterator[list[Event]]:
    seen: list[Event] = []
    subscription = event_bus.subscribe(seen.append, types="mcp.*")
    yield seen
    event_bus.unsubscribe(subscription)


@pytest.fixture
def logged() -> Iterator[list[logging.LogRecord]]:
    """The records the library logs while the test runs (its logger does not propagate)."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler(level=logging.INFO)
    handler.emit = records.append  # type: ignore[method-assign]
    file_automation_logger.addHandler(handler)
    yield records
    file_automation_logger.removeHandler(handler)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _next_door(arguments: dict) -> dict:
    """Return ``arguments`` pointing at the tree next to the allowed one."""
    swaps = {A: OUTSIDE, INBOX: f"{BOX}/in-b"}
    return {key: swaps.get(value, value) for key, value in arguments.items()}


# ---------------------------------------------------------------------- the catalogue


def test_the_catalogue_holds_the_fourteen_tools_in_order() -> None:
    assert tuple(tool.name for tool in SEMANTIC_TOOLS) == SEMANTIC_TOOL_NAMES
    assert [tool["name"] for tool in toolkit().descriptors()] == list(SEMANTIC_TOOL_NAMES)


@pytest.mark.parametrize("tool", SEMANTIC_TOOLS, ids=lambda tool: tool.name)
def test_every_tool_has_a_closed_schema_with_described_arguments(tool) -> None:
    schema = tool.input_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert len(tool.description) > 40
    for name, spec in schema["properties"].items():
        assert spec["type"] in {"string", "integer", "boolean", "object"}, name
        assert len(spec["description"]) > 10, name
    assert set(schema.get("required", ())) <= set(schema["properties"])


def test_every_tool_that_changes_something_takes_dry_run() -> None:
    changing = {tool.name for tool in SEMANTIC_TOOLS if tool.changes}
    assert changing == {
        "file_write",
        "file_copy",
        "file_move",
        "storage_copy",
        "pipeline_create",
        "pipeline_run",
    }
    for tool in SEMANTIC_TOOLS:
        assert ("dry_run" in tool.input_schema["properties"]) is tool.changes, tool.name


def test_a_descriptor_is_a_copy() -> None:
    kit = toolkit()
    kit.descriptors()[0]["inputSchema"]["properties"].clear()
    assert "uri" in kit.descriptors()[0]["inputSchema"]["properties"]


def test_an_unknown_tool_name_is_not_an_outcome() -> None:
    with pytest.raises(MCPToolException, match="unknown semantic tool"):
        toolkit().call("file_delete", {})
    assert SemanticToolkit.owns("file_read") is True
    assert SemanticToolkit.owns("FA_storage_copy") is False


# ---------------------------------------------------------------------- arguments


def test_wrong_arguments_are_reported_together_without_their_values() -> None:
    outcome = toolkit().call(
        "file_read", {"offset": "secret-value", "max_bytes": 0, "surprise": 1, "encoding": True}
    )
    message = failed(outcome, "invalid_arguments")["message"]
    assert "'uri' is required" in message
    assert "'offset' must be of type integer" in message
    assert "'max_bytes' must be 1 or more" in message
    assert "'surprise' is not an argument of file_read" in message
    assert "'encoding' must be of type string" in message
    assert "secret-value" not in message


def test_a_boolean_is_not_an_integer_and_null_means_left_out() -> None:
    kit = toolkit()
    failed(kit.call("file_read", {"uri": A, "offset": True}), "invalid_arguments")
    failed(kit.call("storage_list", {"uri": INBOX, "recursive": 1}), "invalid_arguments")
    assert succeed(kit.call("file_read", {"uri": A, "max_bytes": None}))["bytes"] == 24


# ---------------------------------------------------------------------- refusals by location


@pytest.mark.parametrize(("name", "arguments"), STORAGE_TOOLS + CHANGING_TOOLS)
def test_without_a_root_every_storage_tool_says_how_to_configure_one(
    name: str, arguments: dict
) -> None:
    kit = SemanticToolkit(MCPPolicy(allow_write=True, allow_delete=True))
    error = refused(kit.call(name, arguments), NO_ROOT)
    assert "--root" in error["message"]


@pytest.mark.parametrize(("name", "arguments"), STORAGE_TOOLS)
def test_a_location_next_to_the_root_is_refused(name: str, arguments: dict) -> None:
    File(OUTSIDE).write("neighbour")
    refused(toolkit().call(name, _next_door(arguments)), OUTSIDE_ROOT)


@pytest.mark.parametrize("name", ["file_copy", "file_move", "storage_copy"])
def test_both_ends_of_a_transfer_must_be_inside_a_root(name: str) -> None:
    File(OUTSIDE).write("neighbour")
    kit = writable(allow_delete=True)
    refused(kit.call(name, {"source": OUTSIDE, "target": B}), OUTSIDE_ROOT)
    refused(kit.call(name, {"source": A, "target": f"{BOX}/in-b/copy.txt"}), OUTSIDE_ROOT)
    assert not File(B).exists()
    assert not File(f"{BOX}/in-b/copy.txt").exists()


def test_dot_dot_is_an_invalid_uri() -> None:
    error = failed(toolkit().call("file_read", {"uri": f"{INBOX}/../secret.txt"}), "invalid_uri")
    assert ".." in error["message"]


def test_a_link_out_of_a_local_root_cannot_be_read_or_written(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "escape"
    link_directory(link, outside)
    try:
        kit = SemanticToolkit(MCPPolicy(roots=[root], allow_write=True))
        refused(kit.call("file_read", {"uri": str(link / "secret.txt")}), OUTSIDE_ROOT)
        refused(
            kit.call("file_write", {"uri": str(link / "new.txt"), "content": "x"}), OUTSIDE_ROOT
        )
        assert not (outside / "new.txt").exists()
    finally:
        remove_link(link)


def test_a_local_root_works_end_to_end(tmp_path: Path) -> None:
    kit = SemanticToolkit(MCPPolicy(roots=[tmp_path], allow_write=True))
    target = tmp_path / "reports" / "a.txt"
    written = succeed(kit.call("file_write", {"uri": str(target), "content": "local"}))
    assert target.read_text(encoding="utf-8") == "local"
    assert written["uri"].startswith("local:///")
    assert succeed(kit.call("file_read", {"uri": written["uri"]}))["content"] == "local"
    listed = succeed(kit.call("storage_list", {"uri": str(tmp_path), "recursive": True}))
    assert [entry["path"] for entry in listed["entries"]] == ["reports", "reports/a.txt"]
    refused(kit.call("file_read", {"uri": str(tmp_path.parent / "elsewhere.txt")}), OUTSIDE_ROOT)


# ---------------------------------------------------------------------- read-only and disabled


@pytest.mark.parametrize(("name", "arguments"), CHANGING_TOOLS)
def test_a_read_only_server_refuses_every_change_even_as_a_dry_run(
    name: str, arguments: dict
) -> None:
    kit = toolkit()
    error = refused(kit.call(name, arguments), READ_ONLY)
    assert "--allow-write" in error["message"]
    refused(kit.call(name, {**arguments, "dry_run": True}), READ_ONLY)
    assert not File(B).exists()
    assert File(A).exists()


def test_a_disabled_tool_is_refused_and_not_listed() -> None:
    kit = toolkit(tools=["file_read"])
    assert [tool["name"] for tool in kit.descriptors()] == ["file_read"]
    refused(kit.call("storage_list", {"uri": INBOX}), TOOL_DISABLED)
    succeed(kit.call("file_read", {"uri": A}))


# ---------------------------------------------------------------------- file_read


def test_file_read_returns_text_with_its_size() -> None:
    body = succeed(toolkit().call("file_read", {"uri": A}))
    assert body["content"] == "alpha\nbeta needle\ngamma\n"
    assert (body["size"], body["bytes"], body["offset"]) == (24, 24, 0)
    assert body["truncated"] is False
    assert body["next_offset"] is None
    assert body["encoding"] == "utf-8"
    assert body["uri"] == A


def test_file_read_stops_at_the_policy_cap_and_says_where_to_continue() -> None:
    kit = toolkit(max_read_bytes=10)
    first = succeed(kit.call("file_read", {"uri": A, "max_bytes": 1000}))
    assert first["content"] == "alpha\nbeta"
    assert first["truncated"] is True
    assert first["next_offset"] == 10
    rest = succeed(kit.call("file_read", {"uri": A, "offset": 20}))
    assert rest["content"] == "mma\n"
    assert rest["truncated"] is False


def test_file_read_takes_a_smaller_window_than_the_cap() -> None:
    body = succeed(toolkit().call("file_read", {"uri": A, "offset": 6, "max_bytes": 4}))
    assert body["content"] == "beta"
    assert body["next_offset"] == 10


def test_file_read_does_not_cut_a_character_in_half() -> None:
    File(f"{INBOX}/zh.txt").write("檔案自動化")
    kit = toolkit(max_read_bytes=4)
    first = succeed(kit.call("file_read", {"uri": f"{INBOX}/zh.txt"}))
    assert first["content"] == "檔"
    assert first["bytes"] == 3
    assert first["next_offset"] == 3
    second = succeed(kit.call("file_read", {"uri": f"{INBOX}/zh.txt", "offset": 3}))
    assert second["content"] == "案"


def test_file_read_returns_binary_content_as_base64() -> None:
    payload = bytes(range(256))
    File(f"{INBOX}/blob.bin").write(payload)
    kit = toolkit()
    failed(kit.call("file_read", {"uri": f"{INBOX}/blob.bin"}), "invalid_arguments")
    body = succeed(kit.call("file_read", {"uri": f"{INBOX}/blob.bin", "encoding": "base64"}))
    assert base64.b64decode(body["content"]) == payload
    assert body["bytes"] == 256


def test_file_read_refuses_a_codec_that_is_not_a_text_encoding() -> None:
    error = failed(toolkit().call("file_read", {"uri": A, "encoding": "zlib"}), "invalid_arguments")
    assert "unknown text encoding" in error["message"]
    big5 = "繁體中文".encode("big5")
    File(f"{INBOX}/big5.txt").write(big5)
    body = succeed(toolkit().call("file_read", {"uri": f"{INBOX}/big5.txt", "encoding": "big5"}))
    assert body["content"] == "繁體中文"


def test_file_read_of_a_missing_file_or_a_directory_fails() -> None:
    kit = toolkit()
    failed(kit.call("file_read", {"uri": f"{INBOX}/absent.txt"}), "not_found")
    error = failed(kit.call("file_read", {"uri": INBOX}), "failed")
    assert "is a directory" in error["message"]


# ---------------------------------------------------------------------- file_write


def test_file_write_creates_a_file_and_reports_its_digest() -> None:
    body = succeed(writable().call("file_write", {"uri": B, "content": "héllo"}))
    assert File(B).read() == "héllo".encode()
    assert body["size"] == 6
    assert body["sha256"] == _sha256("héllo".encode())
    assert (body["overwrites"], body["written"], body["dry_run"]) == (False, True, False)


def test_file_write_takes_base64_and_other_encodings() -> None:
    kit = writable()
    payload = bytes(range(256))
    encoded = base64.b64encode(payload).decode("ascii")
    succeed(kit.call("file_write", {"uri": B, "content": encoded, "encoding": "base64"}))
    assert File(B).read() == payload
    failed(
        kit.call("file_write", {"uri": f"{INBOX}/c", "content": "***", "encoding": "base64"}),
        "invalid_arguments",
    )
    succeed(kit.call("file_write", {"uri": f"{INBOX}/c", "content": "中文", "encoding": "big5"}))
    assert File(f"{INBOX}/c").read() == "中文".encode("big5")
    error = failed(
        kit.call("file_write", {"uri": f"{INBOX}/d", "content": "中文", "encoding": "ascii"}),
        "invalid_arguments",
    )
    assert "中文" not in error["message"]


def test_file_write_as_a_dry_run_changes_nothing() -> None:
    body = succeed(writable().call("file_write", {"uri": B, "content": "abc", "dry_run": True}))
    assert (body["dry_run"], body["written"], body["size"]) == (True, False, 3)
    assert body["overwrites"] is False
    assert not File(B).exists()


def test_file_write_refuses_content_above_the_size_limit() -> None:
    kit = writable(max_write_bytes=4)
    error = refused(kit.call("file_write", {"uri": B, "content": "12345"}), LIMIT_EXCEEDED)
    assert "--max-write-bytes" in error["message"]
    assert not File(B).exists()
    succeed(kit.call("file_write", {"uri": B, "content": "1234"}))


def test_replacing_a_file_needs_the_argument_and_the_permission() -> None:
    kit = writable()
    error = failed(kit.call("file_write", {"uri": A, "content": "new"}), "already_exists")
    assert "does not allow replacing" in error["message"]
    refused(
        kit.call("file_write", {"uri": A, "content": "new", "overwrite": True}),
        OVERWRITE_NOT_ALLOWED,
    )
    assert File(A).read().startswith(b"alpha")
    allowed = writable(allow_overwrite=True)
    error = failed(allowed.call("file_write", {"uri": A, "content": "new"}), "already_exists")
    assert "pass overwrite=true" in error["message"]
    plan = succeed(
        allowed.call("file_write", {"uri": A, "content": "new", "overwrite": True, "dry_run": True})
    )
    assert (plan["overwrites"], plan["replaced_size"]) == (True, 24)
    assert File(A).read().startswith(b"alpha")
    succeed(allowed.call("file_write", {"uri": A, "content": "new", "overwrite": True}))
    assert File(A).read() == b"new"


def test_overwrite_true_is_harmless_when_nothing_is_there() -> None:
    body = succeed(writable().call("file_write", {"uri": B, "content": "x", "overwrite": True}))
    assert body["overwrites"] is False
    assert File(B).read() == b"x"


def test_file_write_onto_a_directory_fails() -> None:
    Storage(INBOX).mkdir("sub")
    kit = writable(allow_overwrite=True)
    outcome = kit.call("file_write", {"uri": f"{INBOX}/sub", "content": "x", "overwrite": True})
    assert "is a directory" in failed(outcome, "failed")["message"]


# ---------------------------------------------------------------------- file_copy and file_move


def test_file_copy_keeps_the_source() -> None:
    body = succeed(writable().call("file_copy", {"source": A, "target": B}))
    assert File(B).read() == File(A).read()
    assert (body["source"], body["target"], body["size"]) == (A, B, 24)
    assert (body["done"], body["deletes_source"], body["overwrites"]) == (True, False, False)


def test_file_copy_with_verify_reports_the_digest() -> None:
    body = succeed(writable().call("file_copy", {"source": A, "target": B, "verify": True}))
    assert body["verified"] is True
    assert body["sha256"] == _sha256(File(A).read())


def test_file_copy_as_a_dry_run_reports_the_plan_and_copies_nothing() -> None:
    File(B).write("old")
    kit = writable(allow_overwrite=True)
    arguments = {"source": A, "target": B, "overwrite": True, "dry_run": True}
    plan = succeed(kit.call("file_copy", arguments))
    assert (plan["source"], plan["target"]) == (A, B)
    assert (plan["size"], plan["overwrites"], plan["replaced_size"]) == (24, True, 3)
    assert (plan["dry_run"], plan["done"]) == (True, False)
    assert File(B).read() == b"old"


def test_file_copy_over_an_existing_file_needs_the_permission() -> None:
    File(B).write("old")
    kit = writable()
    failed(kit.call("file_copy", {"source": A, "target": B}), "already_exists")
    refused(
        kit.call("file_copy", {"source": A, "target": B, "overwrite": True}),
        (OVERWRITE_NOT_ALLOWED),
    )
    assert File(B).read() == b"old"
    allowed = writable(allow_overwrite=True)
    succeed(allowed.call("file_copy", {"source": A, "target": B, "overwrite": True}))
    assert File(B).read() == File(A).read()


def test_file_copy_onto_itself_or_from_nothing_fails() -> None:
    kit = writable(allow_overwrite=True)
    outcome = kit.call("file_copy", {"source": A, "target": A, "overwrite": True})
    assert "same file" in failed(outcome, "invalid_arguments")["message"]
    failed(kit.call("file_copy", {"source": f"{INBOX}/absent", "target": B}), "not_found")


def test_file_move_needs_the_delete_permission() -> None:
    error = refused(writable().call("file_move", {"source": A, "target": B}), DELETE_NOT_ALLOWED)
    assert "--allow-delete" in error["message"]
    assert File(A).exists()
    assert not File(B).exists()


def test_file_move_deletes_the_source() -> None:
    content = File(A).read()
    kit = writable(allow_delete=True)
    plan = succeed(kit.call("file_move", {"source": A, "target": B, "dry_run": True}))
    assert (plan["deletes_source"], plan["done"]) == (True, False)
    assert File(A).exists()
    assert not File(B).exists()
    body = succeed(kit.call("file_move", {"source": A, "target": B}))
    assert body["done"] is True
    assert File(B).read() == content
    assert not File(A).exists()


def test_file_move_with_verify_deletes_only_after_the_digests_match() -> None:
    content = File(A).read()
    body = succeed(
        writable(allow_delete=True).call("file_move", {"source": A, "target": B, "verify": True})
    )
    assert (body["verified"], body["sha256"]) == (True, _sha256(content))
    assert not File(A).exists()


def test_file_move_keeps_the_source_when_the_copy_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = File.copy_to

    def corrupting(self: File, target, *, overwrite: bool = True) -> File:
        copied = real(self, target, overwrite=overwrite)
        copied.write("damaged in transit")
        return copied

    monkeypatch.setattr(File, "copy_to", corrupting)
    outcome = writable(allow_delete=True).call(
        "file_move", {"source": A, "target": B, "verify": True}
    )
    error = failed(outcome, "checksum_mismatch")
    assert "source was left in place" in error["message"]
    assert File(A).read().startswith(b"alpha")


def test_a_transfer_between_a_local_root_and_a_memory_root(tmp_path: Path) -> None:
    kit = SemanticToolkit(MCPPolicy(roots=[tmp_path, INBOX], allow_write=True, allow_delete=True))
    local = tmp_path / "out" / "a.txt"
    succeed(kit.call("file_copy", {"source": A, "target": str(local), "verify": True}))
    assert local.read_bytes() == File(A).read()
    succeed(kit.call("file_move", {"source": str(local), "target": B}))
    assert not local.exists()
    assert File(B).read() == File(A).read()


# ---------------------------------------------------------------------- checksum and verify


def test_file_checksum_defaults_to_sha256() -> None:
    kit = toolkit()
    body = succeed(kit.call("file_checksum", {"uri": A}))
    assert (body["algorithm"], body["value"], body["size"]) == (
        "sha256",
        _sha256(File(A).read()),
        24,
    )
    md5 = succeed(kit.call("file_checksum", {"uri": A, "algorithm": "MD5"}))
    assert md5["value"] == hashlib.md5(File(A).read(), usedforsecurity=False).hexdigest()
    failed(kit.call("file_checksum", {"uri": A, "algorithm": "crc-nope"}), "failed")


def test_file_verify_answers_match_or_mismatch_without_failing() -> None:
    kit = toolkit()
    digest = _sha256(File(A).read())
    for expected in (digest, digest.upper(), f"sha256:{digest}"):
        body = succeed(kit.call("file_verify", {"uri": A, "expected": expected}))
        assert (body["match"], body["actual"], body["algorithm"]) == (True, digest, "sha256")
    wrong = succeed(kit.call("file_verify", {"uri": A, "expected": "00"}))
    assert (wrong["match"], wrong["expected"]) == (False, "00")
    sha1 = hashlib.sha1(File(A).read(), usedforsecurity=False).hexdigest()
    prefixed = succeed(kit.call("file_verify", {"uri": A, "expected": f"sha1:{sha1}"}))
    assert (prefixed["match"], prefixed["algorithm"]) == (True, "sha1")
    failed(kit.call("file_verify", {"uri": A, "expected": "sha256:"}), "invalid_arguments")
    failed(kit.call("file_verify", {"uri": f"{INBOX}/absent", "expected": digest}), "not_found")


# ---------------------------------------------------------------------- traceability


def test_every_outcome_carries_a_correlation_id_of_its_own() -> None:
    kit = toolkit()
    first = kit.call("file_read", {"uri": A})
    second = kit.call("file_read", {"uri": OUTSIDE})
    assert len(first.correlation_id) == 32
    assert first.payload["tool"] == "file_read"
    assert second.is_error is True
    assert len(second.correlation_id) == 32
    assert first.correlation_id != second.correlation_id


def test_a_call_is_reported_as_one_event_with_the_actor_and_the_correlation_id(
    events: list[Event],
) -> None:
    kit = writable()
    kit.set_client("Claude Desktop/1.2")
    outcome = kit.call("file_copy", {"source": A, "target": B})
    assert [type(event) for event in events] == [MCPToolCompleted]
    event = events[0]
    assert (event.type, event.source, event.actor) == (
        "mcp.tool.completed",
        "mcp",
        "mcp:Claude_Desktop_1.2",
    )
    assert event.correlation_id == outcome.correlation_id
    assert event.payload["action"] == "file_copy"
    assert event.payload["status"] == "ok"
    assert (event.payload["resource"], event.payload["source_uri"]) == (B, A)
    assert event.payload["dry_run"] is False


def test_a_refused_call_is_a_warning_event_and_a_log_line_without_values(
    events: list[Event], logged: list[logging.LogRecord]
) -> None:
    outcome = toolkit().call("file_write", {"uri": B, "content": "TOP-SECRET-CONTENT"})
    refused(outcome, READ_ONLY)
    event = events[0]
    assert isinstance(event, MCPToolFailed)
    assert (event.payload["status"], event.payload["code"]) == ("refused", READ_ONLY)
    assert event.severity.value == "warning"
    assert event.payload["resource"] == B
    assert "TOP-SECRET-CONTENT" not in str(event.to_dict())
    assert [record.levelno for record in logged] == [logging.WARNING]
    line = logged[0].getMessage()
    assert f"mcp_tools: file_write refused ({READ_ONLY})" in line
    assert outcome.correlation_id in line
    assert "TOP-SECRET-CONTENT" not in line
    assert B not in line


def test_a_failed_call_is_an_info_event(events: list[Event]) -> None:
    failed(toolkit().call("file_read", {"uri": f"{INBOX}/absent.txt"}), "not_found")
    event = events[0]
    assert isinstance(event, MCPToolFailed)
    assert (event.payload["status"], event.payload["code"]) == ("error", "not_found")
    assert event.severity.value == "info"
    assert "StorageNotFoundException" in event.payload["error"]


def test_a_digest_that_does_not_match_is_an_error_event(
    events: list[Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = File.copy_to

    def corrupting(self: File, target, *, overwrite: bool = True) -> File:
        copied = real(self, target, overwrite=overwrite)
        copied.write("damaged in transit")
        return copied

    monkeypatch.setattr(File, "copy_to", corrupting)
    outcome = writable().call("file_copy", {"source": A, "target": B, "verify": True})
    failed(outcome, "checksum_mismatch")
    assert (events[0].severity.value, events[0].payload["code"]) == ("error", "checksum_mismatch")


def test_a_backend_failure_and_a_partly_failed_copy_are_warning_events(
    events: list[Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(self: File, target, *, overwrite: bool = True) -> File:
        raise StorageTransientException("the backend timed out")

    File(f"{INBOX}/tree/one.txt").write("1")
    monkeypatch.setattr(File, "copy_to", unavailable)
    kit = writable()
    failed(kit.call("file_copy", {"source": A, "target": B}), "failed")
    partly = kit.call("storage_copy", {"source": f"{INBOX}/tree", "target": f"{INBOX}/copy"})
    failed(partly, "failed")
    assert partly.payload["failed"] == 1
    assert [event.severity.value for event in events] == ["warning", "warning"]


def test_an_unexpected_exception_is_an_internal_error_whose_text_stays_out_of_the_event(
    events: list[Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: File) -> None:
        raise RuntimeError("holds file content")

    monkeypatch.setattr(File, "stat", broken)
    outcome = toolkit().call("file_read", {"uri": A})
    error = failed(outcome, "internal_error")
    assert error["exception"] == "RuntimeError"
    assert events[0].severity.value == "error"
    assert events[0].payload["error"] == "RuntimeError"


def test_the_audit_trail_ties_the_storage_operation_to_the_call() -> None:
    store = audited()
    outcome = writable().call("file_copy", {"source": A, "target": B})
    records = store.search(correlation_id=outcome.correlation_id)
    assert [(record.source, record.action) for record in records] == [
        ("mcp", "mcp.tool.completed"),
        ("storage", "copy"),
    ]
    assert {record.actor for record in records} == {"mcp"}
    assert records[1].resource == B
    assert records[0].metadata["action"] == "file_copy"
    refusal = toolkit().call("file_read", {"uri": OUTSIDE})
    refused_records = store.search(correlation_id=refusal.correlation_id)
    assert [(record.action, record.status) for record in refused_records] == [
        ("mcp.tool.failed", "refused")
    ]


def test_the_client_name_is_cleaned_before_it_labels_the_actor() -> None:
    kit = toolkit()
    assert kit.actor == "mcp"
    kit.set_client("  evil\nname with spaces " + "x" * 200)
    assert kit.actor.startswith("mcp:evil_name_with_spaces_x")
    assert "\n" not in kit.actor
    assert len(kit.actor) <= len("mcp:") + 64
    kit.set_client(None)
    assert kit.actor == "mcp"
    assert toolkit(actor="mcp-finance").actor == "mcp-finance"


def test_to_mcp_wraps_the_payload_as_one_json_text_block() -> None:
    outcome = toolkit().call("file_read", {"uri": f"{INBOX}/absent.txt"})
    wrapped = outcome.to_mcp()
    assert wrapped["isError"] is True
    assert [block["type"] for block in wrapped["content"]] == ["text"]
    assert outcome.correlation_id in wrapped["content"][0]["text"]
