"""The scheduler's own thread: starting, ticking, shutting down, and arming triggers again."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from automation_file.events import Event
from automation_file.scheduler import (
    CronExpression,
    EventTrigger,
    FileTrigger,
    RunState,
    ScheduledJob,
    Scheduler,
    SchedulerException,
    TriggerKind,
)
from tests.scheduler_kit import WAIT, Rig, wait_until

EVERY_MINUTE = "* * * * *"
LOOP = "fa-scheduler"


class _Deploy(Event):
    type = "deploy.finished"


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the background thread tick a hundred times a second."""
    monkeypatch.setattr(Scheduler, "_TICK_SECONDS", 0.01)


@pytest.fixture
def rig() -> Iterator[Rig]:
    with Rig() as made:
        yield made


def loops() -> set[threading.Thread]:
    return {thread for thread in threading.enumerate() if thread.name == LOOP}


def test_the_background_thread_fires_what_is_due(fast: None) -> None:
    before = loops()
    with Rig(autostart=True) as rig:
        calls: list[int] = []
        rig.engine.add(
            "job", EVERY_MINUTE, [[rig.command("count", lambda: calls.append(1))]], timezone="UTC"
        )
        (thread,) = loops() - before
        assert thread.daemon is True
        assert wait_until(lambda: calls == [1])
        rig.clock.advance(seconds=59)
        assert not wait_until(lambda: len(calls) > 1, timeout=0.1)
        rig.clock.advance(seconds=1)
        assert wait_until(lambda: calls == [1, 1])
        rig.engine.shutdown()
        assert thread.is_alive() is False
        rig.clock.advance(minutes=1)
        assert not wait_until(lambda: len(calls) > 2, timeout=0.1)


def test_the_background_thread_notices_a_timeout(fast: None) -> None:
    with Rig(autostart=True) as rig:
        action, gate = rig.gate()
        rig.engine.add_job("job", [[action]], timeout=30)
        run = rig.engine.run_now("job")
        gate.await_entry()
        rig.clock.advance(seconds=30)
        assert run.wait(WAIT)
        assert run.state is RunState.TIMEOUT


def test_a_tick_that_raises_does_not_end_the_thread(
    fast: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks: list[int] = []

    def flaky(_self: Scheduler, _now: datetime | None = None) -> list[Any]:
        ticks.append(1)
        if len(ticks) == 1:
            raise RuntimeError("one bad tick")
        return []

    monkeypatch.setattr(Scheduler, "tick", flaky)
    engine = Scheduler()
    try:
        engine.start()
        assert wait_until(lambda: len(ticks) >= 3)
    finally:
        engine.shutdown()


def test_a_scheduler_without_autostart_has_no_thread_until_it_is_started(rig: Rig) -> None:
    before = loops()
    rig.engine.add("job", EVERY_MINUTE, [[rig.command("ok", lambda: 1)]], timezone="UTC")
    assert loops() == before
    rig.engine.start()
    rig.engine.start()
    assert len(loops() - before) == 1
    rig.engine.shutdown()
    assert loops() - before == set()


def test_adding_a_job_starts_the_thread_again_after_a_shutdown(fast: None) -> None:
    before = loops()
    with Rig(autostart=True) as rig:
        action = rig.command("ok", lambda: 1)
        rig.engine.add_job("first", [[action]])
        (first,) = loops() - before
        rig.engine.shutdown()
        assert first.is_alive() is False
        rig.engine.add_job("second", [[action]])
        (second,) = loops() - before
        assert second is not first and second.daemon is True


def test_shutdown_stops_the_bus_subscriptions_and_start_brings_them_back(rig: Rig) -> None:
    rig.engine.add_job(
        "job", [[rig.command("ok", lambda: 1)]], triggers=EventTrigger(types="deploy.finished")
    )
    assert rig.bus.publish(_Deploy()) == 2
    assert rig.runs("job")[0].wait(WAIT)
    rig.engine.shutdown()
    assert rig.bus.publish(_Deploy()) == 1  # the rig's collector only
    assert len(rig.runs("job")) == 1
    assert [job["name"] for job in rig.engine.list()] == ["job"]
    rig.engine.start()
    assert rig.bus.publish(_Deploy()) == 2
    assert wait_until(lambda: len(rig.runs("job")) == 2)
    assert all(run.wait(WAIT) for run in rig.runs("job"))
    rig.engine.start()
    assert rig.bus.publish(_Deploy()) == 2


def test_remove_all_stops_every_trigger(rig: Rig, tmp_path: Path) -> None:
    before = set(threading.enumerate())
    rig.engine.add_job("a", [["FA_schedule_list"]], triggers=EventTrigger(types="deploy.*"))
    rig.engine.add_job("b", [["FA_schedule_list"]], triggers=FileTrigger(str(tmp_path)))
    watching = set(threading.enumerate()) - before
    assert watching
    assert [job["name"] for job in rig.engine.remove_all()] == ["a", "b"]
    assert rig.bus.publish(_Deploy()) == 1
    assert wait_until(lambda: not any(thread.is_alive() for thread in watching))
    assert rig.engine.list() == []


def test_a_trigger_that_cannot_be_armed_again_is_logged_and_the_rest_go_on(
    rig: Rig, tmp_path: Path
) -> None:
    watched = tmp_path / "inbox"
    watched.mkdir()
    rig.engine.add_job("files", [["FA_schedule_list"]], triggers=FileTrigger(str(watched)))
    rig.engine.add_job(
        "events",
        [[rig.command("ok", lambda: 1)]],
        triggers=EventTrigger(types="deploy.finished"),
    )
    rig.engine.shutdown()
    watched.rmdir()
    rig.engine.start()
    assert rig.bus.publish(_Deploy()) == 2
    assert wait_until(lambda: len(rig.runs("events")) == 1)
    assert rig.runs("events")[0].wait(WAIT)
    assert [job["name"] for job in rig.engine.list()] == ["files", "events"]


def test_a_removed_job_is_not_fired_by_a_trigger_that_is_still_in_flight(rig: Rig) -> None:
    rig.engine.add_job("job", [["FA_schedule_list"]])
    rig.engine.remove("job")
    # pylint: disable-next=protected-access  # what a trigger calls when its moment has come
    assert rig.engine._fire("job", TriggerKind.EVENT, {}) is None
    with pytest.raises(SchedulerException, match="no such job: job"):
        rig.engine.remove("job")


def test_dispatch_keeps_accepting_a_bare_job_and_a_naive_moment(rig: Rig) -> None:
    job = ScheduledJob(
        name="bare",
        cron=CronExpression.parse(EVERY_MINUTE),
        action_list=[[rig.command("ok", lambda: 1)]],
    )
    assert [trigger.to_dict() for trigger in job.triggers] == [
        {"kind": "cron", "cron": EVERY_MINUTE, "timezone": None}
    ]
    odd = CronExpression(
        frozenset({0}), frozenset({2}), frozenset({1}), frozenset({1}), frozenset({1}), "nightly"
    )
    assert ScheduledJob(name="odd", cron=odd, action_list=[]).cron is odd
    moment = datetime(2026, 4, 21, 12, 0)
    # pylint: disable-next=protected-access  # the entry point the old tests and callers use
    run = rig.engine._dispatch(job, moment)
    assert run.wait(WAIT)
    assert (job.runs, job.last_run, job.running) == (1, moment, False)
    assert run.scheduled_at == moment.astimezone(run.scheduled_at.tzinfo)
    assert run.trigger == "cron"
