"""FA_schedule_* actions, the package's exports and what its modules may import."""

from __future__ import annotations

import ast
import importlib
import json
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from automation_file import ActionRegistry, execute_action, executor
from automation_file.core.action_registry import build_default_registry
from automation_file.pipeline import MemoryRunStore, set_default_run_store
from automation_file.scheduler import (
    JobRun,
    SchedulerException,
    register_scheduler_ops,
    schedule_add,
    schedule_cancel,
    schedule_history,
    schedule_job,
    schedule_list,
    schedule_pipeline,
    schedule_remove,
    schedule_remove_all,
    schedule_run,
    scheduler,
)
from automation_file.server.action_acl import ActionACL, ActionNotPermittedException
from tests.scheduler_kit import WAIT, Gate, wait_until

# ``automation_file.scheduler`` as an attribute is the facade's Scheduler instance, not the package.
scheduler_package = importlib.import_module("automation_file.scheduler")

NAMES = [
    "FA_schedule_add",
    "FA_schedule_cancel",
    "FA_schedule_history",
    "FA_schedule_job",
    "FA_schedule_list",
    "FA_schedule_pipeline",
    "FA_schedule_remove",
    "FA_schedule_remove_all",
    "FA_schedule_run",
]
LEGACY_KEYS = ["name", "cron", "actions", "last_run", "runs", "allow_overlap", "running", "skipped"]
NEVER = "0 0 30 2 *"  # 30 February: a valid expression that is never due
MARK = "scheduler_actions_mark"
HOLD = "scheduler_actions_hold"
PACKAGE = Path(scheduler_package.__file__).resolve().parent
MODULES = sorted(PACKAGE.glob("*.py"))
FORBIDDEN = ("automation_file.core.action_executor", "automation_file.ui", "automation_file.server")
PUBLIC_NAMES = [
    "CronException",
    "CronExpression",
    "CronTrigger",
    "EventTrigger",
    "FileTrigger",
    "JobRun",
    "PipelineTrigger",
    "RunHistory",
    "RunState",
    "ScheduledJob",
    "Scheduler",
    "SchedulerException",
    "Trigger",
    "TriggerKind",
    "register_scheduler_ops",
    "resolve_timezone",
    "schedule_add",
    "schedule_cancel",
    "schedule_history",
    "schedule_job",
    "schedule_list",
    "schedule_pipeline",
    "schedule_remove",
    "schedule_remove_all",
    "schedule_run",
    "scheduler",
    "trigger_from_dict",
]


@pytest.fixture
def marks() -> Iterator[list[Any]]:
    """Clean the process-wide scheduler around a test and give it two actions to schedule."""
    seen: list[Any] = []
    gate = Gate()
    previous = set_default_run_store(MemoryRunStore())
    executor.registry.register(MARK, seen.append)
    executor.registry.register(HOLD, gate)
    schedule_remove_all()
    yield seen
    gate.open()
    schedule_remove_all()
    scheduler.shutdown(cancel_running=True)
    executor.registry.unregister(MARK)
    executor.registry.unregister(HOLD)
    set_default_run_store(previous)


def latest(job: str) -> JobRun:
    return scheduler.history(job=job, limit=1)[0]


def definition(name: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": name,
        "schedule": {"cron": NEVER, "timezone": "UTC"},
        "tasks": {"mark": {"action": [MARK, ["${params.label}"]]}},
    }


# ---------------------------------------------------------------------- the registry


def test_register_scheduler_ops_adds_every_action() -> None:
    registry = ActionRegistry()
    register_scheduler_ops(registry)
    assert sorted(registry.event_dict) == NAMES


def test_the_default_registry_and_the_shared_executor_have_them() -> None:
    registry = build_default_registry()
    for name in NAMES:
        assert name in registry
        assert executor.registry.resolve(name) is not None


def test_every_action_says_what_it_does() -> None:
    registry = ActionRegistry()
    register_scheduler_ops(registry)
    for name, command in registry.event_dict.items():
        assert (command.__doc__ or "").strip(), name


# ---------------------------------------------------------------------- the actions


def test_the_legacy_add_keeps_its_parameters_and_its_result(marks: list[Any]) -> None:
    snapshot = schedule_add("legacy", NEVER, [[MARK, ["x"]]])
    assert list(snapshot)[: len(LEGACY_KEYS)] == LEGACY_KEYS
    assert [snapshot[key] for key in LEGACY_KEYS] == ["legacy", NEVER, 1, None, 0, False, False, 0]
    assert schedule_add("positional", NEVER, [[MARK, ["x"]]], allow_overlap=True)["allow_overlap"]
    assert [job["name"] for job in schedule_list()] == ["legacy", "positional"]
    assert schedule_remove("legacy")["name"] == "legacy"
    assert [job["name"] for job in schedule_remove_all()] == ["positional"]
    assert schedule_list() == []
    assert marks == []


def test_add_takes_a_time_zone_and_a_timeout_through_the_executor(marks: list[Any]) -> None:
    results = execute_action(
        [
            [
                "FA_schedule_add",
                {
                    "name": "zoned",
                    "cron_expression": NEVER,
                    "action_list": [[MARK, ["x"]]],
                    "timezone": "UTC",
                    "timeout": 120,
                },
            ],
            ["FA_schedule_add", ["by-position", NEVER, [[MARK, ["y"]]]]],
            ["FA_schedule_list"],
        ]
    )
    added, positional, listed = results.values()
    assert (added["timezone"], added["timeout"]) == ("UTC", 120.0)
    assert (positional["timezone"], positional["timeout"]) == (None, None)
    assert [job["name"] for job in listed] == ["zoned", "by-position"]
    assert json.loads(json.dumps(listed)) == listed
    assert marks == []


def test_a_job_is_registered_fired_and_read_back_through_actions(marks: list[Any]) -> None:
    results = execute_action(
        [
            [
                "FA_schedule_job",
                {
                    "name": "by-hand",
                    "action_list": [[MARK, ["fired"]]],
                    "triggers": [{"kind": "event", "types": ["deploy.finished"]}],
                    "timeout": 60,
                },
            ],
            ["FA_schedule_run", {"name": "by-hand"}],
        ]
    )
    job, fired = results.values()
    assert job["triggers"] == [
        {"kind": "event", "types": ["deploy.finished"], "sources": [], "min_severity": "info"}
    ]
    assert (fired["job"], fired["trigger"]) == ("by-hand", "manual")
    assert fired["state"] in ("scheduled", "started", "completed")
    assert latest("by-hand").wait(WAIT)
    assert marks == ["fired"]
    (history,) = execute_action(
        [["FA_schedule_history", {"job": "by-hand", "state": "completed", "limit": 5}]]
    ).values()
    assert [(run["run_id"], run["state"]) for run in history] == [(fired["run_id"], "completed")]
    assert json.loads(json.dumps(history)) == history
    assert schedule_history(job="by-hand", state="failed") == []


def test_schedule_job_checks_its_action_list(marks: list[Any]) -> None:
    with pytest.raises(SchedulerException, match="action_list: expected a list"):
        schedule_job("job", {"schema_version": 1, "name": "sneaked-in", "tasks": {}})
    assert schedule_job("no-trigger", [[MARK, ["x"]]])["triggers"] == []
    assert marks == []


def test_a_pipeline_is_registered_from_a_mapping_and_from_a_file(
    marks: list[Any], tmp_path: Path
) -> None:
    path = tmp_path / "from-file.json"
    path.write_text(json.dumps(definition("from-file")), encoding="utf-8")
    results = execute_action(
        [
            [
                "FA_schedule_pipeline",
                {"definition": definition("from-map"), "params": {"label": "a"}},
            ],
            [
                "FA_schedule_pipeline",
                {
                    "definition": str(path),
                    "name": "renamed",
                    "params": {"label": "${date:%Y}"},
                    "triggers": [{"kind": "pipeline", "pipeline": "from-map"}],
                    "timeout": 600,
                },
            ],
        ]
    )
    first, second = results.values()
    assert (first["name"], first["cron"], first["timezone"]) == ("from-map", NEVER, "UTC")
    assert (first["target"], first["pipeline"], first["actions"]) == ("pipeline", "from-map", 0)
    assert (second["name"], second["pipeline"], second["timeout"]) == (
        "renamed",
        "from-file",
        600.0,
    )
    assert [trigger["kind"] for trigger in second["triggers"]] == ["cron", "pipeline"]
    assert schedule_run("from-map")["target"] == "pipeline"
    assert latest("from-map").wait(WAIT)
    assert wait_until(lambda: len(scheduler.history(job="renamed")) == 1)
    assert latest("renamed").wait(WAIT)
    assert latest("renamed").trigger == "pipeline"
    assert len(marks) == 2 and marks[0] == "a" and len(marks[1]) == 4


def test_schedule_pipeline_takes_positional_arguments(marks: list[Any]) -> None:
    assert schedule_pipeline(definition("positional"), "other-name")["name"] == "other-name"
    assert marks == []


def test_a_running_job_is_cancelled_through_an_action(marks: list[Any]) -> None:
    schedule_job("slow", [[HOLD], [MARK, ["after"]]])
    fired = schedule_run("slow")
    assert wait_until(lambda: latest("slow").state == "started")
    skipped = schedule_run("slow")
    assert (skipped["state"], skipped["reason"]) == ("skipped", "overlap")
    (cancelled,) = execute_action([["FA_schedule_cancel", {"name": "slow"}]]).values()
    assert [(run["run_id"], run["state"]) for run in cancelled] == [(fired["run_id"], "cancelled")]
    assert schedule_cancel("slow") == []
    assert marks == []


def test_an_action_that_fails_is_recorded_by_the_executor_as_usual(marks: list[Any]) -> None:
    results = execute_action(
        [
            ["FA_schedule_run", {"name": "nope"}],
            ["FA_schedule_cancel", {"name": "nope"}],
            ["FA_schedule_history", {"state": "done"}],
            ["FA_schedule_pipeline", {"definition": {"name": "no-version"}}],
        ]
    )
    run, cancel, history, pipeline = results.values()
    assert "SchedulerException" in run and "no such job: nope" in run
    assert "SchedulerException" in cancel
    assert "unknown run state" in history
    assert "PipelineDefinitionException" in pipeline
    assert marks == []


def test_the_process_wide_scheduler_restarts_after_a_shutdown(marks: list[Any]) -> None:
    def loops() -> set[threading.Thread]:
        return {thread for thread in threading.enumerate() if thread.name == "fa-scheduler"}

    before = loops()
    schedule_add("first", NEVER, [[MARK, ["x"]]])
    (first,) = loops() - before
    scheduler.shutdown()
    assert first.is_alive() is False
    schedule_add("second", NEVER, [[MARK, ["y"]]])
    (second,) = loops() - before
    assert second is not first and second.daemon is True
    assert marks == []


# ---------------------------------------------------------------------- the ACL


def test_an_acl_sees_the_actions_a_scheduled_job_would_run() -> None:
    acl = ActionACL.build(denied=["FA_storage_delete"])
    nested = [["FA_storage_delete", {"uri": "local:///data"}]]
    with pytest.raises(ActionNotPermittedException):
        acl.enforce([["FA_schedule_job", {"name": "job", "action_list": nested}]])
    with pytest.raises(ActionNotPermittedException):
        acl.enforce(
            [
                [
                    "FA_schedule_pipeline",
                    {"definition": {"tasks": {"wipe": {"action": nested[0]}}}},
                ]
            ]
        )
    acl.enforce([["FA_schedule_run", {"name": "job"}], ["FA_schedule_history"]])


# ---------------------------------------------------------------------- the package


def _module_level_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: relative import"
            names.append(node.module or "")
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _is_allowed(name: str) -> bool:
    top_level = name.partition(".")[0]
    if top_level == "automation_file":
        return not any(name == banned or name.startswith(f"{banned}.") for banned in FORBIDDEN)
    return top_level in sys.stdlib_module_names or name == "__future__"


def test_the_package_has_its_modules() -> None:
    assert {path.name for path in MODULES} == {
        "__init__.py",
        "cron.py",
        "dispatch.py",
        "errors.py",
        "job.py",
        "manager.py",
        "runs.py",
        "targets.py",
        "triggers.py",
    }


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_module_level_imports_are_safe_while_the_registry_is_built(path: Path) -> None:
    """The registry is built while the executor is still being imported: no module may need it."""
    offending = [name for name in _module_level_imports(path) if not _is_allowed(name)]
    assert offending == []


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_every_module_starts_with_the_future_import(path: Path) -> None:
    assert "from __future__ import annotations" in path.read_text(encoding="utf-8")


def test_the_package_exports_its_public_names() -> None:
    assert sorted(scheduler_package.__all__) == sorted(PUBLIC_NAMES)
    for name in PUBLIC_NAMES:
        assert hasattr(scheduler_package, name), name


def test_the_names_the_old_scheduler_exported_are_still_there() -> None:
    from automation_file.scheduler import manager

    for name in (
        "CronException",
        "CronExpression",
        "ScheduledJob",
        "Scheduler",
        "register_scheduler_ops",
        "schedule_add",
        "schedule_list",
        "schedule_remove",
        "schedule_remove_all",
        "scheduler",
    ):
        assert name in scheduler_package.__all__
    for name in ("ScheduledJob", "Scheduler", "SchedulerException", "_safe_execute", "scheduler"):
        assert hasattr(manager, name), name
    assert manager.ScheduledJob is scheduler_package.ScheduledJob
