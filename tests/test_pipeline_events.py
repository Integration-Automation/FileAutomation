"""What a pipeline run publishes: the events, their order, payload and correlation ID."""

from __future__ import annotations

import threading
import time

import pytest

from automation_file.core.progress import CancellationToken, CancelledException
from automation_file.events import (
    PAYLOAD_KEYS,
    Event,
    EventBus,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    Severity,
    TaskCompleted,
    TaskFailed,
    TaskStarted,
    actor_scope,
    correlation_scope,
    current_actor,
    current_correlation_id,
    event_bus,
)
from automation_file.pipeline import (
    MemoryRunStore,
    Pipeline,
    RetryPolicy,
    RunStatus,
    TaskContext,
    worker,
)

WAIT = 5.0


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def events(bus: EventBus) -> list[Event]:
    """Every event published on the test's bus, in order."""
    received: list[Event] = []
    bus.subscribe(received.append)
    return received


@pytest.fixture
def store() -> MemoryRunStore:
    return MemoryRunStore()


def summary(events: list[Event]) -> list[tuple[str, str | None, int | None, str]]:
    return [
        (
            event.type,
            event.payload.get("task"),
            event.payload.get("attempt"),
            event.payload["status"],
        )
        for event in events
    ]


def test_a_successful_run_publishes_its_events_in_order(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    pipeline = Pipeline("daily")
    pipeline.task("load", lambda ctx: 1)
    pipeline.task("report", lambda ctx: 2, depends_on=["load"])
    run = pipeline.run(store=store, bus=bus)
    assert summary(events) == [
        ("pipeline.started", None, None, "running"),
        ("task.started", "load", 1, "running"),
        ("task.completed", "load", 1, "succeeded"),
        ("task.started", "report", 1, "running"),
        ("task.completed", "report", 1, "succeeded"),
        ("pipeline.completed", None, None, "succeeded"),
    ]
    assert [type(event) for event in events] == [
        PipelineStarted,
        TaskStarted,
        TaskCompleted,
        TaskStarted,
        TaskCompleted,
        PipelineCompleted,
    ]
    assert {event.correlation_id for event in events} == {run.run_id}
    assert {event.source for event in events} == {"pipeline"}
    assert {event.severity for event in events} == {Severity.INFO}
    assert {event.actor for event in events} == {current_actor()}
    assert [event.subject for event in events] == [
        "daily running",
        "daily/load running (attempt 1)",
        "daily/load succeeded (attempt 1)",
        "daily/report running (attempt 1)",
        "daily/report succeeded (attempt 1)",
        "daily succeeded",
    ]


def test_the_payload_uses_the_shared_keys(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    def boom(_ctx: TaskContext) -> None:
        raise ValueError("boom")

    pipeline = Pipeline("payloads")
    pipeline.task("fine", lambda ctx: 1)
    pipeline.task("broken", boom, depends_on=["fine"])
    run = pipeline.run(store=store, bus=bus)
    for event in events:
        assert set(event.payload) <= set(PAYLOAD_KEYS)
        assert event.payload["pipeline"] == "payloads"
        assert event.payload["run_id"] == run.run_id
        assert isinstance(event.to_dict()["payload"], dict)
    by_type = {event.type: event for event in events}
    assert set(by_type["pipeline.started"].payload) == {"pipeline", "run_id", "status"}
    assert set(by_type["task.started"].payload) == {
        "pipeline",
        "run_id",
        "task",
        "attempt",
        "status",
    }
    completed = by_type["task.completed"].payload
    assert set(completed) == {"pipeline", "run_id", "task", "attempt", "status", "duration_ms"}
    assert completed["duration_ms"] >= 0
    failed = by_type["task.failed"]
    assert failed.payload["error"] == "ValueError: boom"
    assert failed.payload["status"] == "failed"
    assert failed.payload["duration_ms"] >= 0
    assert failed.severity is Severity.ERROR
    ended = by_type["pipeline.failed"]
    assert isinstance(ended, PipelineFailed)
    assert ended.payload["status"] == "failed"
    assert ended.payload["error"] == "did not succeed: broken"
    assert ended.payload["duration_ms"] >= 0
    assert ended.severity is Severity.ERROR
    assert "pipeline.completed" not in by_type


def test_each_attempt_has_its_own_events(
    bus: EventBus, events: list[Event], store: MemoryRunStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "pause", lambda _token, _seconds: False)

    def down(_ctx: TaskContext) -> None:
        raise ConnectionError("refused")

    pipeline = Pipeline("attempts")
    pipeline.task("down", down, retry=RetryPolicy(max_attempts=3))
    pipeline.run(store=store, bus=bus)
    assert summary(events) == [
        ("pipeline.started", None, None, "running"),
        ("task.started", "down", 1, "running"),
        ("task.failed", "down", 1, "retrying"),
        ("task.started", "down", 2, "running"),
        ("task.failed", "down", 2, "retrying"),
        ("task.started", "down", 3, "running"),
        ("task.failed", "down", 3, "failed"),
        ("pipeline.failed", None, None, "failed"),
    ]
    failures = [event for event in events if isinstance(event, TaskFailed)]
    assert [event.severity for event in failures] == [
        Severity.WARNING,  # it will be tried again
        Severity.WARNING,
        Severity.ERROR,
    ]
    assert {event.payload["error"] for event in failures} == {"ConnectionError: refused"}


def test_a_timeout_is_a_failed_task_event(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    release = threading.Event()
    pipeline = Pipeline("slow")
    pipeline.task("stuck", lambda ctx: release.wait(WAIT), timeout=0.05)
    try:
        pipeline.run(store=store, bus=bus)
    finally:
        release.set()
    assert summary(events) == [
        ("pipeline.started", None, None, "running"),
        ("task.started", "stuck", 1, "running"),
        ("task.failed", "stuck", 1, "timeout"),
        ("pipeline.failed", None, None, "failed"),
    ]
    assert events[2].payload["error"] == "TimeoutError: no result within 0.05 s"
    assert events[2].severity is Severity.ERROR


def test_a_cancelled_run_ends_with_a_warning(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    entered = threading.Event()

    def watches(ctx: TaskContext) -> None:
        entered.set()
        deadline = time.monotonic() + WAIT
        while not ctx.cancel.is_cancelled and time.monotonic() < deadline:
            time.sleep(0.002)
        ctx.cancel.raise_if_cancelled()

    pipeline = Pipeline("stopped")
    pipeline.task("first", watches)
    pipeline.task("second", lambda ctx: None, depends_on=["first"])
    run = pipeline.start(store=store, bus=bus)
    assert entered.wait(WAIT)
    run.cancel()
    assert run.wait(WAIT) is True
    assert summary(events) == [
        ("pipeline.started", None, None, "running"),
        ("task.started", "first", 1, "running"),
        ("task.failed", "first", 1, "cancelled"),
        ("pipeline.failed", None, None, "cancelled"),
    ]
    assert events[2].severity is Severity.WARNING
    assert events[2].payload["error"] == "CancelledException: operation cancelled"
    assert events[3].severity is Severity.WARNING
    assert events[3].payload["error"] == "the run was cancelled"
    assert {event.correlation_id for event in events} == {run.run_id}


def test_tasks_that_do_not_run_publish_nothing(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    def build() -> Pipeline:
        pipeline = Pipeline("quiet")
        pipeline.task("once", lambda ctx: "done", idempotency_key="once")
        pipeline.task("never", lambda ctx: None, depends_on=["once"], when="on_failure")
        pipeline.task("pruned", lambda ctx: None, depends_on=["never"])
        return pipeline

    build().run(store=store, bus=bus)
    events.clear()
    second = build().run(store=store, bus=bus)
    assert second.status is RunStatus.SUCCEEDED
    assert second.tasks["once"].reason == "idempotent"
    assert summary(events) == [
        ("pipeline.started", None, None, "running"),
        ("pipeline.completed", None, None, "succeeded"),
    ]
    events.clear()
    token = CancellationToken()
    token.cancel()
    build().run(store=store, bus=bus, cancel=token)
    assert summary(events) == [
        ("pipeline.started", None, None, "running"),
        ("pipeline.failed", None, None, "cancelled"),
    ]
    events.clear()
    build().run(dry_run=True, store=store, bus=bus)
    assert events == []


def test_a_condition_that_raises_is_reported(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    def broken(_ctx: TaskContext) -> bool:
        raise LookupError("missing")

    pipeline = Pipeline("conditions")
    pipeline.task("guarded", lambda ctx: None, when=broken)
    pipeline.run(store=store, bus=bus)
    assert summary(events) == [
        ("pipeline.started", None, None, "running"),
        ("task.failed", "guarded", 0, "failed"),
        ("pipeline.failed", None, None, "failed"),
    ]
    assert events[1].payload["error"] == "when: LookupError: missing"


def test_a_task_cancelled_on_its_own_is_reported(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    def gives_up(_ctx: TaskContext) -> None:
        raise CancelledException("transfer cancelled")

    pipeline = Pipeline("self-cancelled")
    pipeline.task("transfer", gives_up)
    pipeline.run(store=store, bus=bus)
    assert summary(events)[2] == ("task.failed", "transfer", 1, "cancelled")
    assert summary(events)[3] == ("pipeline.failed", None, None, "failed")
    assert events[3].severity is Severity.ERROR


# ---------------------------------------------------------------------- scopes


def test_worker_threads_carry_the_correlation_id_and_the_actor(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    def inspect(_ctx: TaskContext) -> dict[str, object]:
        return {
            "correlation_id": current_correlation_id(),
            "actor": current_actor(),
            "event": Event().correlation_id,  # what a storage event raised in here would carry
            "thread": threading.current_thread().name,
        }

    pipeline = Pipeline("scoped", max_workers=2)
    pipeline.task("one", inspect)
    pipeline.task("two", inspect)
    pipeline.task(
        "when", inspect, depends_on=["one"], when=lambda ctx: current_actor() == "scheduler"
    )
    with actor_scope("scheduler"), correlation_scope("an-outer-scope"):
        run = pipeline.run(store=store, bus=bus)
        assert current_correlation_id() == "an-outer-scope"  # the run's scope is closed again
    assert current_correlation_id() is None
    for task_id in ("one", "two", "when"):
        seen = run.tasks[task_id].result
        assert seen["correlation_id"] == run.run_id
        assert seen["event"] == run.run_id
        assert seen["actor"] == "scheduler"
        assert seen["thread"] == f"pipeline-scoped-{task_id}"
        assert seen["thread"] != threading.current_thread().name
    assert {event.actor for event in events} == {"scheduler"}
    assert {event.correlation_id for event in events} == {run.run_id}
    assert run.run_id != "an-outer-scope"


def test_a_background_run_keeps_the_actor_of_its_caller(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    pipeline = Pipeline("background")
    pipeline.task("who", lambda ctx: (current_actor(), current_correlation_id()))
    with actor_scope("mcp"):
        run = pipeline.start(store=store, bus=bus)
    assert run.wait(WAIT) is True
    assert run.tasks["who"].result == ("mcp", run.run_id)
    assert {event.actor for event in events} == {"mcp"}
    assert {event.correlation_id for event in events} == {run.run_id}
    assert [event.type for event in events] == [
        "pipeline.started",
        "task.started",
        "task.completed",
        "pipeline.completed",
    ]


def test_two_runs_have_two_correlation_ids(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    pipeline = Pipeline("twice")
    pipeline.task("only", lambda ctx: None)
    first = pipeline.run(store=store, bus=bus)
    second = pipeline.run(store=store, bus=bus)
    assert first.run_id != second.run_id
    assert len(first.run_id) == 32
    assert [event.correlation_id for event in events] == [first.run_id] * 4 + [second.run_id] * 4


def test_a_resumed_run_reports_under_the_same_correlation_id(
    bus: EventBus, events: list[Event], store: MemoryRunStore
) -> None:
    def build(fail: bool) -> Pipeline:
        def second(_ctx: TaskContext) -> str:
            if fail:
                raise ValueError("not yet")
            return "done"

        pipeline = Pipeline("resumed")
        pipeline.task("first", lambda ctx: "kept")
        pipeline.task("second", second, depends_on=["first"])
        return pipeline

    run = build(fail=True).run(store=store, bus=bus)
    events.clear()
    build(fail=False).resume(run.run_id, store=store, bus=bus)
    assert summary(events) == [
        ("pipeline.started", None, None, "running"),
        ("task.started", "second", 1, "running"),
        ("task.completed", "second", 1, "succeeded"),
        ("pipeline.completed", None, None, "succeeded"),
    ]
    assert {event.correlation_id for event in events} == {run.run_id}


# ---------------------------------------------------------------------- the bus


def test_without_a_bus_the_events_go_to_the_process_wide_one(store: MemoryRunStore) -> None:
    received: list[Event] = []
    subscription = event_bus.subscribe(received.append, types=["pipeline.*", "task.*"])
    try:
        pipeline = Pipeline("global-bus")
        pipeline.task("only", lambda ctx: None)
        run = pipeline.run(store=store)
    finally:
        event_bus.unsubscribe(subscription)
    mine = [event for event in received if event.correlation_id == run.run_id]
    assert [event.type for event in mine] == [
        "pipeline.started",
        "task.started",
        "task.completed",
        "pipeline.completed",
    ]
    recent = event_bus.recent(correlation_id=run.run_id)
    assert [event.type for event in reversed(recent)] == [event.type for event in mine]


def test_a_failing_subscriber_does_not_disturb_the_run(
    bus: EventBus, store: MemoryRunStore
) -> None:
    def broken(_event: Event) -> None:
        raise RuntimeError("subscriber bug")

    bus.subscribe(broken)
    pipeline = Pipeline("robust")
    pipeline.task("only", lambda ctx: "fine")
    run = pipeline.run(store=store, bus=bus)
    assert run.status is RunStatus.SUCCEEDED
    assert run.tasks["only"].result == "fine"


def test_a_subscriber_sees_the_state_the_event_announces(
    bus: EventBus, store: MemoryRunStore
) -> None:
    seen: list[tuple[str, str, str | None]] = []

    def look(event: Event) -> None:
        stored = store.get_run(event.correlation_id)
        task = event.payload.get("task")
        status = stored.tasks[task].status.value if task else stored.status.value
        seen.append((event.type, status, task))

    bus.subscribe(look)
    pipeline = Pipeline("consistent")
    pipeline.task("only", lambda ctx: "fine")
    pipeline.run(store=store, bus=bus)
    assert seen == [
        ("pipeline.started", "running", None),
        ("task.started", "running", "only"),
        ("task.completed", "succeeded", "only"),
        ("pipeline.completed", "succeeded", None),
    ]
