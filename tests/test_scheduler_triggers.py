"""The scheduler's triggers: cron with a time zone, file events, events on the bus."""

# pylint: disable=inconsistent-return-statements  # the other branch raises, or no test reaches it
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import zoneinfo
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler

from automation_file.events import Event, PipelineFailed, Severity
from automation_file.scheduler import (
    CronException,
    CronExpression,
    CronTrigger,
    EventTrigger,
    FileTrigger,
    PipelineTrigger,
    RunState,
    SchedulerException,
    Trigger,
    TriggerKind,
    cron,
    resolve_timezone,
    trigger_from_dict,
)
from automation_file.scheduler.triggers import as_triggers
from automation_file.trigger import manager as watch_manager
from automation_file.trigger.manager import FileWatcher, TriggerException
from tests.scheduler_kit import START, WAIT, Rig, wait_until

UTC = timezone.utc


@pytest.fixture
def rig() -> Iterator[Rig]:
    with Rig() as made:
        yield made


def zone(name: str) -> zoneinfo.ZoneInfo:
    """Return the zone ``name``, or skip the test where no zone data is installed."""
    try:
        return zoneinfo.ZoneInfo(name)
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip(f"no IANA zone data for {name} (install tzdata)")


def minutes(start: datetime, count: int) -> list[datetime]:
    return [start + timedelta(minutes=offset) for offset in range(count)]


def fired_at(trigger: CronTrigger, start: datetime, count: int) -> list[str]:
    """The UTC minutes, as ``HH:MM``, at which ``trigger`` is due from ``start`` on."""
    return [moment.strftime("%H:%M") for moment in minutes(start, count) if trigger.due(moment)]


class _Deploy(Event):
    type = "deploy.finished"


# ---------------------------------------------------------------------- time zones


def test_utc_needs_no_zone_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(key: str) -> None:
        raise zoneinfo.ZoneInfoNotFoundError(key)

    monkeypatch.setattr(cron.zoneinfo, "ZoneInfo", missing)
    assert resolve_timezone("UTC") is UTC
    assert resolve_timezone(" utc ") is UTC
    assert CronTrigger("0 2 * * *", "UTC").zone is UTC


def test_a_zone_without_data_says_to_install_tzdata(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(key: str) -> None:
        raise zoneinfo.ZoneInfoNotFoundError(key)

    monkeypatch.setattr(cron.zoneinfo, "ZoneInfo", missing)
    with pytest.raises(CronException, match=r"unknown time zone 'Asia/Taipei'.*tzdata"):
        resolve_timezone("Asia/Taipei")
    with pytest.raises(CronException, match="tzdata"):
        CronTrigger("0 2 * * *", "Asia/Taipei")


def test_no_time_zone_stays_none() -> None:
    assert resolve_timezone(None) is None
    assert CronTrigger("0 2 * * *").zone is None


@pytest.mark.parametrize("name", ["", "   ", 8, "Not/AZone", "../etc/passwd", "/etc/localtime"])
def test_a_name_that_is_no_time_zone_is_refused(name: Any) -> None:
    with pytest.raises(CronException):
        resolve_timezone(name)


def test_a_cron_trigger_is_read_in_its_time_zone() -> None:
    zone("Asia/Taipei")
    trigger = CronTrigger("0 2 * * *", "Asia/Taipei")
    assert trigger.due(datetime(2026, 10, 7, 18, 0, tzinfo=UTC)) is True
    assert trigger.due(datetime(2026, 10, 8, 2, 0, tzinfo=UTC)) is False
    moment = trigger.moment(datetime(2026, 10, 7, 18, 0, tzinfo=UTC))
    assert moment.isoformat() == "2026-10-08T02:00:00+08:00"


def test_a_cron_trigger_without_a_zone_is_read_in_local_time() -> None:
    local = datetime(2026, 4, 21, 9, 30)
    instant = local.astimezone(UTC)
    assert CronTrigger("30 9 * * *").due(instant) is True
    assert CronTrigger("31 9 * * *").due(instant) is False
    assert CronTrigger("30 9 * * *").moment(instant) == local


def test_a_cron_trigger_keeps_its_expression_and_zone() -> None:
    trigger = CronTrigger("  */5 * * * *  ", " UTC ")
    assert (trigger.cron, trigger.timezone) == ("*/5 * * * *", "UTC")
    assert trigger.expression == CronExpression.parse("*/5 * * * *")
    assert trigger.kind is TriggerKind.CRON
    assert trigger == CronTrigger("*/5 * * * *", "UTC")
    assert trigger.to_dict() == {"kind": "cron", "cron": "*/5 * * * *", "timezone": "UTC"}


@pytest.mark.parametrize("expression", ["not a cron", "", None, 5])
def test_a_cron_trigger_refuses_a_bad_expression(expression: Any) -> None:
    with pytest.raises(CronException):
        CronTrigger(expression)


def test_every_hour_tells_a_wildcard_hour_field() -> None:
    assert CronExpression.parse("30 * * * *").every_hour is True
    assert CronExpression.parse("30 0-23 * * *").every_hour is True
    assert CronExpression.parse("30 1 * * *").every_hour is False
    assert CronExpression.parse("30 */2 * * *").every_hour is False


def test_a_local_time_that_does_not_exist_is_not_fired() -> None:
    zone("America/New_York")
    # 2026-03-08: the clocks go from 01:59 EST (06:59 UTC) straight to 03:00 EDT (07:00 UTC).
    start = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
    assert fired_at(CronTrigger("30 2 * * *", "America/New_York"), start, 240) == []
    assert fired_at(CronTrigger("30 1 * * *", "America/New_York"), start, 240) == ["06:30"]
    assert fired_at(CronTrigger("30 3 * * *", "America/New_York"), start, 240) == ["07:30"]


def test_a_local_time_that_occurs_twice_fires_once() -> None:
    zone("America/New_York")
    # 2026-11-01: 01:30 happens at 05:30 UTC (EDT) and again at 06:30 UTC (EST).
    start = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    assert fired_at(CronTrigger("30 1 * * *", "America/New_York"), start, 240) == ["05:30"]
    assert fired_at(CronTrigger("30 0-2 * * *", "America/New_York"), start, 240) == [
        "04:30",
        "05:30",
        "07:30",
    ]


def test_a_job_that_runs_every_hour_keeps_firing_through_the_repeated_hour() -> None:
    zone("America/New_York")
    start = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    assert fired_at(CronTrigger("30 * * * *", "America/New_York"), start, 240) == [
        "04:30",
        "05:30",
        "06:30",
        "07:30",
    ]
    every_quarter = fired_at(CronTrigger("*/15 * * * *", "America/New_York"), start, 240)
    assert len(every_quarter) == 16


def test_the_scheduler_fires_a_zoned_job_at_its_local_minute(rig: Rig) -> None:
    zone("Asia/Taipei")
    calls: list[int] = []
    rig.engine.add(
        "nightly",
        "0 2 * * *",
        [[rig.command("count", lambda: calls.append(1))]],
        timezone="Asia/Taipei",
    )
    assert rig.engine.tick(datetime(2026, 10, 7, 17, 59, tzinfo=UTC)) == []
    (run,) = rig.engine.tick(datetime(2026, 10, 7, 18, 0, 20, tzinfo=UTC))
    assert run.wait(WAIT)
    assert (run.trigger, run.state) == (TriggerKind.CRON, RunState.COMPLETED)
    assert run.scheduled_at == datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
    assert run.detail == {"cron": "0 2 * * *", "timezone": "Asia/Taipei"}
    snapshot = rig.job("nightly")
    assert snapshot["last_run"] == "2026-10-08T02:00:00+08:00"
    assert (snapshot["cron"], snapshot["timezone"]) == ("0 2 * * *", "Asia/Taipei")
    assert calls == [1]


def test_the_scheduler_refuses_a_job_in_an_unknown_zone(rig: Rig) -> None:
    with pytest.raises(CronException):
        rig.engine.add("job", "0 2 * * *", [["FA_schedule_list"]], timezone="Not/AZone")
    assert rig.engine.list() == []


# ---------------------------------------------------------------------- the tick


def test_a_minute_is_fired_once_however_often_it_is_ticked(rig: Rig) -> None:
    calls: list[int] = []
    rig.engine.add(
        "job", "* * * * *", [[rig.command("count", lambda: calls.append(1))]], timezone="UTC"
    )
    (first,) = rig.tick()
    assert first.wait(WAIT)
    assert rig.tick(seconds=1) == []
    assert rig.tick(seconds=58) == []
    (second,) = rig.tick(seconds=1)
    assert second.wait(WAIT)
    assert second.scheduled_at == START + timedelta(minutes=1)
    assert calls == [1, 1]


def test_a_job_without_a_zone_keeps_a_naive_local_last_run(rig: Rig) -> None:
    rig.engine.add("job", "* * * * *", [[rig.command("ok", lambda: 1)]])
    (run,) = rig.tick(seconds=30)
    assert run.wait(WAIT)
    expected = START.astimezone().replace(tzinfo=None)
    assert rig.job("job")["last_run"] == expected.isoformat()
    assert run.detail == {"cron": "* * * * *", "timezone": None}


def test_tick_takes_a_naive_time_as_local_time(rig: Rig) -> None:
    rig.engine.add("job", "30 9 * * *", [[rig.command("ok", lambda: 1)]])
    assert rig.engine.tick(datetime(2026, 4, 21, 9, 29)) == []
    (run,) = rig.engine.tick(datetime(2026, 4, 21, 9, 30))
    assert run.wait(WAIT)
    assert run.scheduled_at == datetime(2026, 4, 21, 9, 30).astimezone(UTC)


def test_two_cron_triggers_due_in_one_minute_fire_the_job_once(rig: Rig) -> None:
    rig.engine.add_job(
        "job",
        [[rig.command("ok", lambda: 1)]],
        triggers=[CronTrigger("* * * * *", "UTC"), CronTrigger("0 2 * * *", "UTC")],
    )
    assert len(rig.tick()) == 1


# ---------------------------------------------------------------------- events


def test_an_event_trigger_fires_on_a_type_name(rig: Rig) -> None:
    rig.engine.add_job(
        "job", [[rig.command("ok", lambda: 1)]], triggers=EventTrigger(types="deploy.finished")
    )
    event = _Deploy(source="webhook", subject="release 1.4")
    rig.bus.publish(event)
    (run,) = rig.runs("job")
    assert run.wait(WAIT)
    assert (run.trigger, run.state) == (TriggerKind.EVENT, RunState.COMPLETED)
    assert run.detail == {
        "event_type": "deploy.finished",
        "event_id": event.id,
        "source": "webhook",
        "subject": "release 1.4",
        "correlation_id": event.correlation_id,
    }
    assert run.correlation_id != event.correlation_id


@pytest.mark.parametrize(
    ("trigger", "fires"),
    [
        (EventTrigger(types="deploy.*"), True),
        (EventTrigger(types=_Deploy), True),
        (EventTrigger(types=["task.failed", "deploy.finished"]), True),
        (EventTrigger(types="task.failed"), False),
        (EventTrigger(sources="webhook"), True),
        (EventTrigger(sources=["cli", "mcp"]), False),
        (EventTrigger(types="deploy.finished", sources="webhook"), True),
        (EventTrigger(types="deploy.finished", sources="cli"), False),
        (EventTrigger(types="deploy.finished", min_severity="warning"), True),
        (EventTrigger(types="deploy.finished", min_severity=Severity.ERROR), False),
    ],
)
def test_an_event_trigger_matches_by_type_source_and_severity(
    rig: Rig, trigger: EventTrigger, fires: bool
) -> None:
    rig.engine.add_job("job", [[rig.command("ok", lambda: 1)]], triggers=trigger)
    rig.bus.publish(_Deploy(source="webhook", severity=Severity.WARNING))
    assert len(rig.runs("job")) == int(fires)
    assert all(run.wait(WAIT) for run in rig.runs("job"))


def test_an_event_trigger_stops_with_its_job(rig: Rig) -> None:
    rig.engine.add_job("job", [["FA_schedule_list"]], triggers=EventTrigger(types="deploy.*"))
    rig.engine.remove("job")
    assert rig.bus.publish(_Deploy()) == 1  # only the rig's own collector is left
    assert rig.runs("job") == []


def test_a_job_does_not_fire_on_the_events_of_its_own_run(rig: Rig) -> None:
    def boom() -> None:
        raise ValueError("no")

    rig.engine.add_job(
        "watcher",
        [[rig.command("boom", boom)]],
        triggers=EventTrigger(types="scheduler.error"),
        allow_overlap=True,
    )
    rig.engine.add_job("other", [[rig.command("boom2", boom)]])
    first = rig.engine.run_now("watcher")
    assert first.wait(WAIT)
    assert rig.idle("watcher")
    assert [run.trigger.value for run in rig.runs("watcher")] == ["manual"]
    # Another job's failure does fire it, and its own failure then stops there.
    assert rig.engine.run_now("other").wait(WAIT)
    assert wait_until(lambda: len(rig.runs("watcher")) == 2)
    assert all(run.wait(WAIT) for run in rig.runs("watcher"))
    assert rig.idle("watcher")
    assert [run.trigger.value for run in rig.runs("watcher")] == ["event", "manual"]
    assert len(rig.errors()) == 3


def test_a_job_does_not_fire_on_its_own_timeout(rig: Rig) -> None:
    action, gate = rig.gate()
    rig.engine.add_job(
        "watcher",
        [[action]],
        triggers=EventTrigger(types="scheduler.error"),
        allow_overlap=True,
        timeout=30,
    )
    run = rig.engine.run_now("watcher")
    gate.await_entry()
    rig.tick(seconds=30)
    assert run.state is RunState.TIMEOUT
    assert len(rig.errors()) == 1
    assert rig.runs("watcher") == [run]


def test_two_jobs_that_fire_each_other_stop_after_a_chain_of_sixteen_runs(rig: Rig) -> None:
    def boom() -> None:
        raise ValueError("no")

    action = rig.command("boom", boom)
    for name in ("ping", "pong"):
        rig.engine.add_job(
            name, [[action]], triggers=EventTrigger(types="scheduler.error"), allow_overlap=True
        )
    rig.engine.run_now("ping")
    assert wait_until(lambda: bool(rig.engine.history(state="skipped")))
    assert rig.idle("ping") and rig.idle("pong")
    records = rig.engine.history(limit=100)
    assert [run.state.value for run in records] == ["skipped"] + ["failed"] * 16
    assert [run.job for run in reversed(records)] == ["ping", "pong"] * 8 + ["ping"]
    assert (records[0].reason, records[0].trigger) == ("chain", TriggerKind.EVENT)
    assert len(rig.errors()) == 16
    assert rig.job("ping")["skipped"] == 1
    # A firing no run caused starts a chain of its own.
    rig.engine.remove("pong")
    assert rig.engine.run_now("ping").wait(WAIT)
    assert len(rig.engine.history(limit=100)) == 18


def test_an_action_that_publishes_an_event_does_not_fire_its_own_job(rig: Rig) -> None:
    rig.engine.add_job(
        "job",
        [[rig.command("emit", lambda: rig.bus.publish(_Deploy(source="job")))]],
        triggers=EventTrigger(types="deploy.finished"),
        allow_overlap=True,
    )
    run = rig.engine.run_now("job")
    assert run.wait(WAIT)
    assert rig.idle("job")
    assert len(rig.runs("job")) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"types": ()},
        {"types": [""]},
        {"types": [5]},
        {"types": int},
        {"sources": [" "]},
        {"types": "task.failed", "min_severity": "fatal"},
    ],
)
def test_an_event_trigger_refuses_what_it_cannot_match(arguments: dict[str, Any]) -> None:
    with pytest.raises(SchedulerException, match="event trigger"):
        EventTrigger(**arguments)


def test_an_event_trigger_as_a_mapping() -> None:
    trigger = EventTrigger(
        types=[PipelineFailed, "task.*"], sources="pipeline", min_severity="error"
    )
    assert trigger.to_dict() == {
        "kind": "event",
        "types": ["pipeline.failed", "task.*"],
        "sources": ["pipeline"],
        "min_severity": "error",
    }
    assert trigger.kind is TriggerKind.EVENT
    assert trigger_from_dict(trigger.to_dict()) == EventTrigger(
        types=("pipeline.failed", "task.*"), sources=("pipeline",), min_severity=Severity.ERROR
    )


# ---------------------------------------------------------------------- files


class _Observer:
    """A stand-in for watchdog's observer: it records what it was told and fires nothing."""

    def __init__(self, made: list[_Observer]) -> None:
        self.handler: FileSystemEventHandler | None = None
        self.path = ""
        self.recursive = False
        self.alive = False
        self.daemon = False
        made.append(self)

    def schedule(self, handler: FileSystemEventHandler, path: str, recursive: bool) -> None:
        self.handler, self.path, self.recursive = handler, path, recursive

    def start(self) -> None:
        self.alive = True

    def stop(self) -> None:
        self.alive = False

    def join(self, timeout: float | None = None) -> None:
        self.joined_with = timeout  # pylint: disable=attribute-defined-outside-init  # kept for the assertion

    def is_alive(self) -> bool:
        return self.alive

    def emit(self, event: Any) -> None:
        assert self.handler is not None
        self.handler.on_any_event(event)


@pytest.fixture
def observers(monkeypatch: pytest.MonkeyPatch) -> list[_Observer]:
    """Every observer the watchers of this test made, in order."""
    made: list[_Observer] = []
    monkeypatch.setattr(watch_manager, "Observer", lambda: _Observer(made))
    return made


def test_a_file_trigger_fires_its_job_for_a_matching_event(
    rig: Rig, observers: list[_Observer], tmp_path: Path
) -> None:
    calls: list[int] = []
    snapshot = rig.engine.add_job(
        "inbox",
        [[rig.command("count", lambda: calls.append(1))]],
        triggers=FileTrigger(str(tmp_path), events=["created"], recursive=False),
    )
    assert snapshot["triggers"] == [
        {"kind": "file", "path": str(tmp_path), "events": ["created"], "recursive": False}
    ]
    (observer,) = observers
    assert (observer.alive, observer.recursive) == (True, False)
    assert Path(observer.path) == tmp_path.resolve()
    target = str(tmp_path / "report.csv")
    observer.emit(FileModifiedEvent(target))
    assert rig.runs("inbox") == []
    observer.emit(FileCreatedEvent(target))
    (run,) = rig.runs("inbox")
    assert run.wait(WAIT)
    assert (run.trigger, run.state) == (TriggerKind.FILE, RunState.COMPLETED)
    assert run.detail == {"path": target, "event": "created"}
    assert calls == [1]


def test_a_file_trigger_stops_watching_when_its_job_is_removed(
    rig: Rig, observers: list[_Observer], tmp_path: Path
) -> None:
    rig.engine.add_job("a", [["FA_schedule_list"]], triggers=FileTrigger(str(tmp_path)))
    rig.engine.add_job("b", [["FA_schedule_list"]], triggers=FileTrigger(str(tmp_path)))
    rig.engine.remove("a")
    assert [observer.alive for observer in observers] == [False, True]
    rig.engine.shutdown()
    assert [observer.alive for observer in observers] == [False, False]
    assert [job["name"] for job in rig.engine.list()] == ["b"]


def test_a_file_trigger_on_a_missing_path_registers_nothing(rig: Rig, tmp_path: Path) -> None:
    with pytest.raises(TriggerException, match="watch path does not exist"):
        rig.engine.add_job(
            "job", [["FA_schedule_list"]], triggers=FileTrigger(str(tmp_path / "nope"))
        )
    assert "job" not in rig.engine
    assert rig.engine.list() == []


def test_a_job_whose_second_trigger_fails_leaves_nothing_armed(
    rig: Rig, observers: list[_Observer], tmp_path: Path
) -> None:
    with pytest.raises(TriggerException, match="unsupported event types"):
        rig.engine.add_job(
            "job",
            [["FA_schedule_list"]],
            triggers=[
                EventTrigger(types="deploy.finished"),
                FileTrigger(str(tmp_path)),
                FileTrigger(str(tmp_path), events=["exploded"]),
            ],
        )
    assert "job" not in rig.engine
    assert [observer.alive for observer in observers] == [False]
    assert rig.bus.publish(_Deploy()) == 1
    rig.engine.add_job("job", [["FA_schedule_list"]])


def test_a_file_trigger_with_a_real_observer_starts_and_stops(rig: Rig, tmp_path: Path) -> None:
    rig.engine.add_job("job", [["FA_schedule_list"]], triggers=FileTrigger(tmp_path))
    assert rig.job("job")["triggers"][0]["events"] == ["created", "modified"]
    rig.engine.remove("job")


def test_a_file_trigger_normalises_its_arguments(tmp_path: Path) -> None:
    trigger = FileTrigger(tmp_path, events="deleted", recursive=0)
    assert (trigger.path, trigger.events, trigger.recursive) == (str(tmp_path), ("deleted",), False)
    assert FileTrigger(str(tmp_path), events=()).events == ("created", "modified")
    assert trigger.kind is TriggerKind.FILE
    with pytest.raises(SchedulerException, match="file trigger"):
        FileTrigger("")
    with pytest.raises(SchedulerException, match="file trigger"):
        FileTrigger(None)


def test_a_watcher_with_a_callback_runs_no_action_list(
    observers: list[_Observer], tmp_path: Path
) -> None:
    seen: list[tuple[str, str]] = []
    watcher = FileWatcher(
        "unit", str(tmp_path), [["FA_does_not_exist"]], on_event=lambda *call: seen.append(call)
    )
    watcher.start()
    (observer,) = observers
    observer.emit(FileCreatedEvent(str(tmp_path / "a.txt")))
    observer.emit(FileCreatedEvent(bytes(tmp_path / "b.txt")))
    watcher.stop()
    assert seen == [("created", str(tmp_path / "a.txt")), ("created", str(tmp_path / "b.txt"))]


def test_a_failing_watcher_callback_does_not_reach_the_observer(
    observers: list[_Observer], tmp_path: Path
) -> None:
    def refuse(_kind: str, _path: str) -> None:
        raise SchedulerException("no such job")

    watcher = FileWatcher("unit", str(tmp_path), [], on_event=refuse)
    watcher.start()
    observers[0].emit(FileCreatedEvent(str(tmp_path / "a.txt")))
    watcher.stop()


# ---------------------------------------------------------------------- mappings


def test_every_trigger_turns_into_a_mapping_and_back(tmp_path: Path) -> None:
    triggers: list[Trigger] = [
        CronTrigger("0 2 * * *", "UTC"),
        CronTrigger("*/5 * * * *"),
        FileTrigger(str(tmp_path), events=("created", "moved"), recursive=False),
        EventTrigger(types=("task.failed",), sources=("pipeline",), min_severity=Severity.ERROR),
        PipelineTrigger("daily-report", "always"),
    ]
    for trigger in triggers:
        assert trigger_from_dict(trigger.to_dict()) == trigger
    assert as_triggers([trigger.to_dict() for trigger in triggers]) == tuple(triggers)


def test_as_triggers_takes_one_or_many() -> None:
    cron_trigger = CronTrigger("0 2 * * *")
    assert as_triggers(None) == ()
    assert as_triggers(cron_trigger) == (cron_trigger,)
    assert as_triggers({"kind": "cron", "cron": "0 2 * * *"}) == (cron_trigger,)
    assert as_triggers((cron_trigger, {"kind": "pipeline", "pipeline": "daily"})) == (
        cron_trigger,
        PipelineTrigger("daily"),
    )
    for wrong in ("0 2 * * *", 5):
        with pytest.raises(SchedulerException, match="triggers"):
            as_triggers(wrong)


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("cron", "expected a mapping"),
        ({}, "unknown kind None"),
        ({"kind": "hourly"}, "unknown kind 'hourly'"),
        ({"kind": "manual"}, "'manual' needs no trigger"),
        ({"kind": "cron"}, "'cron' is required"),
        ({"kind": "file"}, "'path' is required"),
        ({"kind": "pipeline"}, "'pipeline' is required"),
        ({"kind": "cron", "cron": "0 2 * * *", "tz": "UTC"}, "unknown key tz"),
        ({"kind": "event"}, "at least one type or one source"),
        ({"kind": "pipeline", "pipeline": "daily", "when": "sometimes"}, "when is one of"),
        ({"kind": "pipeline", "pipeline": " "}, "expected a pipeline name"),
    ],
)
def test_a_trigger_mapping_that_is_wrong_is_refused(spec: Any, message: str) -> None:
    with pytest.raises(SchedulerException, match=message):
        trigger_from_dict(spec)


def test_a_bad_cron_in_a_mapping_is_a_cron_exception() -> None:
    with pytest.raises(CronException):
        trigger_from_dict({"kind": "cron", "cron": "61 * * * *"})
