"""The notification router: routes, deduplication, rate limits, failures, notify_on_failure."""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=unused-argument  # a fixture is requested for its effect; a stand-in keeps the real signature
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Iterator

import pytest

from automation_file.core.action_executor import ActionExecutor
from automation_file.core.action_registry import ActionRegistry
from automation_file.events import (
    Event,
    EventBus,
    PipelineFailed,
    PipelineStarted,
    SchedulerError,
    Severity,
    StorageError,
    SystemErrorEvent,
    TaskFailed,
    actor_scope,
    correlation_scope,
    event_bus,
)
from automation_file.notify import (
    NotificationException,
    NotificationManager,
    NotificationRouter,
    NotificationSink,
    Route,
    message_for,
    notification_manager,
    notification_router,
    register_notify_ops,
)
from automation_file.notify.manager import failure_event, notify_on_failure


class _Clock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Recorder(NotificationSink):
    def __init__(self, name: str) -> None:
        self.name = name
        self.messages: list[tuple[str, str, str]] = []

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self.messages.append((subject, body, level))


class _Broken(NotificationSink):
    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.calls = 0
        self._error = error or NotificationException("channel is down")

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self.calls += 1
        raise self._error


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def manager() -> NotificationManager:
    return NotificationManager(dedup_seconds=0.0)


@pytest.fixture
def chat(manager: NotificationManager) -> _Recorder:
    sink = _Recorder("chat")
    manager.register(sink)
    return sink


@pytest.fixture
def mail(manager: NotificationManager) -> _Recorder:
    sink = _Recorder("mail")
    manager.register(sink)
    return sink


@pytest.fixture
def router(manager: NotificationManager, bus: EventBus, clock: _Clock) -> NotificationRouter:
    return NotificationRouter(manager, bus, clock=clock)


def _failed(subject: str = "daily failed", source: str = "pipeline") -> PipelineFailed:
    return PipelineFailed(source=source, subject=subject, payload={"pipeline": "daily"})


# ---------------------------------------------------------------------- Route


def test_a_route_has_the_documented_defaults() -> None:
    route = Route("all")
    assert route.sinks == ()
    assert route.types == ()
    assert route.sources == ()
    assert route.min_severity is Severity.WARNING
    assert route.dedup_seconds == pytest.approx(300.0)
    assert route.rate_limit == 0
    assert route.rate_period == pytest.approx(60.0)


def test_a_route_is_frozen_and_normalises_its_fields() -> None:
    route = Route(
        "ops",
        sinks=["chat", "mail", "chat"],
        types="pipeline.*",
        sources=["pipeline"],
        min_severity="ERROR",
        dedup_seconds=10,
    )
    assert route.sinks == ("chat", "mail")
    assert route.types == ("pipeline.*",)
    assert route.sources == ("pipeline",)
    assert route.min_severity is Severity.ERROR
    assert isinstance(route.dedup_seconds, float)
    with pytest.raises(dataclasses.FrozenInstanceError):
        route.name = "changed"
    assert hash(route) == hash(dataclasses.replace(route))


@pytest.mark.parametrize(
    "options",
    [
        {"name": ""},
        {"name": 7},
        {"name": "r", "sinks": [""]},
        {"name": "r", "sinks": 5},
        {"name": "r", "sinks": [["nested"]]},
        {"name": "r", "types": [3]},
        {"name": "r", "types": [int]},
        {"name": "r", "sources": [None]},
        {"name": "r", "min_severity": "fatal"},
        {"name": "r", "min_severity": 2},
        {"name": "r", "dedup_seconds": -1},
        {"name": "r", "dedup_seconds": "soon"},
        {"name": "r", "dedup_seconds": float("nan")},
        {"name": "r", "rate_limit": -1},
        {"name": "r", "rate_limit": 1.5},
        {"name": "r", "rate_limit": True},
        {"name": "r", "rate_period": 0},
    ],
)
def test_a_route_rejects_bad_options(options: dict) -> None:
    with pytest.raises(NotificationException):
        Route(**options)


def test_a_route_from_a_mapping_and_back() -> None:
    options = {
        "name": "ops",
        "sinks": ["chat"],
        "types": ["task.failed", "pipeline.*"],
        "sources": ["pipeline"],
        "min_severity": "critical",
        "dedup_seconds": 0.0,
        "rate_limit": 3,
        "rate_period": 30.0,
    }
    route = Route.from_mapping(options)
    assert route.to_dict() == options
    assert Route.from_mapping(route.to_dict()) == route
    assert Route("classes", types=(TaskFailed,)).to_dict()["types"] == ["task.failed"]
    assert Route.from_mapping({"name": "bare", "sinks": None}) == Route("bare")


def test_a_mapping_with_an_unknown_option_or_no_name_is_rejected() -> None:
    with pytest.raises(NotificationException, match="colour"):
        Route.from_mapping({"name": "ops", "colour": "red"})
    with pytest.raises(NotificationException, match="name"):
        Route.from_mapping({"sinks": ["chat"]})


# ---------------------------------------------------------------------- routing


def test_routing_by_type(router: NotificationRouter, chat: _Recorder) -> None:
    router.add_route(Route("by-class", types=(TaskFailed,), dedup_seconds=0))
    router.add_route(Route("by-name", types=("storage.error",), dedup_seconds=0))
    router.add_route(Route("by-prefix", types=("pipeline.*",), dedup_seconds=0))
    assert router.handle(TaskFailed(subject="load")) == {"chat": "sent"}
    assert router.handle(StorageError(subject="s3")) == {"chat": "sent"}
    assert router.handle(_failed()) == {"chat": "sent"}
    assert router.handle(SchedulerError(subject="nightly")) == {}
    assert len(chat.messages) == 3


def test_routing_by_source(router: NotificationRouter, chat: _Recorder) -> None:
    router.add_route(Route("pipelines", sources=("pipeline",), dedup_seconds=0))
    assert router.handle(_failed(source="pipeline")) == {"chat": "sent"}
    assert router.handle(_failed(source="scheduler")) == {}
    assert len(chat.messages) == 1


def test_routing_by_severity(router: NotificationRouter, chat: _Recorder) -> None:
    router.add_route(Route("default"))
    router.add_route(Route("loud", sinks=("chat",), min_severity=Severity.CRITICAL))
    assert router.handle(PipelineStarted(subject="info is below the default")) == {}
    assert router.handle(PipelineStarted(subject="warned", severity=Severity.WARNING)) == {
        "chat": "sent"
    }
    assert router.handle(TaskFailed(subject="errored")) == {"chat": "sent"}
    assert len(chat.messages) == 2


def test_a_route_without_sinks_reaches_every_sink(
    router: NotificationRouter, chat: _Recorder, mail: _Recorder
) -> None:
    router.add_route(Route("everyone", dedup_seconds=0))
    assert router.handle(_failed()) == {"chat": "sent", "mail": "sent"}
    assert len(chat.messages) == len(mail.messages) == 1


def test_a_route_with_sinks_reaches_only_those(
    router: NotificationRouter, chat: _Recorder, mail: _Recorder
) -> None:
    router.add_route(Route("mail-only", sinks=("mail",), dedup_seconds=0))
    assert router.handle(_failed()) == {"mail": "sent"}
    assert chat.messages == []
    assert len(mail.messages) == 1


def test_a_sink_on_two_routes_gets_the_event_once(
    router: NotificationRouter, chat: _Recorder, mail: _Recorder
) -> None:
    router.add_route(Route("first", sinks=("chat",), dedup_seconds=0))
    router.add_route(Route("second", sinks=("chat", "mail"), dedup_seconds=0))
    assert router.handle(_failed()) == {"chat": "sent", "mail": "sent"}
    assert len(chat.messages) == 1
    assert len(mail.messages) == 1


def test_a_later_route_may_send_what_an_earlier_one_held_back(
    router: NotificationRouter, chat: _Recorder
) -> None:
    router.add_route(Route("quiet", sinks=("chat",), dedup_seconds=600))
    router.add_route(
        Route("critical", sinks=("chat",), min_severity=Severity.CRITICAL, dedup_seconds=0)
    )
    event = SystemErrorEvent(source="system", subject="disk gone")
    assert router.handle(event) == {"chat": "sent"}
    assert router.handle(event) == {"chat": "sent"}
    assert router.handle(TaskFailed(subject="load")) == {"chat": "sent"}
    assert router.handle(TaskFailed(subject="load")) == {"chat": "dedup"}
    assert len(chat.messages) == 3


def test_routes_are_listed_replaced_and_removed(router: NotificationRouter) -> None:
    first, second = Route("first"), Route("second", min_severity=Severity.ERROR)
    router.add_route(first)
    router.add_route(second)
    assert router.routes() == [first, second]
    replacement = Route("first", sinks=("chat",))
    router.add_route(replacement)
    assert router.routes() == [replacement, second]
    assert router.remove_route("first") is True
    assert router.remove_route("first") is False
    assert router.routes() == [second]
    with pytest.raises(NotificationException):
        router.add_route({"name": "not a route"})


def test_sync_routes_replaces_only_the_routes_of_its_origin(router: NotificationRouter) -> None:
    router.add_route(Route("by-hand"))
    assert router.sync_routes([Route("a"), Route("b")], origin="config") == 0
    assert [route.name for route in router.routes()] == ["by-hand", "a", "b"]
    changed = [Route("b", min_severity=Severity.ERROR), Route("c")]
    assert router.sync_routes(changed, origin="config") == 1
    assert [route.name for route in router.routes()] == ["by-hand", "b", "c"]
    assert router.routes()[1].min_severity is Severity.ERROR
    assert router.sync_routes([], origin="config") == 2
    assert [route.name for route in router.routes()] == ["by-hand"]
    with pytest.raises(NotificationException):
        router.sync_routes(["not a route"], origin="config")


# ---------------------------------------------------------------------- the bus


def test_start_and_stop_subscribe_on_the_bus(
    router: NotificationRouter, bus: EventBus, chat: _Recorder
) -> None:
    router.add_route(Route("all", dedup_seconds=0))
    assert router.active is False
    bus.publish(_failed("before start"))
    assert chat.messages == []
    router.start()
    router.start()
    assert router.active is True
    bus.publish(_failed("while active"))
    assert len(chat.messages) == 1
    router.stop()
    router.stop()
    assert router.active is False
    bus.publish(_failed("after stop"))
    assert len(chat.messages) == 1


def test_the_default_router_uses_the_process_wide_manager_and_bus() -> None:
    assert notification_router.manager is notification_manager
    assert notification_router.bus is event_bus
    private = NotificationRouter()
    assert private.manager is notification_manager
    assert private.bus is event_bus
    assert private.active is False


# ---------------------------------------------------------------------- the message


def test_the_message_is_built_from_the_event(router: NotificationRouter, chat: _Recorder) -> None:
    router.add_route(Route("all", dedup_seconds=0))
    with actor_scope("scheduler"), correlation_scope("run-42"):
        event = TaskFailed(
            source="pipeline",
            subject="load failed",
            payload={"pipeline": "daily", "task": "load", "error": "OSError: disk full"},
        )
    router.handle(event)
    subject, body, level = chat.messages[0]
    assert subject == "[ERROR] task.failed: load failed"
    assert level == "error"
    for line in (
        "Severity: error",
        "Type: task.failed",
        "Source: pipeline",
        "Subject: load failed",
        "Correlation ID: run-42",
        "Actor: scheduler",
        "Error: OSError: disk full",
    ):
        assert line in body.splitlines()
    assert json.loads(body.split("Event:\n", 1)[1]) == event.to_dict()


@pytest.mark.parametrize(
    "severity,level",
    [
        (Severity.INFO, "info"),
        (Severity.WARNING, "warning"),
        (Severity.ERROR, "error"),
        (Severity.CRITICAL, "error"),
    ],
)
def test_severity_maps_onto_a_level_the_sinks_accept(severity: Severity, level: str) -> None:
    message = message_for(Event(source="system", subject="something", severity=severity))
    assert message.level == level
    assert message.subject.startswith(f"[{severity.value.upper()}] event: ")


def test_a_subject_stays_one_short_line() -> None:
    message = message_for(TaskFailed(source="pipeline", subject="first line\nsecond " + "x" * 500))
    assert "\n" not in message.subject
    assert len(message.subject) <= 200
    assert message_for(TaskFailed(source="pipeline")).subject == (
        "[ERROR] task.failed: reported by pipeline"
    )


def test_a_payload_json_cannot_hold_is_still_delivered() -> None:
    message = message_for(TaskFailed(subject="odd", payload={"value": object()}))
    assert "<object object at" in message.body


# ---------------------------------------------------------------------- deduplication


def test_a_repeat_inside_the_window_is_dropped(
    router: NotificationRouter, chat: _Recorder, clock: _Clock
) -> None:
    router.add_route(Route("all", dedup_seconds=300))
    assert router.handle(_failed()) == {"chat": "sent"}
    clock.now += 299
    assert router.handle(_failed()) == {"chat": "dedup"}
    clock.now += 1
    assert router.handle(_failed()) == {"chat": "sent"}
    assert len(chat.messages) == 2


def test_dedup_compares_type_source_and_subject(
    router: NotificationRouter, chat: _Recorder
) -> None:
    router.add_route(Route("all", dedup_seconds=300))
    assert router.handle(_failed("daily failed", "pipeline")) == {"chat": "sent"}
    assert router.handle(_failed("weekly failed", "pipeline")) == {"chat": "sent"}
    assert router.handle(_failed("daily failed", "scheduler")) == {"chat": "sent"}
    assert router.handle(TaskFailed(source="pipeline", subject="daily failed")) == {"chat": "sent"}
    other_payload = PipelineFailed(source="pipeline", subject="daily failed", payload={"n": 2})
    assert router.handle(other_payload) == {"chat": "dedup"}
    assert len(chat.messages) == 4


def test_dedup_can_be_switched_off(router: NotificationRouter, chat: _Recorder) -> None:
    router.add_route(Route("all", dedup_seconds=0))
    assert [router.handle(_failed()) for _ in range(3)] == [{"chat": "sent"}] * 3
    assert len(chat.messages) == 3


def test_repeats_from_many_threads_are_sent_once(
    router: NotificationRouter, chat: _Recorder
) -> None:
    router.add_route(Route("all", dedup_seconds=300))
    workers = 8
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []

    def publish() -> None:
        barrier.wait(timeout=10)
        outcomes.append(router.handle(_failed())["chat"])

    threads = [threading.Thread(target=publish) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["dedup"] * (workers - 1) + ["sent"]
    assert len(chat.messages) == 1


def test_each_route_has_its_own_window(
    router: NotificationRouter, chat: _Recorder, mail: _Recorder, clock: _Clock
) -> None:
    router.add_route(Route("short", sinks=("chat",), dedup_seconds=10))
    router.add_route(Route("long", sinks=("mail",), dedup_seconds=100))
    router.handle(_failed())
    clock.now += 50
    assert router.handle(_failed()) == {"chat": "sent", "mail": "dedup"}


def test_replacing_a_route_forgets_what_it_sent(
    router: NotificationRouter, chat: _Recorder
) -> None:
    route = Route("all", dedup_seconds=300)
    router.add_route(route)
    router.handle(_failed())
    router.add_route(Route("all", dedup_seconds=300))
    assert router.handle(_failed()) == {"chat": "dedup"}
    router.add_route(Route("all", dedup_seconds=301))
    assert router.handle(_failed()) == {"chat": "sent"}
    assert len(chat.messages) == 2


# ---------------------------------------------------------------------- rate limiting


def test_a_route_sends_at_most_its_limit_per_period(
    router: NotificationRouter, chat: _Recorder, clock: _Clock
) -> None:
    router.add_route(Route("all", dedup_seconds=0, rate_limit=2, rate_period=60))
    assert router.handle(_failed("one")) == {"chat": "sent"}
    clock.now += 10
    assert router.handle(_failed("two")) == {"chat": "sent"}
    clock.now += 10
    assert router.handle(_failed("three")) == {"chat": "rate_limited"}
    clock.now += 40
    assert router.handle(_failed("four")) == {"chat": "sent"}
    assert router.handle(_failed("five")) == {"chat": "rate_limited"}
    assert [subject for subject, _, _ in chat.messages] == [
        "[ERROR] pipeline.failed: one",
        "[ERROR] pipeline.failed: two",
        "[ERROR] pipeline.failed: four",
    ]


def test_the_limit_is_per_sink_and_route(
    router: NotificationRouter, chat: _Recorder, mail: _Recorder
) -> None:
    router.add_route(Route("tight", sinks=("chat",), dedup_seconds=0, rate_limit=1))
    router.add_route(Route("loose", sinks=("mail",), dedup_seconds=0, rate_limit=3))
    assert router.handle(_failed("one")) == {"chat": "sent", "mail": "sent"}
    assert router.handle(_failed("two")) == {"chat": "rate_limited", "mail": "sent"}
    assert len(chat.messages) == 1
    assert len(mail.messages) == 2


def test_a_rate_limited_event_is_not_remembered_as_sent(
    router: NotificationRouter, chat: _Recorder, clock: _Clock
) -> None:
    router.add_route(Route("all", dedup_seconds=300, rate_limit=1, rate_period=60))
    assert router.handle(_failed("one")) == {"chat": "sent"}
    assert router.handle(_failed("two")) == {"chat": "rate_limited"}
    clock.now += 60
    assert router.handle(_failed("two")) == {"chat": "sent"}
    assert router.handle(_failed("one")) == {"chat": "dedup"}


def test_a_duplicate_does_not_use_up_the_limit(router: NotificationRouter, chat: _Recorder) -> None:
    router.add_route(Route("all", dedup_seconds=300, rate_limit=2, rate_period=60))
    assert router.handle(_failed("one")) == {"chat": "sent"}
    assert router.handle(_failed("one")) == {"chat": "dedup"}
    assert router.handle(_failed("one")) == {"chat": "dedup"}
    assert router.handle(_failed("two")) == {"chat": "sent"}
    assert len(chat.messages) == 2


# ---------------------------------------------------------------------- failures


def test_one_failing_sink_does_not_affect_another(
    router: NotificationRouter, manager: NotificationManager, chat: _Recorder
) -> None:
    broken = _Broken("pager")
    crashing = _Broken("legacy", RuntimeError("not a NotificationException"))
    manager.register(broken)
    manager.register(crashing)
    router.add_route(Route("all", dedup_seconds=0))
    assert router.handle(_failed()) == {
        "chat": "sent",
        "pager": "NotificationException: channel is down",
        "legacy": "RuntimeError: not a NotificationException",
    }
    assert len(chat.messages) == 1
    assert broken.calls == crashing.calls == 1


def test_a_sink_failure_is_published_as_a_system_error(
    router: NotificationRouter, manager: NotificationManager, bus: EventBus
) -> None:
    manager.register(_Broken("pager"))
    router.add_route(Route("ops", dedup_seconds=0))
    published: list[Event] = []
    bus.subscribe(published.append)
    with correlation_scope("run-9"):
        event = _failed()
    router.handle(event)
    assert len(published) == 1
    failure = published[0]
    assert isinstance(failure, SystemErrorEvent)
    assert failure.source == "notify"
    assert failure.severity is Severity.CRITICAL
    assert failure.subject == "notification sink 'pager' failed"
    assert failure.correlation_id == "run-9"
    assert failure.payload["resource"] == "pager"
    assert failure.payload["route"] == "ops"
    assert failure.payload["status"] == "error"
    assert failure.payload["error"] == "NotificationException: channel is down"
    assert failure.payload["event_type"] == "pipeline.failed"
    assert failure.payload["event_id"] == event.id


def test_a_failure_event_is_never_routed(
    router: NotificationRouter, manager: NotificationManager, bus: EventBus, chat: _Recorder
) -> None:
    broken = _Broken("pager")
    manager.register(broken)
    router.add_route(Route("everything", min_severity=Severity.INFO, dedup_seconds=0))
    router.start()
    published: list[Event] = []
    bus.subscribe(published.append)
    bus.publish(_failed())
    assert [event.type for event in published] == ["system.error", "pipeline.failed"]
    assert broken.calls == 1
    assert len(chat.messages) == 1
    failure = published[0]
    assert router.handle(failure) == {}
    assert broken.calls == 1


def test_two_routers_on_one_bus_do_not_feed_each_other(
    manager: NotificationManager, bus: EventBus, clock: _Clock
) -> None:
    broken = _Broken("pager")
    manager.register(broken)
    routers = [NotificationRouter(manager, bus, clock=clock) for _ in range(2)]
    published: list[Event] = []
    bus.subscribe(published.append)
    for router in routers:
        router.add_route(Route("everything", min_severity=Severity.INFO, dedup_seconds=0))
        router.start()
    bus.publish(_failed())
    assert broken.calls == 2
    assert sorted(event.type for event in published) == [
        "pipeline.failed",
        "system.error",
        "system.error",
    ]


def test_another_system_error_is_routed(router: NotificationRouter, chat: _Recorder) -> None:
    router.add_route(Route("all", dedup_seconds=0))
    assert router.handle(SystemErrorEvent(source="system", subject="out of disk")) == {
        "chat": "sent"
    }
    assert chat.messages[0][2] == "error"


def test_a_route_to_an_unknown_sink_reports_the_failure(
    router: NotificationRouter, bus: EventBus, chat: _Recorder
) -> None:
    router.add_route(Route("typo", sinks=("chat", "chta"), dedup_seconds=0))
    published: list[Event] = []
    bus.subscribe(published.append)
    outcomes = router.handle(_failed())
    assert outcomes["chat"] == "sent"
    assert outcomes["chta"].startswith("NotificationException: no notification sink")
    assert [event.payload["resource"] for event in published] == ["chta"]


def test_a_secret_url_never_reaches_the_outcome_or_the_event(
    router: NotificationRouter, manager: NotificationManager, bus: EventBus
) -> None:
    leak = (
        "post failed: HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries "
        "exceeded with url: /bot123456:TOPSECRET/sendMessage; see "
        "https://user:hunter2@hooks.example.com/services/T000/B000/XXXX?token=abc"
    )
    manager.register(_Broken("telegram", NotificationException(leak)))
    router.add_route(Route("all", dedup_seconds=0))
    published: list[Event] = []
    bus.subscribe(published.append)
    outcome = router.handle(_failed())["telegram"]
    reported = json.dumps(published[0].to_dict())
    for text in (outcome, reported):
        assert "TOPSECRET" not in text
        assert "hunter2" not in text
        assert "XXXX" not in text
        assert "token=abc" not in text
        assert "hooks.example.com" in text
        assert "api.telegram.org" in text


# ---------------------------------------------------------------------- notify_on_failure


@pytest.fixture
def process_wide() -> Iterator[list[Event]]:
    """The process-wide manager, router and bus, put back the way they were."""
    routes, was_active = notification_router.routes(), notification_router.active
    notification_manager.unregister_all()
    published: list[Event] = []
    subscription = event_bus.subscribe(published.append)
    yield published
    event_bus.unsubscribe(subscription)
    notification_router.stop()
    for route in notification_router.routes():
        notification_router.remove_route(route.name)
    for route in routes:
        notification_router.add_route(route)
    if was_active:
        notification_router.start()
    notification_manager.unregister_all()


def test_failure_event_for_a_scheduler_job() -> None:
    event = failure_event("scheduler[nightly]", RuntimeError("disk full"))
    assert isinstance(event, SchedulerError)
    assert event.source == "scheduler"
    assert event.severity is Severity.ERROR
    assert event.subject == "scheduler[nightly] failed"
    assert event.payload["job"] == "nightly"
    assert event.payload["status"] == "error"
    assert event.payload["error"] == "RuntimeError: disk full"


def test_failure_event_for_any_other_context() -> None:
    trigger = failure_event("trigger[inbox]", ValueError("bad action"))
    assert isinstance(trigger, SystemErrorEvent)
    assert trigger.source == "trigger"
    assert trigger.payload["trigger"] == "inbox"
    assert trigger.payload["error"] == "ValueError: bad action"
    plain = failure_event("nightly backup", OSError("no space"))
    assert isinstance(plain, SystemErrorEvent)
    assert plain.source == "system"
    assert plain.subject == "nightly backup failed"
    assert plain.payload["context"] == "nightly backup"
    odd = failure_event("error[x]", OSError("no space"))
    assert odd.payload["error"] == "OSError: no space"


def test_notify_on_failure_without_the_router_notifies_directly(
    process_wide: list[Event],
) -> None:
    sink = _Recorder("chat")
    notification_manager.register(sink)
    assert notification_router.active is False
    notify_on_failure("scheduler[router-off]", RuntimeError("disk full"))
    assert sink.messages == [
        ("automation_file: scheduler[router-off] failed", "RuntimeError('disk full')", "error")
    ]
    assert [event.type for event in process_wide] == ["scheduler.error"]
    assert process_wide[0].payload["job"] == "router-off"


def test_notify_on_failure_with_the_router_notifies_once_through_it(
    process_wide: list[Event],
) -> None:
    sink = _Recorder("chat")
    notification_manager.register(sink)
    notification_router.add_route(Route("failures", types=("scheduler.error", "system.error")))
    notification_router.start()
    notify_on_failure("scheduler[router-on]", RuntimeError("disk full"))
    notify_on_failure("trigger[router-on]", RuntimeError("disk full"))
    assert [(subject, level) for subject, _, level in sink.messages] == [
        ("[ERROR] scheduler.error: scheduler[router-on] failed", "error"),
        ("[CRITICAL] system.error: trigger[router-on] failed", "error"),
    ]
    assert "RuntimeError: disk full" in sink.messages[0][1]
    assert [event.type for event in process_wide] == ["scheduler.error", "system.error"]


def test_notify_on_failure_with_the_router_obeys_its_routes(process_wide: list[Event]) -> None:
    sink = _Recorder("chat")
    notification_manager.register(sink)
    notification_router.add_route(Route("pipelines-only", types=("pipeline.*",)))
    notification_router.start()
    notify_on_failure("scheduler[unrouted]", RuntimeError("disk full"))
    assert sink.messages == []
    assert [event.type for event in process_wide] == ["scheduler.error"]


def test_notify_on_failure_without_sinks_still_publishes(process_wide: list[Event]) -> None:
    notify_on_failure("scheduler[no-sinks]", RuntimeError("disk full"))
    assert [event.subject for event in process_wide] == ["scheduler[no-sinks] failed"]


# ---------------------------------------------------------------------- actions


def test_the_route_actions(process_wide: list[Event]) -> None:
    registry = ActionRegistry()
    register_notify_ops(registry)
    for name in ("FA_notify_route_add", "FA_notify_route_remove", "FA_notify_route_list"):
        assert name in registry
    sink = _Recorder("chat")
    notification_manager.register(sink)
    executor = ActionExecutor(registry)
    added, listed = executor.execute_action(
        [
            [
                "FA_notify_route_add",
                {
                    "name": "ops",
                    "sinks": ["chat"],
                    "types": ["pipeline.*"],
                    "min_severity": "error",
                    "dedup_seconds": 0,
                    "rate_limit": 5,
                },
            ],
            ["FA_notify_route_list"],
        ]
    ).values()
    assert added["name"] == "ops"
    assert added["rate_limit"] == 5
    assert listed == [added]
    assert notification_router.active is True
    event_bus.publish(_failed("through the action"))
    assert [subject for subject, _, _ in sink.messages] == [
        "[ERROR] pipeline.failed: through the action"
    ]
    removed, missing = executor.execute_action(
        [["FA_notify_route_remove", {"name": "ops"}], ["FA_notify_route_remove", ["ops"]]]
    ).values()
    assert (removed, missing) == (True, False)
    assert notification_router.routes() == []
    assert notification_router.active is False


def test_removing_an_unknown_route_leaves_a_started_router_alone(
    process_wide: list[Event],
) -> None:
    registry = ActionRegistry()
    register_notify_ops(registry)
    notification_router.start()
    (removed,) = (
        ActionExecutor(registry).execute_action([["FA_notify_route_remove", ["nobody"]]]).values()
    )
    assert removed is False
    assert notification_router.active is True


def test_a_bad_route_action_is_reported_not_stored(process_wide: list[Event]) -> None:
    registry = ActionRegistry()
    register_notify_ops(registry)
    (result,) = (
        ActionExecutor(registry)
        .execute_action([["FA_notify_route_add", {"name": "ops", "min_severity": "fatal"}]])
        .values()
    )
    assert "min_severity" in result
    assert notification_router.routes() == []
    assert notification_router.active is False
