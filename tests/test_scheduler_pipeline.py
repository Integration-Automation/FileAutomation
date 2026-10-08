"""Pipelines as scheduler targets: the declared schedule, parameters, dependencies, stopping."""

from __future__ import annotations

import json
import time
import zoneinfo
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from automation_file.pipeline import (
    MemoryRunStore,
    Pipeline,
    PipelineDefinitionException,
    Schedule,
    TaskContext,
    set_default_run_store,
)
from automation_file.scheduler import (
    CronException,
    CronTrigger,
    PipelineTrigger,
    RunState,
    SchedulerException,
    TriggerKind,
)
from automation_file.scheduler.targets import fill_params
from tests.scheduler_kit import START, WAIT, Rig, wait_until

UTC = timezone.utc
NIGHTLY = Schedule("0 2 * * *", "UTC")


@pytest.fixture
def rig() -> Iterator[Rig]:
    with Rig() as made:
        yield made


@pytest.fixture(autouse=True)
def store() -> Iterator[MemoryRunStore]:
    """A default run store of this test's own: scheduled pipelines record their runs there."""
    fresh = MemoryRunStore()
    previous = set_default_run_store(fresh)
    yield fresh
    set_default_run_store(previous)


def simple(name: str, schedule: Schedule | None = None, result: Any = 1) -> Pipeline:
    pipeline = Pipeline(name, schedule=schedule)
    pipeline.task("load", lambda ctx: result)
    return pipeline


def failing(name: str, schedule: Schedule | None = None) -> Pipeline:
    def boom(_ctx: TaskContext) -> None:
        raise ValueError("the report is empty")

    pipeline = Pipeline(name, schedule=schedule)
    pipeline.task("load", boom)
    return pipeline


def waiting(name: str, entered: list[str]) -> Pipeline:
    """A pipeline whose only task goes on until its run is cancelled."""

    def hold(ctx: TaskContext) -> str:
        entered.append(ctx.run_id)
        deadline = time.monotonic() + WAIT
        while not ctx.cancel.is_cancelled and time.monotonic() < deadline:
            time.sleep(0.005)
        ctx.cancel.raise_if_cancelled()
        return "never cancelled"

    pipeline = Pipeline(name)
    pipeline.task("hold", hold)
    return pipeline


def types(rig: Rig) -> list[str]:
    return [event.type for event in rig.events]


# ---------------------------------------------------------------------- registration


def test_a_pipeline_with_a_schedule_is_registered_with_one_call(rig: Rig) -> None:
    snapshot = rig.engine.add_pipeline(simple("daily-report", NIGHTLY))
    assert snapshot == {
        "name": "daily-report",
        "cron": "0 2 * * *",
        "actions": 0,
        "last_run": None,
        "runs": 0,
        "allow_overlap": False,
        "running": False,
        "skipped": 0,
        "timezone": "UTC",
        "triggers": [{"kind": "cron", "cron": "0 2 * * *", "timezone": "UTC"}],
        "target": "pipeline",
        "pipeline": "daily-report",
        "timeout": None,
        "last_state": None,
    }
    assert "daily-report" in rig.engine


def test_a_scheduled_pipeline_runs_at_its_minute(rig: Rig, store: MemoryRunStore) -> None:
    rig.engine.add_pipeline(simple("daily-report", NIGHTLY))
    assert rig.engine.tick(datetime(2026, 10, 8, 1, 59, tzinfo=UTC)) == []
    (run,) = rig.engine.tick(datetime(2026, 10, 8, 2, 0, tzinfo=UTC))
    assert run.wait(WAIT)
    assert (run.state, run.trigger, run.target, run.pipeline) == (
        RunState.COMPLETED,
        TriggerKind.CRON,
        "pipeline",
        "daily-report",
    )
    stored = store.get_run(run.correlation_id)
    assert stored is not None and stored.status == "succeeded"
    assert run.correlation_id != run.run_id
    assert types(rig) == [
        "pipeline.started",
        "task.started",
        "task.completed",
        "pipeline.completed",
    ]
    assert {event.correlation_id for event in rig.events} == {run.correlation_id}
    assert {event.actor for event in rig.events} == {"scheduler"}
    assert rig.job("daily-report")["last_state"] == "completed"


def test_the_schedule_of_a_pipeline_keeps_its_time_zone(rig: Rig) -> None:
    try:
        zoneinfo.ZoneInfo("Asia/Taipei")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("no IANA zone data for Asia/Taipei (install tzdata)")
    seen: list[Any] = []
    pipeline = Pipeline("daily-report", schedule=Schedule("0 2 * * *", "Asia/Taipei"))
    pipeline.task("load", lambda ctx: seen.append(ctx.params["date"]))
    snapshot = rig.engine.add_pipeline(pipeline, params={"date": "${date:%Y-%m-%d %H:%M}"})
    assert snapshot["timezone"] == "Asia/Taipei"
    assert rig.engine.tick(datetime(2026, 10, 8, 2, 0, tzinfo=UTC)) == []
    (run,) = rig.engine.tick(datetime(2026, 10, 7, 18, 0, tzinfo=UTC))
    assert run.wait(WAIT)
    # 18:00 UTC on the 7th is 02:00 on the 8th in Taipei: the date is the job's, not UTC's.
    assert seen == ["2026-10-08 02:00"]


def test_a_schedule_in_an_unknown_zone_is_refused(rig: Rig) -> None:
    with pytest.raises(CronException, match="unknown time zone"):
        rig.engine.add_pipeline(simple("daily", Schedule("0 2 * * *", "Not/AZone")))
    assert rig.engine.list() == []


def test_a_pipeline_without_a_schedule_is_fired_by_hand_or_by_other_triggers(rig: Rig) -> None:
    snapshot = rig.engine.add_pipeline(simple("on-demand"))
    assert (snapshot["cron"], snapshot["triggers"]) == ("", [])
    assert rig.tick(minutes=1) == []
    run = rig.engine.run_now("on-demand")
    assert run.wait(WAIT)
    assert (run.state, run.trigger) == (RunState.COMPLETED, TriggerKind.MANUAL)


def test_extra_triggers_are_added_to_the_declared_schedule(rig: Rig) -> None:
    snapshot = rig.engine.add_pipeline(
        simple("daily", NIGHTLY), name="twice", triggers=CronTrigger("0 14 * * *", "UTC")
    )
    assert snapshot["name"] == "twice"
    assert [trigger["cron"] for trigger in snapshot["triggers"]] == ["0 2 * * *", "0 14 * * *"]
    assert len(rig.engine.tick(datetime(2026, 10, 8, 14, 0, tzinfo=UTC))) == 1


def test_add_job_takes_a_pipeline_and_does_not_read_its_schedule(rig: Rig) -> None:
    snapshot = rig.engine.add_job("explicit", simple("daily", NIGHTLY))
    assert (snapshot["cron"], snapshot["triggers"], snapshot["target"]) == ("", [], "pipeline")
    assert rig.engine.tick(datetime(2026, 10, 8, 2, 0, tzinfo=UTC)) == []


def test_a_definition_mapping_and_a_definition_file_are_targets(rig: Rig, tmp_path: Path) -> None:
    calls: list[str] = []
    definition = {
        "schema_version": 1,
        "name": "from-document",
        "schedule": {"cron": "0 2 * * *", "timezone": "UTC"},
        "params": {"label": "default"},
        "tasks": {"mark": {"action": [rig.command("mark", calls.append), ["${params.label}"]]}},
    }
    path = tmp_path / "from-file.json"
    path.write_text(json.dumps({**definition, "name": "from-file"}), encoding="utf-8")
    assert rig.engine.add_pipeline(definition)["name"] == "from-document"
    assert rig.engine.add_pipeline(str(path), params={"label": "file"})["name"] == "from-file"
    runs = rig.tick()
    assert sorted(run.job for run in runs) == ["from-document", "from-file"]
    assert all(run.wait(WAIT) for run in runs)
    assert {run.state for run in runs} == {RunState.COMPLETED}
    assert sorted(calls) == ["default", "file"]


def test_a_wrong_definition_is_refused_when_it_is_registered(rig: Rig, tmp_path: Path) -> None:
    with pytest.raises(PipelineDefinitionException, match="at least one task"):
        rig.engine.add_pipeline(Pipeline("empty"))
    with pytest.raises(PipelineDefinitionException, match="schema_version"):
        rig.engine.add_pipeline({"name": "no-version", "tasks": {}})
    with pytest.raises(PipelineDefinitionException):
        rig.engine.add_pipeline(str(tmp_path / "missing.yaml"))
    for wrong in (5, None):
        with pytest.raises(SchedulerException, match="expected a Pipeline"):
            rig.engine.add_job("job", wrong)
    assert rig.engine.list() == []


@pytest.mark.parametrize("name", ["", "  ", None, 5])
def test_a_job_needs_a_name(rig: Rig, name: Any) -> None:
    with pytest.raises(SchedulerException, match="job name"):
        rig.engine.add_job(name, simple("daily"))


def test_a_pipeline_cannot_depend_on_itself(rig: Rig) -> None:
    with pytest.raises(SchedulerException, match="cannot be fired by its own runs"):
        rig.engine.add_pipeline(simple("daily"), triggers=PipelineTrigger("daily"))
    assert rig.engine.list() == []


# ---------------------------------------------------------------------- parameters


def test_fill_params_replaces_the_date_placeholders() -> None:
    moment = datetime(2026, 10, 8, 2, 0, tzinfo=UTC)
    assert fill_params(
        {
            "date": "${date:%Y-%m-%d}",
            "stamp": "${date}",
            "path": "reports/${date:%Y}/${DATE:%m}.csv",
            "limit": 20,
            "nested": {"days": ["${date:%d}", 7]},
            "other": "${params.x} ${env:HOME}",
        },
        moment,
    ) == {
        "date": "2026-10-08",
        "stamp": "2026-10-08T02:00:00",
        "path": "reports/2026/10.csv",
        "limit": 20,
        "nested": {"days": ["08", 7]},
        "other": "${params.x} ${env:HOME}",
    }


def test_the_params_of_a_job_reach_every_run(rig: Rig) -> None:
    seen: list[dict[str, Any]] = []
    pipeline = Pipeline("daily", params={"limit": 5, "date": "unset"}, schedule=NIGHTLY)
    pipeline.task("load", lambda ctx: seen.append(dict(ctx.params)))
    rig.engine.add_pipeline(pipeline, params={"date": "${date:%Y-%m-%d}"})
    (run,) = rig.tick()
    assert run.wait(WAIT)
    assert seen == [{"limit": 5, "date": "2026-10-08"}]


@pytest.mark.parametrize("params", [["date"], "date", 5])
def test_params_are_a_mapping(rig: Rig, params: Any) -> None:
    with pytest.raises(SchedulerException, match="params: expected a mapping"):
        rig.engine.add_pipeline(simple("daily"), params=params)


def test_an_action_list_takes_no_params(rig: Rig) -> None:
    with pytest.raises(SchedulerException, match="params belong to a pipeline"):
        rig.engine.add_job("job", [["FA_schedule_list"]], params={"date": "x"})


# ---------------------------------------------------------------------- failures


def test_a_pipeline_that_fails_is_recorded_and_published(rig: Rig) -> None:
    rig.engine.add_pipeline(failing("daily", NIGHTLY))
    (run,) = rig.tick()
    assert run.wait(WAIT)
    assert run.state is RunState.FAILED
    assert run.error == "did not succeed: load"
    assert types(rig) == [
        "pipeline.started",
        "task.started",
        "task.failed",
        "pipeline.failed",
        "scheduler.error",
    ]
    assert {event.correlation_id for event in rig.events} == {run.correlation_id}
    (event,) = rig.errors()
    assert event.subject == "scheduler[daily] failed"
    assert dict(event.payload) == {
        "job": "daily",
        "trigger": "cron",
        "status": "failed",
        "error": "did not succeed: load",
        "target": "pipeline",
        "scheduler_run_id": run.run_id,
        "duration_ms": 0.0,
        "pipeline": "daily",
        "run_id": run.correlation_id,
    }
    assert rig.job("daily")["running"] is False


def test_a_run_that_cannot_start_is_recorded_as_failed(rig: Rig) -> None:
    pipeline = Pipeline("daily")
    pipeline.task("load", ["FA_schedule_list", {"unused": "${params.date}"}])
    rig.engine.add_pipeline(pipeline)
    run = rig.engine.run_now("daily")
    assert run.wait(WAIT)
    assert run.state is RunState.FAILED
    assert str(run.error).startswith("PipelineDefinitionException: ")
    assert "date" in str(run.error)
    assert run.correlation_id == run.run_id
    (event,) = rig.errors()
    assert event.correlation_id == run.run_id
    assert "run_id" not in event.payload
    assert event.payload["pipeline"] == "daily"


# ---------------------------------------------------------------------- dependencies


def test_a_dependent_pipeline_runs_after_the_other_succeeded(
    rig: Rig, store: MemoryRunStore
) -> None:
    rig.engine.add_pipeline(simple("daily-report", NIGHTLY))
    snapshot = rig.engine.add_pipeline(
        simple("publish-summary"), triggers=PipelineTrigger("daily-report")
    )
    assert snapshot["triggers"] == [
        {"kind": "pipeline", "pipeline": "daily-report", "when": "on_success"}
    ]
    (first,) = rig.tick()
    assert first.wait(WAIT)
    assert wait_until(lambda: len(rig.runs("publish-summary")) == 1)
    (second,) = rig.runs("publish-summary")
    assert second.wait(WAIT)
    assert (second.state, second.trigger) == (RunState.COMPLETED, TriggerKind.PIPELINE)
    assert second.detail == {
        "pipeline": "daily-report",
        "run_id": first.correlation_id,
        "status": "succeeded",
    }
    assert [run.pipeline for run in store.list_runs(None, 10)] == [
        "publish-summary",
        "daily-report",
    ]


@pytest.mark.parametrize(
    ("when", "upstream_fails", "fires"),
    [
        ("on_success", False, True),
        ("on_success", True, False),
        ("on_failure", False, False),
        ("on_failure", True, True),
        ("always", False, True),
        ("always", True, True),
    ],
)
def test_a_dependency_looks_at_how_the_other_run_ended(
    rig: Rig, when: str, upstream_fails: bool, fires: bool
) -> None:
    upstream = failing("upstream") if upstream_fails else simple("upstream")
    rig.engine.add_pipeline(upstream)
    rig.engine.add_pipeline(simple("downstream"), triggers=PipelineTrigger("upstream", when))
    assert rig.engine.run_now("upstream").wait(WAIT)
    assert len(rig.runs("downstream")) == int(fires)
    assert all(run.wait(WAIT) for run in rig.runs("downstream"))
    if fires:
        status = "failed" if upstream_fails else "succeeded"
        assert rig.runs("downstream")[0].detail["status"] == status


def test_a_dependency_also_sees_a_run_started_outside_the_scheduler(rig: Rig) -> None:
    rig.engine.add_pipeline(simple("downstream"), triggers=PipelineTrigger("upstream"))
    outside = simple("upstream").run(bus=rig.bus)
    simple("unrelated").run(bus=rig.bus)
    (run,) = rig.runs("downstream")
    assert run.wait(WAIT)
    assert run.detail["run_id"] == outside.run_id


def test_two_pipelines_that_depend_on_each_other_stop_after_sixteen_runs(rig: Rig) -> None:
    rig.engine.add_pipeline(simple("ping"), triggers=PipelineTrigger("pong"), allow_overlap=True)
    rig.engine.add_pipeline(simple("pong"), triggers=PipelineTrigger("ping"), allow_overlap=True)
    rig.engine.run_now("ping")
    assert wait_until(lambda: bool(rig.engine.history(state="skipped")))
    assert rig.idle("ping") and rig.idle("pong")
    records = rig.engine.history(limit=100)
    assert [run.state.value for run in records] == ["skipped"] + ["completed"] * 16
    assert (records[0].reason, records[0].trigger) == ("chain", TriggerKind.PIPELINE)
    assert rig.errors() == []


def test_an_action_list_can_depend_on_a_pipeline(rig: Rig) -> None:
    calls: list[int] = []
    rig.engine.add_job(
        "after-daily",
        [[rig.command("count", lambda: calls.append(1))]],
        triggers={"kind": "pipeline", "pipeline": "daily"},
    )
    simple("daily").run(bus=rig.bus)
    (run,) = rig.runs("after-daily")
    assert run.wait(WAIT)
    assert calls == [1]


# ---------------------------------------------------------------------- stopping


def test_a_pipeline_past_its_timeout_is_cancelled_through_its_token(
    rig: Rig, store: MemoryRunStore
) -> None:
    entered: list[str] = []
    rig.engine.add_pipeline(waiting("slow", entered), timeout=60)
    run = rig.engine.run_now("slow")
    assert wait_until(lambda: bool(entered))
    assert run.correlation_id == entered[0]  # the record follows the pipeline's run ID at once
    assert rig.tick(seconds=59) == []
    assert run.state is RunState.STARTED
    rig.tick(seconds=1)
    assert run.state is RunState.TIMEOUT
    assert run.error == "TimeoutError: not finished within 60 s"
    assert rig.idle("slow")
    stored = store.get_run(entered[0])
    assert stored is not None and stored.status == "cancelled"
    (event,) = rig.errors()
    assert (event.subject, event.payload["status"]) == ("scheduler[slow] timed out", "timeout")
    assert (event.payload["pipeline"], event.payload["run_id"]) == ("slow", entered[0])
    assert event.correlation_id == entered[0]
    assert run.state is RunState.TIMEOUT


def test_cancelling_a_scheduled_pipeline_stops_its_run(rig: Rig, store: MemoryRunStore) -> None:
    entered: list[str] = []
    rig.engine.add_pipeline(waiting("slow", entered))
    run = rig.engine.run_now("slow")
    assert wait_until(lambda: bool(entered))
    assert rig.engine.cancel("slow") == [run]
    assert (run.state, run.reason) == (RunState.CANCELLED, "cancelled")
    assert rig.idle("slow")
    stored = store.get_run(entered[0])
    assert stored is not None and stored.status == "cancelled"
    assert rig.errors() == []
    assert rig.engine.history(job="slow", state="cancelled") == [run]


def test_shutdown_can_cancel_what_is_running(store: MemoryRunStore) -> None:
    entered: list[str] = []
    with Rig() as rig:
        rig.engine.add_pipeline(waiting("slow", entered))
        run = rig.engine.run_now("slow")
        assert wait_until(lambda: bool(entered))
        rig.engine.shutdown()
        assert run.state is RunState.STARTED
        rig.engine.shutdown(cancel_running=True)
        assert run.state is RunState.CANCELLED
        assert rig.idle("slow")
    stored = store.get_run(entered[0])
    assert stored is not None and stored.status == "cancelled"


def test_the_start_time_of_the_fixture_is_the_nightly_minute() -> None:
    assert CronTrigger(NIGHTLY.cron, NIGHTLY.timezone).due(START) is True
