"""Run records of the scheduler: the seven states, overlap, timeout, cancellation, history."""

# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import timedelta, timezone
from typing import Any

import pytest

from automation_file.events import Event, SchedulerError, Severity, event_bus
from automation_file.exceptions import FileAutomationException
from automation_file.scheduler import (
    EventTrigger,
    JobRun,
    RunHistory,
    RunState,
    Scheduler,
    SchedulerException,
    TriggerKind,
    dispatch,
    manager,
)
from tests.scheduler_kit import START, WAIT, Rig, wait_until

EVERY_MINUTE = "* * * * *"


@pytest.fixture
def rig() -> Iterator[Rig]:
    with Rig() as made:
        yield made


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> list[threading.Thread]:
    """Threads that were asked to start and are kept back until the test starts them."""
    kept: list[threading.Thread] = []

    def hold(thread: threading.Thread) -> None:
        kept.append(thread)

    monkeypatch.setattr(threading.Thread, "start", hold)
    return kept


def test_the_seven_states_and_which_of_them_are_final() -> None:
    assert [state.value for state in RunState] == [
        "scheduled",
        "started",
        "completed",
        "failed",
        "skipped",
        "timeout",
        "cancelled",
    ]
    assert [state for state in RunState if not state.is_final] == [
        RunState.SCHEDULED,
        RunState.STARTED,
    ]
    assert RunState.FAILED == "failed"


def test_a_run_is_scheduled_then_started_then_completed(rig: Rig) -> None:
    action, gate = rig.gate()
    rig.engine.add_job("job", [[action]])
    run = rig.engine.run_now("job")
    gate.await_entry()
    assert run.state is RunState.STARTED
    assert run.done is False
    assert run.started_at == START
    assert rig.job("job")["running"] is True
    rig.clock.advance(seconds=2)
    gate.open()
    assert run.wait(WAIT) is True
    assert run.state is RunState.COMPLETED
    assert (run.scheduled_at, run.started_at, run.finished_at) == (
        START,
        START,
        START + timedelta(seconds=2),
    )
    assert run.duration_ms == 2000.0
    assert run.error is None
    assert rig.job("job") == {
        "name": "job",
        "cron": "",
        "actions": 1,
        "last_run": START.astimezone().replace(tzinfo=None).isoformat(),
        "runs": 1,
        "allow_overlap": False,
        "running": False,
        "skipped": 0,
        "timezone": None,
        "triggers": [],
        "target": "actions",
        "pipeline": None,
        "timeout": None,
        "last_state": "completed",
    }


def test_a_firing_is_recorded_as_scheduled_before_its_thread_runs(
    rig: Rig, held: list[threading.Thread], monkeypatch: pytest.MonkeyPatch
) -> None:
    rig.engine.add_job("job", [[rig.command("ok", lambda: 1)]])
    run = rig.engine.run_now("job")
    assert run.state is RunState.SCHEDULED
    assert (run.started_at, run.finished_at) == (None, None)
    assert rig.job("job")["running"] is True
    monkeypatch.undo()
    held[0].start()
    assert run.wait(WAIT) is True
    assert run.state is RunState.COMPLETED


def test_the_times_of_a_record_are_aware_utc(rig: Rig) -> None:
    rig.engine.add_job("job", [[rig.command("ok", lambda: 1)]])
    run = rig.engine.run_now("job")
    assert run.wait(WAIT)
    for moment in (run.scheduled_at, run.started_at, run.finished_at):
        assert moment is not None and moment.utcoffset() == timedelta(0)
        assert moment.tzinfo is timezone.utc


def test_a_record_is_json_friendly(rig: Rig) -> None:
    rig.engine.add(
        "job", EVERY_MINUTE, [[rig.command("ok", lambda: 1)]], timezone="UTC", timeout=30
    )
    (run,) = rig.engine.tick()
    assert run.wait(WAIT)
    document = json.loads(json.dumps(run.to_dict()))
    assert document == {
        "run_id": run.run_id,
        "job": "job",
        "trigger": "cron",
        "target": "actions",
        "pipeline": None,
        "state": "completed",
        "scheduled_at": "2026-10-08T02:00:00.000000+00:00",
        "started_at": "2026-10-08T02:00:00.000000+00:00",
        "finished_at": "2026-10-08T02:00:00.000000+00:00",
        "duration_ms": 0.0,
        "error": None,
        "reason": None,
        "correlation_id": run.run_id,
        "detail": {"cron": EVERY_MINUTE, "timezone": "UTC"},
    }
    assert len(run.run_id) == 32


def test_the_target_runs_inside_the_runs_correlation_scope(rig: Rig) -> None:
    from automation_file.events import current_actor, current_correlation_id

    seen: list[tuple[str | None, str]] = []
    rig.engine.add_job(
        "job",
        [[rig.command("look", lambda: seen.append((current_correlation_id(), current_actor())))]],
    )
    run = rig.engine.run_now("job")
    assert run.wait(WAIT)
    assert seen == [(run.correlation_id, "scheduler")]
    assert run.correlation_id == run.run_id


# ---------------------------------------------------------------------- overlap


def test_a_firing_that_overlaps_is_recorded_as_skipped(rig: Rig) -> None:
    action, gate = rig.gate()
    rig.engine.add_job("job", [[action]])
    first = rig.engine.run_now("job")
    gate.await_entry()
    second = rig.engine.run_now("job")
    assert second.state is RunState.SKIPPED
    assert second.reason == "overlap"
    assert second.done and second.wait(0) is True
    assert (second.started_at, second.finished_at) == (None, START)
    assert rig.job("job")["skipped"] == 1
    assert rig.job("job")["runs"] == 1
    gate.open()
    assert first.wait(WAIT) and first.state is RunState.COMPLETED
    assert gate.calls == 1
    assert [run.state.value for run in rig.runs("job")] == ["skipped", "completed"]
    assert rig.errors() == []


def test_overlap_is_allowed_when_the_job_says_so(rig: Rig) -> None:
    action, gate = rig.gate()
    rig.engine.add_job("job", [[action]], allow_overlap=True)
    first = rig.engine.run_now("job")
    second = rig.engine.run_now("job")
    assert wait_until(lambda: gate.calls == 2)
    assert rig.job("job")["skipped"] == 0
    gate.open()
    assert first.wait(WAIT) and second.wait(WAIT)
    assert {first.state, second.state} == {RunState.COMPLETED}
    assert rig.idle("job")
    assert rig.job("job")["runs"] == 2


def test_a_job_counts_as_running_until_its_last_overlapping_run_has_ended(rig: Rig) -> None:
    slow_action, slow = rig.gate("slow")
    rig.engine.add_job("job", [[slow_action]], allow_overlap=True)
    first = rig.engine.run_now("job")
    slow.await_entry()
    second = rig.engine.run_now("job")
    assert wait_until(lambda: slow.calls == 2)
    assert rig.job("job")["running"] is True
    slow.open()
    assert first.wait(WAIT) and second.wait(WAIT)
    assert rig.idle("job")


@pytest.mark.parametrize("kind", ["cron", "manual", "event"])
def test_overlap_protection_covers_every_kind_of_trigger(rig: Rig, kind: str) -> None:
    action, gate = rig.gate()
    rig.engine.add_job(
        "job",
        [[action]],
        triggers=[{"kind": "cron", "cron": EVERY_MINUTE}, EventTrigger(types="deploy.finished")],
    )
    first = rig.engine.run_now("job")
    gate.await_entry()
    if kind == "cron":
        rig.tick()
    elif kind == "manual":
        rig.engine.run_now("job")
    else:
        rig.bus.publish(_Deploy(source="webhook"))
    skipped = rig.engine.history(job="job", state=RunState.SKIPPED)
    assert [(run.trigger.value, run.reason) for run in skipped] == [(kind, "overlap")]
    gate.open()
    assert first.wait(WAIT)
    assert gate.calls == 1


# ---------------------------------------------------------------------- failures


def test_an_action_that_raises_fails_the_run_and_the_list_goes_on(rig: Rig) -> None:
    def boom() -> None:
        raise ValueError("the report is empty")

    later: list[int] = []
    rig.engine.add_job(
        "job", [[rig.command("boom", boom)], [rig.command("later", lambda: later.append(1))]]
    )
    run = rig.engine.run_now("job")
    assert run.wait(WAIT)
    assert run.state is RunState.FAILED
    assert run.error == (
        "1 of 2 actions failed: execute[0] scheduler_test_boom: ValueError: the report is empty"
    )
    assert later == [1]
    assert rig.job("job")["last_state"] == "failed"
    assert rig.job("job")["running"] is False


def test_a_failed_run_is_published_as_a_scheduler_error(rig: Rig) -> None:
    def boom() -> None:
        raise ValueError("the report is empty")

    rig.engine.add("job", EVERY_MINUTE, [[rig.command("boom", boom)]], timezone="UTC")
    (run,) = rig.engine.tick()
    assert run.wait(WAIT)
    (event,) = rig.errors()
    assert isinstance(event, SchedulerError)
    assert (event.type, event.source, event.severity) == (
        "scheduler.error",
        "scheduler",
        Severity.ERROR,
    )
    assert event.subject == "scheduler[job] failed"
    assert event.correlation_id == run.correlation_id
    assert event.actor == "scheduler"
    assert dict(event.payload) == {
        "job": "job",
        "trigger": "cron",
        "status": "failed",
        "error": run.error,
        "target": "actions",
        "scheduler_run_id": run.run_id,
        "duration_ms": 0.0,
    }


def test_the_error_text_keeps_a_url_down_to_its_host(rig: Rig) -> None:
    def boom() -> None:
        raise ConnectionError("POST https://hooks.example.com/services/T0/B0/secret failed")

    rig.engine.add_job("job", [[rig.command("boom", boom)]])
    run = rig.engine.run_now("job")
    assert run.wait(WAIT)
    assert "secret" not in str(run.error)
    assert "hooks.example.com" in str(run.error)
    assert "secret" not in json.dumps(rig.errors()[0].to_dict())


def test_many_failures_are_summarised(rig: Rig) -> None:
    def boom() -> None:
        raise ValueError("no")

    action = rig.command("boom", boom)
    rig.engine.add_job("job", [[action]] * 7)
    run = rig.engine.run_now("job")
    assert run.wait(WAIT)
    assert str(run.error).startswith("7 of 7 actions failed: execute[0] ")
    assert str(run.error).endswith("; and 2 more")
    assert str(run.error).count("execute[") == 5


def test_a_list_the_executor_rejects_is_reported_through_notify_on_failure(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from automation_file.notify import manager as notify_manager

    reported: list[tuple[str, BaseException]] = []
    monkeypatch.setattr(
        notify_manager,
        "notify_on_failure",
        lambda context, error: reported.append((context, error)),
    )
    rig.engine.add("job", EVERY_MINUTE, [])
    (run,) = rig.engine.tick()
    assert run.wait(WAIT)
    assert run.state is RunState.FAILED
    assert run.error == "ExecuteActionException: action_list is empty"
    assert [(context, type(error).__name__) for context, error in reported] == [
        ("scheduler[job]", "ExecuteActionException")
    ]
    assert rig.errors() == []


def test_a_rejected_list_gives_exactly_one_scheduler_error_on_the_process_bus() -> None:
    seen: list[Any] = []
    subscription = event_bus.subscribe(seen.append, types="scheduler.error")
    engine = Scheduler(autostart=False)
    try:
        engine.add_job("rejected-list", [])
        run = engine.run_now("rejected-list")
        assert run.wait(WAIT)
    finally:
        event_bus.unsubscribe(subscription)
        engine.shutdown()
    assert [(event.subject, event.correlation_id) for event in seen] == [
        ("scheduler[rejected-list] failed", run.correlation_id)
    ]
    assert seen[0].payload["job"] == "rejected-list"


def test_a_run_ended_by_a_base_exception_still_releases_the_job(
    rig: Rig, held: list[threading.Thread], monkeypatch: pytest.MonkeyPatch
) -> None:
    def leave() -> None:
        raise SystemExit(3)  # not an Exception: nothing in the run's thread catches it

    rig.engine.add_job("job", [[rig.command("leave", leave)]])
    run = rig.engine.run_now("job")
    monkeypatch.undo()
    with pytest.raises(SystemExit):
        held[0].run()  # the body of the run's thread, called here so the exit is seen
    assert run.wait(0) is True
    assert run.state is RunState.FAILED
    assert run.error == "the run's thread ended without a result"
    assert rig.job("job")["running"] is False
    assert [event.payload["status"] for event in rig.errors()] == ["failed"]


def test_a_target_that_raises_unexpectedly_is_recorded_and_the_job_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_arguments: Any) -> None:
        raise RuntimeError("the runner itself broke")

    monkeypatch.setattr(manager, "_safe_execute", broken)
    with Rig() as rig:
        rig.engine.add_job("job", [["FA_schedule_list"]])
        run = rig.engine.run_now("job")
        assert run.wait(WAIT)
        assert run.state is RunState.FAILED
        assert run.error == "RuntimeError: the runner itself broke"
        assert rig.job("job")["running"] is False
        assert [event.payload["status"] for event in rig.errors()] == ["failed"]


def test_a_thread_that_cannot_start_fails_the_run_and_releases_the_job(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_thread: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    rig.engine.add_job("job", [[rig.command("ok", lambda: 1)]])
    monkeypatch.setattr(dispatch.threading.Thread, "start", refuse)
    run = rig.engine.run_now("job")
    monkeypatch.undo()
    assert run.state is RunState.FAILED
    assert run.error == "RuntimeError: can't start new thread"
    assert rig.job("job")["running"] is False
    assert rig.engine.run_now("job").wait(WAIT)


def test_safe_execute_reports_how_the_list_went(rig: Rig) -> None:
    def boom() -> None:
        raise ValueError("no")

    good = manager._safe_execute("unit", [[rig.command("ok", lambda: 1)]])
    assert (good.state, good.error, good.reported) == (RunState.COMPLETED, None, False)
    bad = manager._safe_execute("unit", [[rig.command("boom", boom)]])
    assert (bad.state, bad.reported) == (RunState.FAILED, False)
    unknown = manager._safe_execute("unit", [["FA_does_not_exist"]])
    assert unknown.state is RunState.FAILED
    assert "FA_does_not_exist" in str(unknown.error)


# ---------------------------------------------------------------------- timeout


def test_a_run_past_its_timeout_is_recorded_as_timeout(rig: Rig) -> None:
    action, gate = rig.gate()
    after: list[int] = []
    rig.engine.add(
        "job",
        EVERY_MINUTE,
        [[action], [rig.command("after", lambda: after.append(1))]],
        timezone="UTC",
        timeout=30,
    )
    (run,) = rig.engine.tick()
    gate.await_entry()
    assert rig.tick(seconds=29) == []
    assert run.state is RunState.STARTED
    rig.tick(seconds=1)
    assert run.state is RunState.TIMEOUT
    assert run.wait(0) is True
    assert run.error == "TimeoutError: not finished within 30 s"
    assert run.finished_at == START + timedelta(seconds=30)
    (event,) = rig.errors()
    assert event.subject == "scheduler[job] timed out"
    assert (event.payload["status"], event.payload["duration_ms"]) == ("timeout", 30000.0)
    assert event.correlation_id == run.correlation_id
    # The thread cannot be killed: the job stays busy until the action returns.
    assert rig.job("job")["running"] is True
    assert rig.engine.run_now("job").state is RunState.SKIPPED
    gate.open()
    assert rig.idle("job")
    assert after == []
    assert run.state is RunState.TIMEOUT
    assert rig.job("job")["last_state"] == "timeout"
    assert len(rig.errors()) == 1
    assert rig.engine.run_now("job").wait(WAIT)


def test_a_run_that_ends_in_time_is_not_touched_by_its_timeout(rig: Rig) -> None:
    rig.engine.add_job("job", [[rig.command("ok", lambda: 1)]], timeout=30)
    run = rig.engine.run_now("job")
    assert run.wait(WAIT)
    rig.tick(minutes=5)
    assert run.state is RunState.COMPLETED
    assert rig.errors() == []


@pytest.mark.parametrize("timeout", [0, -1, True, "60", float("inf"), float("nan"), 1e12])
def test_a_timeout_must_be_seconds_above_zero(rig: Rig, timeout: Any) -> None:
    with pytest.raises(SchedulerException, match="timeout"):
        rig.engine.add("job", EVERY_MINUTE, [["FA_schedule_list"]], timeout=timeout)
    assert "job" not in rig.engine


# ---------------------------------------------------------------------- cancel


def test_cancelling_a_running_job_records_the_run_as_cancelled(rig: Rig) -> None:
    action, gate = rig.gate()
    after: list[int] = []
    rig.engine.add_job("job", [[action], [rig.command("after", lambda: after.append(1))]])
    run = rig.engine.run_now("job")
    gate.await_entry()
    rig.clock.advance(seconds=3)
    assert rig.engine.cancel("job") == [run]
    assert run.state is RunState.CANCELLED
    assert (run.reason, run.error) == ("cancelled", None)
    assert run.finished_at == START + timedelta(seconds=3)
    assert run.wait(0) is True
    assert rig.job("job")["running"] is True
    gate.open()
    assert rig.idle("job")
    assert after == []
    assert rig.errors() == []
    assert rig.job("job")["last_state"] == "cancelled"


def test_cancel_returns_nothing_for_an_idle_job_and_refuses_an_unknown_one(rig: Rig) -> None:
    rig.engine.add_job("job", [["FA_schedule_list"]])
    assert rig.engine.cancel("job") == []
    with pytest.raises(SchedulerException, match="no such job: nope"):
        rig.engine.cancel("nope")
    with pytest.raises(SchedulerException, match="no such job: None"):
        rig.engine.cancel(None)


def test_a_subscriber_can_fire_the_failed_job_again_at_once(rig: Rig) -> None:
    attempts: list[int] = []

    def flaky() -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("first attempt")

    retried: list[JobRun] = []
    rig.bus.subscribe(
        lambda event: retried.append(rig.engine.run_now(event.payload["job"])),
        types="scheduler.error",
    )
    rig.engine.add_job("job", [[rig.command("flaky", flaky)]])
    first = rig.engine.run_now("job")
    assert first.wait(WAIT) and first.state is RunState.FAILED
    (second,) = retried
    assert second.wait(WAIT)
    assert second.state is RunState.COMPLETED
    assert rig.job("job")["skipped"] == 0


def test_a_removed_job_that_is_still_running_can_be_cancelled(rig: Rig) -> None:
    action, gate = rig.gate()
    rig.engine.add_job("job", [[action]])
    run = rig.engine.run_now("job")
    gate.await_entry()
    rig.engine.remove("job")
    assert run.state is RunState.STARTED
    assert rig.engine.cancel("job") == [run]
    assert run.state is RunState.CANCELLED


def test_a_run_cancelled_before_it_started_never_runs_its_target(
    rig: Rig, held: list[threading.Thread], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    rig.engine.add_job("job", [[rig.command("count", lambda: calls.append(1))]])
    run = rig.engine.run_now("job")
    assert rig.engine.cancel("job") == [run]
    monkeypatch.undo()
    held[0].start()
    assert rig.idle("job")
    assert calls == []
    assert (run.state, run.started_at) == (RunState.CANCELLED, None)


# ---------------------------------------------------------------------- manual


def test_run_now_fires_a_job_that_has_no_trigger(rig: Rig) -> None:
    calls: list[int] = []
    snapshot = rig.engine.add_job("by-hand", [[rig.command("count", lambda: calls.append(1))]])
    assert (snapshot["triggers"], snapshot["cron"]) == ([], "")
    assert rig.tick(minutes=1) == []
    run = rig.engine.run_now("by-hand")
    assert run.wait(WAIT)
    assert (run.trigger, run.detail) == (TriggerKind.MANUAL, {})
    assert calls == [1]


def test_run_now_refuses_an_unknown_job(rig: Rig) -> None:
    with pytest.raises(SchedulerException, match="no such job: nope"):
        rig.engine.run_now("nope")


# ---------------------------------------------------------------------- history


def test_the_history_is_newest_first_and_can_be_filtered(rig: Rig) -> None:
    def boom() -> None:
        raise ValueError("no")

    rig.engine.add_job("good", [[rig.command("ok", lambda: 1)]])
    rig.engine.add_job("bad", [[rig.command("boom", boom)]])
    for name in ("good", "bad", "good"):
        assert rig.engine.run_now(name).wait(WAIT)
    assert [(run.job, run.state.value) for run in rig.engine.history()] == [
        ("good", "completed"),
        ("bad", "failed"),
        ("good", "completed"),
    ]
    assert [run.job for run in rig.engine.history(job="bad")] == ["bad"]
    assert [run.job for run in rig.engine.history(state="completed")] == ["good", "good"]
    assert [run.job for run in rig.engine.history(state=RunState.FAILED)] == ["bad"]
    assert len(rig.engine.history(limit=2)) == 2
    assert rig.engine.history(limit=0) == []
    assert rig.engine.history(job="good", state="failed") == []
    with pytest.raises(SchedulerException, match="unknown run state 'done'"):
        rig.engine.history(state="done")


def test_the_history_is_bounded() -> None:
    with Rig(history_limit=3) as rig:
        rig.engine.add_job("job", [[rig.command("ok", lambda: 1)]])
        runs = [rig.engine.run_now("job") for _ in range(5)]
        assert all(run.wait(WAIT) for run in runs)
        assert wait_until(lambda: not rig.job("job")["running"])
        kept = rig.engine.history(limit=100)
        assert len(kept) == 3
        assert {run.job for run in kept} == {"job"}


def test_the_history_keeps_the_records_of_a_removed_job(rig: Rig) -> None:
    rig.engine.add_job("job", [[rig.command("ok", lambda: 1)]])
    run = rig.engine.run_now("job")
    assert run.wait(WAIT)
    rig.engine.remove("job")
    assert rig.engine.history(job="job") == [run]


@pytest.mark.parametrize("limit", [0, -1, True, "10"])
def test_a_history_needs_room_for_one_record(limit: Any) -> None:
    with pytest.raises(SchedulerException, match="history limit"):
        RunHistory(limit)
    with pytest.raises(SchedulerException, match="history limit"):
        Scheduler(history_limit=limit, autostart=False)


def test_run_history_by_itself() -> None:
    history = RunHistory(2)
    runs = [JobRun(f"run-{index}", "job", TriggerKind.MANUAL, START) for index in range(3)]
    for run in runs:
        history.add(run)
    assert len(history) == 2
    assert history.query() == [runs[2], runs[1]]
    history.clear()
    assert history.query() == []


def test_the_scheduler_exception_is_a_file_automation_exception() -> None:
    assert issubclass(SchedulerException, FileAutomationException)
    assert manager.SchedulerException is SchedulerException


class _Deploy(Event):
    """A stand-in for an event some webhook handler publishes."""

    type = "deploy.finished"
