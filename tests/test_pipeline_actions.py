"""FA_pipeline_* actions: pipelines through the registry and ``execute_action``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from automation_file import ActionRegistry, execute_action, executor
from automation_file.pipeline import (
    MemoryRunStore,
    PipelineDefinitionException,
    PipelineException,
    actions,
    register_pipeline_ops,
    set_default_run_store,
)
from automation_file.storage import clear_memory_stores

NAMES = [
    "FA_pipeline_history",
    "FA_pipeline_resume",
    "FA_pipeline_run",
    "FA_pipeline_status",
    "FA_pipeline_validate",
]

YAML_TEXT = """\
schema_version: 1
name: notes
params: {text: default}
tasks:
  write:
    action: ["FA_storage_write_text", {"uri": "memory://pipeline/notes/${params.name}.txt", "text": "${params.text}"}]
  read:
    action: ["FA_storage_read_text", {"uri": "memory://pipeline/notes/${params.name}.txt"}]
    depends_on: [write]
"""


def definition(name: str = "notes") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": name,
        "tasks": {
            "write": {
                "action": [
                    "FA_storage_write_text",
                    {"uri": "memory://pipeline/a.txt", "text": "${params.text}"},
                ]
            },
            "read": {
                "action": ["FA_storage_read_text", {"uri": "memory://pipeline/a.txt"}],
                "depends_on": ["write"],
            },
            "size": {
                "action": ["FA_storage_stat", ["memory://pipeline/a.txt"]],
                "depends_on": ["write"],
            },
        },
    }


@pytest.fixture(autouse=True)
def _isolated() -> Iterator[MemoryRunStore]:
    """A fresh default run store, clean memory storage, and the actions on the shared executor."""
    clear_memory_stores()
    fresh = MemoryRunStore()
    previous = set_default_run_store(fresh)
    before = {name: executor.registry.resolve(name) for name in NAMES}
    register_pipeline_ops(executor.registry)
    yield fresh
    for name, command in before.items():
        if command is None:
            executor.registry.unregister(name)
        else:
            executor.registry.register(name, command)
    set_default_run_store(previous)
    clear_memory_stores()


def run_action(name: str, arguments: dict[str, Any]) -> Any:
    """Call one action through the shared executor and return its recorded result."""
    (result,) = execute_action([[name, arguments]]).values()
    return result


def test_register_pipeline_ops_fills_a_registry() -> None:
    registry = ActionRegistry()
    register_pipeline_ops(registry)
    assert sorted(registry.event_dict) == NAMES
    assert sorted(actions.pipeline_commands()) == NAMES
    assert all(callable(command) for command in actions.pipeline_commands().values())


def test_run_executes_a_definition_and_returns_the_run(_isolated: MemoryRunStore) -> None:
    result = run_action(
        "FA_pipeline_run", {"definition": definition(), "params": {"text": "hello"}}
    )
    assert json.loads(json.dumps(result)) == result
    assert result["pipeline"] == "notes"
    assert result["status"] == "succeeded"
    assert result["dry_run"] is False
    assert result["params"] == {"text": "hello"}
    assert result["error"] is None
    assert list(result["tasks"]) == ["write", "read", "size"]
    assert result["tasks"]["read"]["result"] == "hello"
    assert result["tasks"]["size"]["result"]["size"] == 5
    assert result["tasks"]["write"]["attempts"] == 1
    assert result["tasks"]["write"]["duration_ms"] >= 0
    assert _isolated.get_run(result["run_id"]).to_dict() == result


def test_run_takes_the_path_of_a_yaml_or_a_json_file(tmp_path: Path) -> None:
    yaml_file = tmp_path / "notes.yaml"
    yaml_file.write_text(YAML_TEXT, encoding="utf-8")
    from_yaml = run_action(
        "FA_pipeline_run", {"definition": str(yaml_file), "params": {"name": "a"}}
    )
    assert from_yaml["status"] == "succeeded"
    assert from_yaml["params"] == {"text": "default", "name": "a"}
    assert from_yaml["tasks"]["read"]["result"] == "default"
    json_file = tmp_path / "notes.json"
    json_file.write_text(json.dumps(definition("from-json")), encoding="utf-8")
    from_json = actions.pipeline_run(json_file, params={"text": "json"})
    assert (from_json["pipeline"], from_json["tasks"]["read"]["result"]) == ("from-json", "json")


def test_a_failed_task_does_not_raise_from_the_action() -> None:
    document = definition()
    document["tasks"]["read"]["action"][1]["uri"] = "memory://pipeline/absent.txt"
    document["tasks"]["after"] = {"action": ["FA_storage_schemes"], "depends_on": ["read"]}
    result = run_action("FA_pipeline_run", {"definition": document, "params": {"text": "x"}})
    assert result["status"] == "failed"
    assert result["error"] == "did not succeed: read"
    assert result["tasks"]["read"]["status"] == "failed"
    assert result["tasks"]["read"]["error"].startswith("StorageNotFoundException: ")
    assert result["tasks"]["after"] == {
        **result["tasks"]["after"],
        "status": "skipped",
        "reason": "upstream_failed",
    }


def test_a_dry_run_plans_without_executing_or_recording(_isolated: MemoryRunStore) -> None:
    document = definition()
    document["tasks"]["typo"] = {"action": ["FA_storage_wrte_text"]}
    result = run_action("FA_pipeline_run", {"definition": document, "dry_run": True})
    assert result["dry_run"] is True
    assert result["status"] == "failed"
    assert {task["status"] for task in result["tasks"].values()} == {"planned"}
    assert result["tasks"]["write"]["error"] == (
        "tasks.write.action[1].text: unknown parameter 'text'"
    )
    assert result["tasks"]["typo"]["error"] == (
        "tasks.typo.action[0]: unknown action 'FA_storage_wrte_text'"
    )
    assert [task["level"] for task in result["tasks"].values()] == [0, 0, 1, 1]
    assert _isolated.list_runs() == []
    assert run_action("FA_storage_exists", {"uri": "memory://pipeline/a.txt"}) is False


def test_an_invalid_definition_is_recorded_as_the_action_s_error(_isolated: MemoryRunStore) -> None:
    document = definition()
    document["tasks"]["read"]["depends_on"] = ["missing"]
    recorded = run_action("FA_pipeline_run", {"definition": document})
    assert "PipelineDefinitionException" in recorded
    assert "tasks.read.depends_on[0]: unknown task 'missing'" in recorded
    with pytest.raises(PipelineDefinitionException, match="unknown task 'missing'"):
        actions.pipeline_run(document)
    with pytest.raises(PipelineDefinitionException, match="expected a mapping or a file path"):
        actions.pipeline_run(["not", "a", "definition"])  # type: ignore[arg-type]
    with pytest.raises(PipelineDefinitionException, match="unknown parameter 'text'"):
        actions.pipeline_run(definition())
    assert _isolated.list_runs() == []


def test_validate_reports_every_problem(tmp_path: Path) -> None:
    assert run_action("FA_pipeline_validate", {"definition": definition()}) == {
        "valid": True,
        "errors": [],
    }
    document = definition()
    document["max_workers"] = 0
    document["tasks"]["read"]["depends_on"] = ["missing"]
    assert run_action("FA_pipeline_validate", {"definition": document}) == {
        "valid": False,
        "errors": [
            "max_workers: expected an integer >= 1, got 0",
            "tasks.read.depends_on[0]: unknown task 'missing'",
        ],
    }
    good = tmp_path / "good.yaml"
    good.write_text(YAML_TEXT, encoding="utf-8")
    assert actions.pipeline_validate(str(good)) == {"valid": True, "errors": []}
    broken = tmp_path / "broken.yaml"
    broken.write_text("tasks: [unclosed\n", encoding="utf-8")
    unreadable = actions.pipeline_validate(str(broken))
    assert unreadable["valid"] is False
    assert unreadable["errors"][0].startswith(f"{broken}: invalid YAML: ")
    missing = actions.pipeline_validate(str(tmp_path / "absent.json"))
    assert missing["valid"] is False
    assert "cannot read the definition" in missing["errors"][0]
    assert actions.pipeline_validate(7) == {  # type: ignore[arg-type]
        "valid": False,
        "errors": ["definition: expected a mapping or a file path, got int"],
    }


def test_status_returns_a_recorded_run() -> None:
    result = run_action("FA_pipeline_run", {"definition": definition(), "params": {"text": "x"}})
    assert run_action("FA_pipeline_status", {"run_id": result["run_id"]}) == result
    assert actions.pipeline_status(result["run_id"]) == result
    unknown = run_action("FA_pipeline_status", {"run_id": "no-such-run"})
    assert "PipelineException" in unknown
    assert "unknown run 'no-such-run'" in unknown
    with pytest.raises(PipelineException, match="unknown run"):
        actions.pipeline_status("no-such-run")


def test_history_lists_the_recorded_runs_newest_first() -> None:
    assert run_action("FA_pipeline_history", {}) == []
    first = actions.pipeline_run(definition("alpha"), params={"text": "1"})
    second = actions.pipeline_run(definition("beta"), params={"text": "2"})
    third = actions.pipeline_run(definition("alpha"), params={"text": "3"})
    history = run_action("FA_pipeline_history", {})
    assert history == [third, second, first]
    assert json.loads(json.dumps(history)) == history
    assert run_action("FA_pipeline_history", {"pipeline": "alpha"}) == [third, first]
    assert run_action("FA_pipeline_history", {"pipeline": "alpha", "limit": 1}) == [third]
    assert run_action("FA_pipeline_history", {"pipeline": "gamma"}) == []
    assert actions.pipeline_history(limit=2) == [third, second]
    (listed,) = execute_action([["FA_pipeline_history", ["beta", 5]]]).values()
    assert listed == [second]


def test_resume_continues_a_recorded_run(_isolated: MemoryRunStore) -> None:
    document = definition()
    document["tasks"]["read"]["action"][1]["uri"] = "memory://pipeline/late.txt"
    failed = run_action("FA_pipeline_run", {"definition": document, "params": {"text": "kept"}})
    assert failed["status"] == "failed"
    assert failed["tasks"]["write"]["status"] == "succeeded"
    run_action("FA_storage_write_text", {"uri": "memory://pipeline/late.txt", "text": "arrived"})
    run_action("FA_storage_write_text", {"uri": "memory://pipeline/a.txt", "text": "overwritten"})
    resumed = run_action("FA_pipeline_resume", {"run_id": failed["run_id"], "definition": document})
    assert resumed["run_id"] == failed["run_id"]
    assert resumed["status"] == "succeeded"
    assert resumed["params"] == {"text": "kept"}
    assert resumed["tasks"]["read"]["result"] == "arrived"
    assert resumed["tasks"]["write"] == failed["tasks"]["write"]  # not run again
    assert run_action("FA_storage_read_text", {"uri": "memory://pipeline/a.txt"}) == "overwritten"
    assert len(_isolated.list_runs()) == 1
    assert run_action("FA_pipeline_status", {"run_id": failed["run_id"]}) == resumed
    unknown = run_action("FA_pipeline_resume", {"run_id": "no-such-run", "definition": document})
    assert "unknown run 'no-such-run'" in unknown


def test_a_pipeline_action_can_be_a_task_of_another_pipeline(tmp_path: Path) -> None:
    inner = tmp_path / "inner.json"
    inner.write_text(json.dumps(definition("inner")), encoding="utf-8")
    outer = {
        "schema_version": 1,
        "name": "outer",
        "params": {"inner": str(inner)},
        "tasks": {
            "check": {"action": ["FA_pipeline_validate", {"definition": "${params.inner}"}]},
            "inner": {
                "action": [
                    "FA_pipeline_run",
                    {"definition": "${params.inner}", "params": {"text": "${params.text}"}},
                ],
                "depends_on": ["check"],
            },
        },
    }
    result = actions.pipeline_run(outer, params={"text": "nested"})
    assert result["status"] == "succeeded"
    assert result["tasks"]["check"]["result"] == {"valid": True, "errors": []}
    assert result["tasks"]["inner"]["result"]["tasks"]["read"]["result"] == "nested"
    assert sorted(run["pipeline"] for run in actions.pipeline_history()) == ["inner", "outer"]


def test_a_strict_verification_fails_its_task_on_a_mismatch() -> None:
    execute_action([["FA_storage_write_text", ["memory://pipeline/verified.txt", "hello"]]])
    described = {
        "schema_version": 1,
        "name": "verified",
        "tasks": {
            "verify": {
                "action": [
                    "FA_storage_verify",
                    {"uri": "memory://pipeline/verified.txt", "expected": "0" * 64, "strict": True},
                ]
            },
            "publish": {
                "action": ["FA_storage_read_text", {"uri": "memory://pipeline/verified.txt"}],
                "depends_on": ["verify"],
            },
        },
    }
    run = actions.pipeline_run(described)
    assert run["status"] == "failed"
    assert run["tasks"]["verify"]["status"] == "failed"
    assert "StorageChecksumException" in str(run["tasks"]["verify"])
    assert run["tasks"]["publish"]["status"] == "skipped"
