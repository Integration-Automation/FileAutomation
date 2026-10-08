"""The semantic pipeline and reporting tools, and the guarded actions a pipeline runs with."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from automation_file import PipelineStarted, correlation_scope, emit
from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import (
    MCPServerException,
    StorageAlreadyExistsException,
    StorageChecksumException,
    StorageException,
)
from automation_file.integrity import actions as integrity_actions
from automation_file.pipeline import default_run_store
from automation_file.server.mcp_pipeline_actions import (
    GUARDED_ACTIONS,
    GuardedStorageActions,
    default_pipeline_actions,
)
from automation_file.server.mcp_pipeline_tools import (
    action_refusals,
    allowed_actions,
    definitions,
    pipeline_registry,
)
from automation_file.server.mcp_policy import (
    ACTION_NOT_ALLOWED,
    DELETE_NOT_ALLOWED,
    LIMIT_EXCEEDED,
    OUTSIDE_ROOT,
    OVERWRITE_NOT_ALLOWED,
    READ_ONLY,
    MCPLocationException,
    MCPPermissionException,
    MCPPolicy,
)
from automation_file.server.mcp_tools import SemanticToolkit
from automation_file.storage import File, Storage
from tests.mcp_support import (
    BOX,
    INBOX,
    audited,
    clean_state,
    failed,
    refused,
    succeed,
    toolkit,
    writable,
)

SOURCE = f"{INBOX}/in.csv"
CALLS: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _state() -> Iterator[None]:
    with clean_state():
        File(SOURCE).write("id,amount\n1,10\n")
        CALLS.clear()
        yield


def _definition(**extra: Any) -> dict[str, Any]:
    target = f"{INBOX}/out/${{params.date}}.csv"
    return {
        "schema_version": 1,
        "params": {"date": "2026-10-07"},
        "tasks": {
            "copy": {"action": ["FA_storage_copy", {"source": SOURCE, "target": target}]},
            "check": {
                "action": ["FA_storage_checksum", {"uri": target}],
                "depends_on": ["copy"],
            },
        },
        **extra,
    }


def _one_task(action: list[Any]) -> dict[str, Any]:
    return {"schema_version": 1, "tasks": {"only": {"action": action}}}


def _create(kit: SemanticToolkit, name: str = "daily", **extra: Any):
    return kit.call("pipeline_create", {"name": name, "definition": _definition(), **extra})


def _notify(**arguments: Any) -> str:
    CALLS.append(arguments)
    return "sent"


def _with_notify(**policy: Any) -> SemanticToolkit:
    """A writable toolkit whose registry has one action of its own, ``FA_test_notify``."""
    registry = ActionRegistry({"FA_test_notify": _notify, "FA_test_other": _notify})
    policy.setdefault("roots", (INBOX,))
    return SemanticToolkit(MCPPolicy(allow_write=True, **policy), registry)


# ---------------------------------------------------------------------- pipeline_create


def test_pipeline_create_validates_and_stores_the_definition() -> None:
    kit = writable()
    body = succeed(_create(kit))
    assert body["name"] == "daily"
    assert body["tasks"] == ["copy", "check"]
    assert body["actions"] == ["FA_storage_checksum", "FA_storage_copy"]
    assert (body["stored"], body["overwrites"], body["dry_run"]) == (True, False, False)
    assert (body["persistent"], body["location"]) == (False, "memory (kept until the server stops)")
    stored = definitions(kit.session).load("daily", 10_000)
    assert stored["name"] == "daily"
    assert stored["tasks"].keys() == {"copy", "check"}
    assert not File(f"{INBOX}/out/2026-10-07.csv").exists()


def test_pipeline_create_as_a_dry_run_stores_nothing() -> None:
    kit = writable()
    body = succeed(_create(kit, dry_run=True))
    assert (body["stored"], body["dry_run"]) == (False, True)
    assert definitions(kit.session).names() == []


def test_pipeline_create_keeps_definitions_in_the_pipeline_directory(tmp_path: Path) -> None:
    directory = tmp_path / "pipelines"
    kit = writable(pipeline_dir=directory)
    body = succeed(_create(kit))
    assert body["persistent"] is True
    assert body["location"].startswith("local:///")
    document = json.loads((directory / "daily.json").read_text(encoding="utf-8"))
    assert document["name"] == "daily"
    again = writable(pipeline_dir=directory)
    assert definitions(again.session).names() == ["daily"]
    assert succeed(again.call("pipeline_run", {"name": "daily"}))["status"] == "succeeded"


def test_the_pipeline_directory_may_be_any_storage_uri() -> None:
    kit = writable(pipeline_dir=f"{BOX}/definitions")
    succeed(_create(kit))
    assert File(f"{BOX}/definitions/daily.json").exists()
    assert succeed(kit.call("pipeline_run", {"name": "daily"}))["status"] == "succeeded"


def test_pipeline_create_reports_every_problem_of_a_definition() -> None:
    broken = {"schema_version": 1, "max_workers": 0, "tasks": {"a": {"depends_on": ["x"]}}}
    outcome = writable().call("pipeline_create", {"name": "broken", "definition": broken})
    error = failed(outcome, "invalid_definition")
    assert "max_workers: expected an integer >= 1, got 0" in error["problems"]
    assert "tasks.a.action: required" in error["problems"]
    assert any("unknown task 'x'" in problem for problem in error["problems"])


def test_pipeline_create_needs_a_schema_version() -> None:
    outcome = writable().call("pipeline_create", {"name": "bare", "definition": {"tasks": {}}})
    assert failed(outcome, "invalid_definition")["problems"] == [
        "schema_version: required (supported: 1)"
    ]


@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".hidden", "x" * 101, "with space"])
def test_a_pipeline_name_is_a_plain_file_name(name: str) -> None:
    outcome = writable().call("pipeline_create", {"name": name, "definition": _definition()})
    assert failed(outcome, "invalid_arguments")
    assert definitions(writable().session).names() == []


def test_the_definition_must_name_itself_as_it_is_stored() -> None:
    outcome = writable().call(
        "pipeline_create", {"name": "daily", "definition": _definition(name="nightly")}
    )
    assert "must be 'daily'" in failed(outcome, "invalid_arguments")["message"]


def test_a_definition_created_through_mcp_cannot_carry_a_schedule() -> None:
    scheduled = _definition(schedule={"cron": "0 2 * * *"})
    outcome = writable().call("pipeline_create", {"name": "daily", "definition": scheduled})
    assert "schedule" in refused(outcome, ACTION_NOT_ALLOWED)["message"]


def test_replacing_a_definition_needs_the_argument_and_the_permission() -> None:
    kit = writable()
    succeed(_create(kit))
    assert "already stored" in failed(_create(kit), "already_exists")["message"]
    refused(_create(kit, overwrite=True), OVERWRITE_NOT_ALLOWED)
    allowed = writable(allow_overwrite=True)
    succeed(_create(allowed))
    plan = succeed(_create(allowed, overwrite=True, dry_run=True))
    assert (plan["overwrites"], plan["stored"]) == (True, False)
    assert succeed(_create(allowed, overwrite=True))["overwrites"] is True


def test_a_definition_larger_than_the_write_limit_is_refused() -> None:
    kit = writable(max_write_bytes=64)
    refused(_create(kit), LIMIT_EXCEEDED)


@pytest.mark.parametrize("tool", ["pipeline_create", "pipeline_run"])
def test_pipelines_are_refused_on_a_read_only_server(tool: str) -> None:
    arguments = {"name": "daily", "definition": _definition(), "dry_run": True}
    if tool == "pipeline_run":
        del arguments["definition"]
    refused(toolkit().call(tool, arguments), READ_ONLY)


# ---------------------------------------------------------------------- which actions


def test_the_default_actions_follow_the_permissions() -> None:
    read_only = default_pipeline_actions(MCPPolicy())
    assert "FA_storage_checksum" in read_only
    assert "FA_storage_copy" not in read_only
    writer = default_pipeline_actions(MCPPolicy(allow_write=True))
    assert {"FA_storage_copy", "FA_storage_write_text", "FA_storage_copy_tree"} <= writer
    assert not {"FA_storage_sync", "FA_storage_move", "FA_storage_delete"} & writer
    everything = default_pipeline_actions(
        MCPPolicy(allow_write=True, allow_overwrite=True, allow_delete=True)
    )
    assert everything == GUARDED_ACTIONS
    assert all(name.startswith("FA_storage_") for name in everything)
    assert not {"FA_storage_upload", "FA_storage_download"} & everything


@pytest.mark.parametrize(
    "action",
    [
        ["FA_run_shell", {"argv": ["echo", "hi"]}],
        ["FA_storage_upload", {"local_path": "/etc/passwd", "uri": f"{INBOX}/p"}],
        ["FA_storage_delete", {"uri": SOURCE}],
        ["FA_execute_action", {"action_list": [["FA_storage_exists", {"uri": SOURCE}]]}],
        ["FA_no_such_action"],
    ],
)
def test_an_action_outside_the_allowed_set_is_refused_at_create(action: list[Any]) -> None:
    outcome = writable().call("pipeline_create", {"name": "bad", "definition": _one_task(action)})
    error = refused(outcome, ACTION_NOT_ALLOWED)
    assert f"tasks.only.action[0]: {action[0]} is not allowed" in error["message"]
    assert "FA_storage_copy" in error["message"]


def test_an_action_hidden_in_the_arguments_of_another_one_is_refused() -> None:
    hidden = ["FA_storage_exists", {"uri": [["FA_run_shell", {"argv": ["id"]}]]}]
    outcome = writable().call("pipeline_create", {"name": "bad", "definition": _one_task(hidden)})
    assert (
        "its arguments name the action FA_run_shell"
        in (refused(outcome, ACTION_NOT_ALLOWED)["message"])
    )
    by_default = _definition(params={"date": "x", "extra": ["FA_run_shell"]})
    outcome = writable().call("pipeline_create", {"name": "bad", "definition": by_default})
    assert (
        "a parameter names the action FA_run_shell"
        in (refused(outcome, ACTION_NOT_ALLOWED)["message"])
    )


def test_the_policy_may_list_the_actions_itself() -> None:
    kit = _with_notify(pipeline_actions=["FA_storage_exists", "FA_test_notify"])
    assert allowed_actions(kit.session) == {"FA_storage_exists", "FA_test_notify"}
    definition = _one_task(["FA_test_notify", {"subject": "done"}])
    succeed(kit.call("pipeline_create", {"name": "tell", "definition": definition}))
    assert succeed(kit.call("pipeline_run", {"name": "tell"}))["status"] == "succeeded"
    assert CALLS == [{"subject": "done"}]
    copying = _one_task(["FA_storage_copy", {"source": SOURCE, "target": f"{INBOX}/x"}])
    refused(
        kit.call("pipeline_create", {"name": "copy", "definition": copying}), (ACTION_NOT_ALLOWED)
    )
    other = _one_task(["FA_test_other", {}])
    refused(kit.call("pipeline_create", {"name": "o", "definition": other}), ACTION_NOT_ALLOWED)


def test_a_listed_action_the_server_does_not_have_is_refused_at_start() -> None:
    with pytest.raises(MCPServerException, match="FA_missing"):
        _with_notify(pipeline_actions=["FA_test_notify", "FA_missing"])
    with pytest.raises(MCPServerException, match="does not expose"):
        SemanticToolkit(MCPPolicy(pipeline_actions=["FA_run_shell"]), ActionRegistry())


def test_a_storage_action_stays_guarded_when_the_policy_lists_it() -> None:
    kit = _with_notify(pipeline_actions=["FA_storage_delete", "FA_storage_copy"])
    registry = pipeline_registry(kit.session)
    assert set(registry.event_dict) == {"FA_storage_delete", "FA_storage_copy"}
    with pytest.raises(MCPPermissionException) as caught:
        registry.resolve("FA_storage_delete")(uri=SOURCE)
    assert caught.value.code == DELETE_NOT_ALLOWED
    assert File(SOURCE).exists()


def test_a_nested_storage_action_is_refused_even_when_it_is_listed() -> None:
    # Nested, it would be run by the shared executor: unguarded.
    kit = _with_notify(pipeline_actions=["FA_test_notify", "FA_storage_copy"])
    nested = _one_task(["FA_test_notify", {"then": [["FA_storage_copy", {"source": "a"}]]}])
    refusals = action_refusals(kit.session, nested, None)
    assert refusals == ["tasks.only.action: its arguments name the action FA_storage_copy"]
    plain = _one_task(["FA_test_notify", {"then": "FA_test_notify"}])
    assert action_refusals(kit.session, plain, {"also": ["FA_test_notify"]}) == []
    assert action_refusals(kit.session, plain, {"also": ["FA_test_other"]}) == [
        "params: a parameter names the action FA_test_other"
    ]


# ---------------------------------------------------------------------- pipeline_run


def test_pipeline_run_as_a_dry_run_returns_the_plan_and_runs_nothing() -> None:
    kit = writable()
    succeed(_create(kit))
    body = succeed(kit.call("pipeline_run", {"name": "daily", "dry_run": True}))
    assert (body["dry_run"], body["status"], body["background"]) == (True, "succeeded", False)
    tasks = body["run"]["tasks"]
    assert list(tasks) == ["copy", "check"]
    assert [state["status"] for state in tasks.values()] == ["planned", "planned"]
    assert [state["level"] for state in tasks.values()] == [0, 1]
    assert not File(f"{INBOX}/out/2026-10-07.csv").exists()
    assert default_run_store().get_run(body["run_id"]) is None


def test_pipeline_run_runs_the_stored_definition_with_its_parameters() -> None:
    kit = writable()
    succeed(_create(kit))
    body = succeed(kit.call("pipeline_run", {"name": "daily", "params": {"date": "2026-10-08"}}))
    assert (body["status"], body["ok"], body["name"]) == ("succeeded", True, "daily")
    assert File(f"{INBOX}/out/2026-10-08.csv").read() == File(SOURCE).read()
    assert body["run"]["params"] == {"date": "2026-10-08"}
    assert body["run"]["tasks"]["check"]["result"]["algorithm"] == "sha256"
    assert default_run_store().get_run(body["run_id"]) is not None


def test_a_failed_run_is_an_error_outcome_that_still_carries_the_run() -> None:
    kit = writable()
    definition = _one_task(["FA_storage_copy", {"source": f"{INBOX}/absent", "target": SOURCE}])
    succeed(kit.call("pipeline_create", {"name": "fails", "definition": definition}))
    outcome = kit.call("pipeline_run", {"name": "fails"})
    failed(outcome, "failed")
    assert outcome.payload["status"] == "failed"
    assert outcome.payload["ok"] is False
    assert "StorageNotFoundException" in outcome.payload["run"]["tasks"]["only"]["error"]


def test_a_dry_run_reports_a_missing_parameter_as_an_error_outcome() -> None:
    kit = writable()
    definition = _one_task(["FA_storage_exists", {"uri": f"{INBOX}/${{params.missing}}"}])
    succeed(kit.call("pipeline_create", {"name": "needs", "definition": definition}))
    outcome = kit.call("pipeline_run", {"name": "needs", "dry_run": True})
    failed(outcome, "failed")
    assert "unknown parameter 'missing'" in outcome.payload["run"]["tasks"]["only"]["error"]


def test_pipeline_run_of_an_unknown_name_lists_what_is_stored() -> None:
    kit = writable()
    succeed(_create(kit))
    error = failed(kit.call("pipeline_run", {"name": "nightly"}), "not_found")
    assert "stored: daily" in error["message"]


def test_a_task_cannot_leave_the_allowed_locations_at_run_time() -> None:
    File(f"{BOX}/private/secret.csv").write("secret")
    kit = writable()
    definition = _one_task(
        ["FA_storage_copy", {"source": "${params.source}", "target": f"{INBOX}/stolen.csv"}]
    )
    succeed(kit.call("pipeline_create", {"name": "sneaky", "definition": definition}))
    outcome = kit.call(
        "pipeline_run", {"name": "sneaky", "params": {"source": f"{BOX}/private/secret.csv"}}
    )
    assert outcome.is_error is True
    assert "MCPLocationException" in outcome.payload["run"]["tasks"]["only"]["error"]
    assert not File(f"{INBOX}/stolen.csv").exists()


def test_the_allowed_actions_are_checked_again_when_the_definition_is_run(tmp_path: Path) -> None:
    directory = tmp_path / "pipelines"
    directory.mkdir()
    planted = {"name": "planted", **_one_task(["FA_run_shell", {"argv": ["echo", "hi"]}])}
    (directory / "planted.json").write_text(json.dumps(planted), encoding="utf-8")
    kit = writable(pipeline_dir=directory)
    refused(kit.call("pipeline_run", {"name": "planted"}), ACTION_NOT_ALLOWED)
    refused(kit.call("pipeline_run", {"name": "planted", "dry_run": True}), ACTION_NOT_ALLOWED)


def test_run_parameters_cannot_smuggle_an_action() -> None:
    kit = writable()
    succeed(_create(kit))
    outcome = kit.call("pipeline_run", {"name": "daily", "params": {"date": ["FA_run_shell"]}})
    assert (
        "a parameter names the action FA_run_shell"
        in (refused(outcome, ACTION_NOT_ALLOWED)["message"])
    )


def test_a_stored_file_that_is_not_a_valid_definition_is_reported(tmp_path: Path) -> None:
    directory = tmp_path / "pipelines"
    directory.mkdir()
    (directory / "garbage.json").write_text("{not json", encoding="utf-8")
    (directory / "twice.json").write_text('{"name": "a", "name": "b"}', encoding="utf-8")
    (directory / "other.json").write_text(
        json.dumps({"name": "different", **_one_task(["FA_storage_schemes"])}), encoding="utf-8"
    )
    (directory / "huge.json").write_text(json.dumps(_definition()) + " " * 4096, encoding="utf-8")
    kit = writable(pipeline_dir=directory, max_write_bytes=1024)
    assert (
        "not valid JSON"
        in failed(kit.call("pipeline_run", {"name": "garbage"}), ("invalid_arguments"))["message"]
    )
    failed(kit.call("pipeline_run", {"name": "twice"}), "invalid_arguments")
    assert (
        "names itself 'different'"
        in failed(kit.call("pipeline_run", {"name": "other"}), ("invalid_arguments"))["message"]
    )
    refused(kit.call("pipeline_run", {"name": "huge"}), LIMIT_EXCEEDED)


def test_a_background_run_returns_at_once_and_is_found_by_pipeline_status() -> None:
    kit = writable()
    succeed(_create(kit))
    started = succeed(kit.call("pipeline_run", {"name": "daily", "background": True}))
    assert started["background"] is True
    assert started["status"] in {"running", "succeeded"}
    deadline = time.monotonic() + 10
    status = "running"
    while status == "running" and time.monotonic() < deadline:
        report = succeed(kit.call("pipeline_status", {"run_id": started["run_id"]}))
        status = report["runs"][0]["status"]
        time.sleep(0.02)
    assert status == "succeeded"


def test_a_large_task_result_is_left_out_of_what_is_returned() -> None:
    File(f"{INBOX}/big.txt").write("x" * 300)
    kit = writable(max_read_bytes=400)
    definition = {
        "schema_version": 1,
        "tasks": {
            "read": {"action": ["FA_storage_read_text", {"uri": f"{INBOX}/big.txt"}]},
            "list": {"action": ["FA_storage_list", {"uri": INBOX, "recursive": True}]},
        },
    }
    succeed(kit.call("pipeline_create", {"name": "big", "definition": definition}))
    body = succeed(kit.call("pipeline_run", {"name": "big"}))
    tasks = body["run"]["tasks"]
    assert tasks["read"]["result"] == "x" * 300
    assert tasks["list"]["result"] is None
    assert "more than the 400" in tasks["list"]["result_omitted"]


def _export_definition() -> dict[str, Any]:
    """The pipeline of the manual: digest, copy, verify against the digest, remove the source."""
    source, target = f"{INBOX}/${{params.date}}.csv", f"{INBOX}/sent/${{params.date}}.csv"
    return {
        "schema_version": 1,
        "tasks": {
            "digest": {"action": ["FA_storage_checksum", {"uri": source}]},
            "copy": {
                "action": ["FA_storage_copy", {"source": source, "target": target}],
                "depends_on": ["digest"],
            },
            "verify": {
                "action": [
                    "FA_storage_verify",
                    {"uri": target, "expected": "${tasks.digest.result}", "strict": True},
                ],
                "depends_on": ["copy"],
            },
            "remove": {"action": ["FA_storage_delete", {"uri": source}], "depends_on": ["verify"]},
        },
    }


def test_the_move_and_verify_pipeline_of_the_manual_runs() -> None:
    File(f"{INBOX}/2026-10-07.csv").write("id,amount\n7,70\n")
    kit = writable(allow_delete=True)
    succeed(kit.call("pipeline_create", {"name": "export", "definition": _export_definition()}))
    body = succeed(kit.call("pipeline_run", {"name": "export", "params": {"date": "2026-10-07"}}))
    assert [state["status"] for state in body["run"]["tasks"].values()] == ["succeeded"] * 4
    assert body["run"]["tasks"]["verify"]["result"] is True
    assert File(f"{INBOX}/sent/2026-10-07.csv").read() == b"id,amount\n7,70\n"
    assert not File(f"{INBOX}/2026-10-07.csv").exists()


def test_the_source_stays_when_the_copy_does_not_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    File(f"{INBOX}/2026-10-07.csv").write("id,amount\n7,70\n")
    real = File.copy_to

    def corrupting(self: File, target, *, overwrite: bool = True) -> File:
        copied = real(self, target, overwrite=overwrite)
        copied.write("damaged in transit")
        return copied

    monkeypatch.setattr(File, "copy_to", corrupting)
    kit = writable(allow_delete=True)
    succeed(kit.call("pipeline_create", {"name": "export", "definition": _export_definition()}))
    outcome = kit.call("pipeline_run", {"name": "export", "params": {"date": "2026-10-07"}})
    failed(outcome, "failed")
    tasks = outcome.payload["run"]["tasks"]
    assert "StorageChecksumException" in tasks["verify"]["error"]
    assert (tasks["remove"]["status"], tasks["remove"]["reason"]) == ("skipped", "upstream_failed")
    assert File(f"{INBOX}/2026-10-07.csv").exists()


# ---------------------------------------------------------------------- pipeline_status


def test_pipeline_status_reports_one_run_or_the_latest() -> None:
    kit = writable()
    succeed(_create(kit))
    first = succeed(kit.call("pipeline_run", {"name": "daily", "params": {"date": "a"}}))
    second = succeed(kit.call("pipeline_run", {"name": "daily", "params": {"date": "b"}}))
    one = succeed(toolkit().call("pipeline_status", {"run_id": first["run_id"]}))
    assert (one["count"], one["runs"][0]["run_id"]) == (1, first["run_id"])
    assert one["runs"][0]["tasks"]["copy"]["status"] == "succeeded"
    latest = succeed(kit.call("pipeline_status", {"name": "daily"}))
    assert [run["run_id"] for run in latest["runs"]] == [second["run_id"], first["run_id"]]
    newest = succeed(kit.call("pipeline_status", {"name": "daily", "limit": 1}))
    assert [run["run_id"] for run in newest["runs"]] == [second["run_id"]]
    assert succeed(kit.call("pipeline_status", {"name": "other"}))["runs"] == []
    assert succeed(kit.call("pipeline_status", {}))["count"] == 2


def test_pipeline_status_of_an_unknown_run_fails() -> None:
    error = failed(toolkit().call("pipeline_status", {"run_id": "no-such-run"}), "not_found")
    assert "no run 'no-such-run' is recorded" in error["message"]


def test_a_run_is_tied_to_its_call_in_the_audit_trail() -> None:
    store = audited()
    kit = writable()
    succeed(_create(kit))
    outcome = kit.call("pipeline_run", {"name": "daily"})
    run_id = succeed(outcome)["run_id"]
    call = store.search(correlation_id=outcome.correlation_id)
    # The call itself read the stored definition; what the run did is under the run ID.
    assert [record.action for record in call] == ["mcp.tool.completed", "read"]
    assert (call[0].pipeline, call[0].metadata["run_id"]) == ("daily", run_id)
    run = store.search(correlation_id=run_id)
    assert {record.actor for record in run} == {"mcp"}
    assert "pipeline.completed" in [record.action for record in run]
    assert ("storage", "copy") in [(record.source, record.action) for record in run]


# ---------------------------------------------------------------------- the guarded actions


def _actions(**policy: Any) -> GuardedStorageActions:
    return GuardedStorageActions(writable(**policy).session)


def test_the_guarded_actions_answer_like_the_storage_actions() -> None:
    actions = _actions()
    assert set(actions.commands()) == GUARDED_ACTIONS
    assert actions.exists(SOURCE) is True
    assert actions.stat(SOURCE)["size"] == 15
    assert [entry["path"] for entry in actions.list_dir(INBOX)] == ["in.csv"]
    assert actions.checksum(SOURCE)["algorithm"] == "sha256"
    digest = actions.checksum(SOURCE)["value"]
    assert actions.verify(SOURCE, digest) is True
    assert actions.verify(SOURCE, "00") is False
    assert actions.verify(SOURCE, actions.checksum(SOURCE)) is True
    assert actions.verify(SOURCE, {"algorithm": "sha256", "value": "00"}) is False
    with pytest.raises(StorageChecksumException):
        actions.verify(SOURCE, "00", strict=True)
    with pytest.raises(StorageException, match="expected must be"):
        actions.verify(SOURCE, ["not", "a", "digest"])  # type: ignore[arg-type]
    assert actions.read_text(SOURCE) == "id,amount\n1,10\n"
    assert "memory" in actions.schemes()
    assert actions.mkdir(f"{INBOX}/made") is True
    assert actions.write_text(f"{INBOX}/made/a.txt", "abc")["size"] == 3
    assert actions.copy(SOURCE, f"{INBOX}/made/b.csv")["uri"] == f"{INBOX}/made/b.csv"
    assert actions.copy_tree(f"{INBOX}/made", f"{INBOX}/again")["copied"] == ["a.txt", "b.csv"]


def test_the_guarded_actions_refuse_what_the_policy_does_not_allow() -> None:
    read_only = GuardedStorageActions(toolkit().session)
    for call in (
        lambda: read_only.mkdir(f"{INBOX}/made"),
        lambda: read_only.write_text(f"{INBOX}/a.txt", "x"),
        lambda: read_only.copy(SOURCE, f"{INBOX}/b.csv"),
        lambda: read_only.copy_tree(INBOX, f"{INBOX}-b"),
    ):
        with pytest.raises(MCPPermissionException) as caught:
            call()
        assert caught.value.code == READ_ONLY
    writer = _actions()
    for call in (
        lambda: writer.move(SOURCE, f"{INBOX}/moved.csv"),
        lambda: writer.delete(SOURCE),
    ):
        with pytest.raises(MCPPermissionException) as caught:
            call()
        assert caught.value.code == DELETE_NOT_ALLOWED
    with pytest.raises(MCPPermissionException) as caught:
        writer.sync(INBOX, f"{INBOX}/mirror")
    assert caught.value.code == OVERWRITE_NOT_ALLOWED
    for call in (
        lambda: writer.read_text(f"{BOX}/private/a.txt"),
        lambda: writer.copy(SOURCE, f"{BOX}/private/a.txt"),
        lambda: writer.list_dir(BOX),
    ):
        with pytest.raises(MCPLocationException) as caught:
            call()
        assert caught.value.code == OUTSIDE_ROOT


def test_overwrite_defaults_to_what_the_policy_permits() -> None:
    target = f"{INBOX}/target.csv"
    File(target).write("old")
    writer = _actions()
    with pytest.raises(StorageAlreadyExistsException):
        writer.copy(SOURCE, target)
    with pytest.raises(MCPPermissionException) as caught:
        writer.copy(SOURCE, target, overwrite=True)
    assert caught.value.code == OVERWRITE_NOT_ALLOWED
    with pytest.raises(MCPPermissionException):
        writer.copy_tree(INBOX, f"{INBOX}/tree", overwrite=True)
    assert writer.copy(SOURCE, f"{INBOX}/fresh.csv", overwrite=True)["size"] == 15
    assert File(target).read() == b"old"
    replacing = _actions(allow_overwrite=True)
    replacing.copy(SOURCE, target)
    assert File(target).read() == File(SOURCE).read()
    with pytest.raises(StorageAlreadyExistsException):
        replacing.write_text(target, "x", overwrite=False)


def test_the_guarded_actions_keep_the_size_limits() -> None:
    actions = _actions(max_read_bytes=8, max_write_bytes=8)
    with pytest.raises(MCPPermissionException) as caught:
        actions.read_text(SOURCE)
    assert caught.value.code == LIMIT_EXCEEDED
    with pytest.raises(MCPPermissionException) as caught:
        actions.write_text(f"{INBOX}/a.txt", "123456789")
    assert caught.value.code == LIMIT_EXCEEDED


def test_delete_move_and_sync_work_with_their_permissions() -> None:
    actions = _actions(allow_overwrite=True, allow_delete=True)
    assert actions.move(SOURCE, f"{INBOX}/moved.csv")["uri"] == f"{INBOX}/moved.csv"
    assert not File(SOURCE).exists()
    mirrored = actions.sync(INBOX, f"{BOX}/in/mirror", delete=True, dry_run=True)
    assert mirrored["dry_run"] is True
    assert actions.delete(f"{INBOX}/moved.csv") is True
    with pytest.raises(MCPLocationException, match="allowed location itself"):
        actions.delete(INBOX, recursive=True)
    assert Storage(INBOX).exists()
    without_delete = _actions(allow_overwrite=True)
    with pytest.raises(MCPPermissionException) as caught:
        without_delete.sync(INBOX, f"{INBOX}/mirror", delete=True)
    assert caught.value.code == DELETE_NOT_ALLOWED


# ---------------------------------------------------------------------- reporting tools


def test_integrity_status_reports_the_named_monitors() -> None:
    kit = toolkit()
    empty = succeed(kit.call("integrity_status", {}))
    assert (empty["monitors"], empty["count"]) == ([], 0)
    baseline = f"{BOX}/baselines/in.json"
    integrity_actions.integrity_baseline(INBOX, baseline)
    integrity_actions.integrity_watch_start("inbox", INBOX, baseline, interval=3600)
    body = succeed(kit.call("integrity_status", {}))
    assert body["count"] == 1
    monitor = body["monitors"][0]
    assert (monitor["name"], monitor["target"], monitor["running"]) == ("inbox", INBOX, True)
    assert succeed(kit.call("integrity_status", {"name": "inbox"}))["count"] == 1
    error = failed(kit.call("integrity_status", {"name": "absent"}), "not_found")
    assert "no integrity monitor named 'absent'" in error["message"]


def test_integrity_status_caps_the_changes_of_the_last_report() -> None:
    baseline = f"{BOX}/baselines/in.json"
    integrity_actions.integrity_baseline(INBOX, baseline)
    for index in range(5):
        File(f"{INBOX}/new-{index}.txt").write("new")
    integrity_actions.integrity_watch_start("inbox", INBOX, baseline, interval=0.05)
    deadline = time.monotonic() + 20
    report = None
    while report is None and time.monotonic() < deadline:
        time.sleep(0.05)
        report = integrity_actions.integrity_status("inbox")[0]["last_report"]
    assert report is not None, "the monitor did not complete a pass"
    body = succeed(toolkit(max_results=2).call("integrity_status", {}))
    trimmed = body["monitors"][0]["last_report"]
    assert len(trimmed["changes"]) == 2
    assert trimmed["changes_truncated"] is True
    assert trimmed["counts"]["created"] == 5


def test_audit_search_says_when_no_trail_is_kept() -> None:
    error = failed(toolkit().call("audit_search", {}), "not_configured")
    assert "configure_audit" in error["message"]


def test_audit_search_filters_and_caps_the_records() -> None:
    audited()
    with correlation_scope("run-1"):
        for index in range(6):
            emit(PipelineStarted(source="pipeline", subject=f"started {index}"))
    kit = toolkit(max_results=4)
    body = succeed(kit.call("audit_search", {"correlation_id": "run-1", "limit": 100}))
    assert (body["count"], body["total"], body["limit"], body["truncated"]) == (4, 6, 4, True)
    assert body["records"][0]["metadata"]["subject"] == "started 5"
    page = succeed(kit.call("audit_search", {"correlation_id": "run-1", "offset": 4}))
    assert (page["count"], page["offset"], page["truncated"]) == (2, 4, False)
    assert (
        succeed(kit.call("audit_search", {"action": "pipeline.started", "limit": 1}))["count"] == 1
    )
    assert succeed(kit.call("audit_search", {"text": "started 3"}))["total"] == 1
    assert succeed(kit.call("audit_search", {"since": "2100-01-01T00:00:00+00:00"}))["total"] == 0
    failed(kit.call("audit_search", {"since": "yesterday"}), "failed")
    failed(kit.call("audit_search", {"limit": 0}), "invalid_arguments")
    failed(kit.call("audit_search", {"unknown_filter": "x"}), "invalid_arguments")


def test_audit_search_finds_what_a_call_did_by_its_correlation_id() -> None:
    audited()
    kit = writable()
    # Not a word a random hexadecimal ID can contain.
    content = "payload-kept-out-of-the-trail"
    written = kit.call("file_write", {"uri": f"{INBOX}/a.txt", "content": content})
    body = succeed(kit.call("audit_search", {"correlation_id": written.correlation_id}))
    # Two records of one call can carry the same timestamp, so their order is not fixed.
    assert sorted((record["source"], record["action"]) for record in body["records"]) == [
        ("mcp", "mcp.tool.completed"),
        ("storage", "upload"),
    ]
    assert {record["actor"] for record in body["records"]} == {"mcp"}
    assert content not in json.dumps(body["records"])
