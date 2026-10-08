"""The pipeline runtime: ordering, fan-out, statuses, retry, timeout, cancellation, conditions."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from automation_file import ActionRegistry
from automation_file.core.progress import CancellationToken, CancelledException
from automation_file.events import EventBus
from automation_file.exceptions import StorageTransientException
from automation_file.pipeline import (
    DEFAULT_RETRY_ON,
    MemoryRunStore,
    Pipeline,
    PipelineDefinitionException,
    PipelineRun,
    RetryPolicy,
    RunStatus,
    TaskContext,
    TaskStatus,
    worker,
)
from automation_file.pipeline.runner import Engine

WAIT = 5.0  # an upper bound for things that happen at once; never slept through


def until(condition: Callable[[], bool], timeout: float = WAIT) -> bool:
    """Poll ``condition`` until it holds; for state another thread is about to reach."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.002)
    return condition()


def join_task_thread(pipeline: str, task: str) -> None:
    """Wait for the thread of a task the run has given up on."""
    for thread in threading.enumerate():
        if thread.name == f"pipeline-{pipeline}-{task}":
            thread.join(WAIT)
            assert not thread.is_alive()


@pytest.fixture
def store() -> MemoryRunStore:
    return MemoryRunStore()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def execute(store: MemoryRunStore, bus: EventBus) -> Callable[..., PipelineRun]:
    """Run a pipeline against a store and a bus of this test alone."""

    def _execute(pipeline: Pipeline, **options: Any) -> PipelineRun:
        return pipeline.run(store=store, bus=bus, **options)

    return _execute


@pytest.fixture
def registry() -> ActionRegistry:
    registered = ActionRegistry()
    registered.register("T_echo", lambda *args, **kwargs: {"args": list(args), "kwargs": kwargs})
    registered.register("T_constant", lambda: "constant")
    registered.register("T_same", lambda value: value)
    return registered


def statuses(run: PipelineRun) -> dict[str, str]:
    return {task_id: state.status.value for task_id, state in run.tasks.items()}


# ---------------------------------------------------------------------- ordering and fan-out


def test_a_chain_runs_in_dependency_order(execute: Callable[..., PipelineRun]) -> None:
    order: list[str] = []
    pipeline = Pipeline("chain")
    pipeline.task("c", lambda ctx: order.append("c"), depends_on=["b"])
    pipeline.task("b", lambda ctx: order.append("b"), depends_on=["a"])
    pipeline.task("a", lambda ctx: order.append("a"))
    run = execute(pipeline)
    assert order == ["a", "b", "c"]
    assert run.status is RunStatus.SUCCEEDED
    assert run.status == "succeeded"
    assert list(run.tasks) == ["a", "b", "c"]
    assert [state.level for state in run.tasks.values()] == [0, 1, 2]
    assert run.error is None
    assert run.done is True
    assert run.started_at is not None and run.finished_at is not None
    assert run.started_at <= run.finished_at


def test_a_diamond_joins_after_both_branches(execute: Callable[..., PipelineRun]) -> None:
    order: list[str] = []
    guard = threading.Lock()

    def note(ctx: TaskContext) -> str:
        with guard:
            order.append(ctx.task)
        return ctx.task

    pipeline = Pipeline("diamond")
    pipeline.task("top", note)
    pipeline.task("left", note, depends_on=["top"])
    pipeline.task("right", note, depends_on=["top"])
    pipeline.task("bottom", note, depends_on=["left", "right"])
    run = execute(pipeline)
    assert order[0] == "top"
    assert order[-1] == "bottom"
    assert sorted(order[1:3]) == ["left", "right"]
    assert [state.level for state in run.tasks.values()] == [0, 1, 1, 2]
    assert statuses(run) == dict.fromkeys(["top", "left", "right", "bottom"], "succeeded")


def test_independent_tasks_run_at_the_same_time(execute: Callable[..., PipelineRun]) -> None:
    together = threading.Barrier(3)
    pipeline = Pipeline("fan-out", max_workers=3)
    for name in ("one", "two", "three"):
        # The barrier only opens when all three are inside at once.
        pipeline.task(name, lambda ctx: together.wait(WAIT))
    run = execute(pipeline)
    assert statuses(run) == {"one": "succeeded", "two": "succeeded", "three": "succeeded"}
    assert sorted(state.result for state in run.tasks.values()) == [0, 1, 2]


@pytest.mark.parametrize("workers", [1, 2])
def test_max_workers_bounds_the_fan_out(execute: Callable[..., PipelineRun], workers: int) -> None:
    guard = threading.Lock()
    inside = {"now": 0, "peak": 0}
    pair = threading.Barrier(workers)

    def work(_ctx: TaskContext) -> None:
        with guard:
            inside["now"] += 1
            inside["peak"] = max(inside["peak"], inside["now"])
        pair.wait(WAIT)
        with guard:
            inside["now"] -= 1

    pipeline = Pipeline("bounded", max_workers=workers)
    for index in range(4):
        pipeline.task(f"task{index}", work)
    run = execute(pipeline)
    assert run.status is RunStatus.SUCCEEDED
    assert inside["peak"] == workers


def test_pending_and_running_are_visible_while_a_run_is_busy(
    store: MemoryRunStore, bus: EventBus
) -> None:
    entered, release = threading.Event(), threading.Event()

    def first(_ctx: TaskContext) -> str:
        entered.set()
        release.wait(WAIT)
        return "done"

    pipeline = Pipeline("busy")
    pipeline.task("first", first)
    pipeline.task("second", lambda ctx: ctx.results["first"], depends_on=["first"])
    run = pipeline.start(store=store, bus=bus)
    assert entered.wait(WAIT)
    assert run.status is RunStatus.RUNNING
    assert run.done is False
    assert run.wait(0.01) is False
    assert statuses(run) == {"first": "running", "second": "pending"}
    assert run.tasks["first"].started_at is not None
    assert run.tasks["first"].finished_at is None
    release.set()
    assert run.wait(WAIT) is True
    assert run.done is True
    assert statuses(run) == {"first": "succeeded", "second": "succeeded"}
    assert run.tasks["second"].result == "done"


# ---------------------------------------------------------------------- failure


def test_a_failing_task_is_recorded_and_its_dependents_are_skipped(
    execute: Callable[..., PipelineRun],
) -> None:
    def boom(_ctx: TaskContext) -> None:
        raise ValueError("boom")

    ran: list[str] = []
    pipeline = Pipeline("failing")
    pipeline.task("bad", boom)
    pipeline.task("good", lambda ctx: "fine")
    pipeline.task("child", lambda ctx: ran.append("child"), depends_on=["bad"])
    pipeline.task("grandchild", lambda ctx: ran.append("grandchild"), depends_on=["child"])
    run = execute(pipeline)
    assert ran == []
    assert statuses(run) == {
        "bad": "failed",
        "good": "succeeded",
        "child": "skipped",
        "grandchild": "skipped",
    }
    bad = run.tasks["bad"]
    assert bad.error == "ValueError: boom"
    assert bad.attempts == 1
    assert bad.result is None
    assert bad.finished_at is not None
    assert run.tasks["child"].reason == "upstream_failed"
    assert run.tasks["child"].attempts == 0
    assert run.tasks["grandchild"].reason == "upstream_skipped"
    assert run.status is RunStatus.FAILED
    assert run.error == "did not succeed: bad"


def test_a_task_that_calls_sys_exit_is_recorded_as_failed(
    execute: Callable[..., PipelineRun],
) -> None:
    def leaves(_ctx: TaskContext) -> None:
        raise SystemExit(3)

    pipeline = Pipeline("exits")
    pipeline.task("leaves", leaves, retry=RetryPolicy(max_attempts=3))
    pipeline.task("after", lambda ctx: "never", depends_on=["leaves"])
    run = execute(pipeline)
    assert run.tasks["leaves"].status is TaskStatus.FAILED
    assert run.tasks["leaves"].error == "SystemExit: 3"
    assert run.tasks["leaves"].attempts == 1
    assert run.tasks["after"].status is TaskStatus.SKIPPED
    assert run.status is RunStatus.FAILED


def test_an_interrupted_coordinator_leaves_a_failed_run(
    store: MemoryRunStore, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(_engine: Engine) -> None:
        raise RuntimeError("no threads left")

    monkeypatch.setattr(Engine, "_launch", explode)
    pipeline = Pipeline("aborted")
    pipeline.task("only", lambda ctx: "never")
    with pytest.raises(RuntimeError, match="no threads left"):
        pipeline.run(store=store, bus=bus)
    (recorded,) = store.list_runs("aborted")
    assert recorded.status is RunStatus.FAILED
    assert recorded.error == "RuntimeError: no threads left"
    assert recorded.done is True
    assert recorded.tasks["only"].status is TaskStatus.CANCELLED
    assert [event.type for event in reversed(bus.recent())] == [
        "pipeline.started",
        "pipeline.failed",
    ]


def test_ctrl_c_gives_up_on_what_is_in_the_air(
    store: MemoryRunStore, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()

    def interrupted(_engine: Engine) -> None:
        assert entered.wait(WAIT)
        raise KeyboardInterrupt

    def slow(ctx: TaskContext) -> str:
        entered.set()
        release.wait(WAIT)
        return f"late, cancelled={ctx.cancel.is_cancelled}"

    monkeypatch.setattr(Engine, "_await", interrupted)
    pipeline = Pipeline("interrupted")
    pipeline.task("slow", slow)
    pipeline.task("next", lambda ctx: "never", depends_on=["slow"])
    try:
        with pytest.raises(KeyboardInterrupt):
            pipeline.run(store=store, bus=bus)
        (recorded,) = store.list_runs("interrupted")
        assert recorded.status is RunStatus.FAILED
        assert recorded.error == "KeyboardInterrupt"
        assert recorded.done is True
        assert statuses(recorded) == {"slow": "cancelled", "next": "cancelled"}
    finally:
        release.set()
    join_task_thread("interrupted", "slow")
    # The task returned after the run had given up on it; its result is not recorded.
    assert store.get_run(recorded.run_id).to_dict() == recorded.to_dict()
    assert bus.recent(limit=1)[0].type == "pipeline.failed"


def test_a_background_run_that_aborts_still_ends(
    store: MemoryRunStore, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(_engine: Engine) -> None:
        raise RuntimeError("no threads left")

    monkeypatch.setattr(Engine, "_launch", explode)
    pipeline = Pipeline("aborted-in-background")
    pipeline.task("only", lambda ctx: "never")
    run = pipeline.start(store=store, bus=bus)
    assert run.wait(WAIT) is True
    assert run.status is RunStatus.FAILED
    assert run.error == "RuntimeError: no threads left"


# ---------------------------------------------------------------------- retry


def test_the_default_retry_types_are_the_transient_ones() -> None:
    policy = RetryPolicy()
    assert policy.max_attempts == 1
    assert policy.backoff_base == pytest.approx(0.0)
    assert policy.backoff_cap == pytest.approx(60.0)
    assert policy.retry_on == (StorageTransientException, ConnectionError, TimeoutError)
    assert policy.retry_on is DEFAULT_RETRY_ON
    assert Exception not in policy.retry_on
    assert policy.retries(StorageTransientException("throttled")) is True
    assert policy.retries(ConnectionResetError("reset")) is True
    assert policy.retries(ValueError("a bug")) is False


def test_the_back_off_doubles_up_to_its_cap() -> None:
    policy = RetryPolicy(max_attempts=9, backoff_base=2.0, backoff_cap=5.0)
    assert [policy.delay(attempt) for attempt in (1, 2, 3, 4)] == [2.0, 4.0, 5.0, 5.0]
    assert policy.delay(5000) == pytest.approx(5.0)
    assert RetryPolicy(max_attempts=3).delay(2) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "options",
    [
        {"max_attempts": 0},
        {"max_attempts": True},
        {"max_attempts": 2.5},
        {"backoff_base": -1.0},
        {"backoff_cap": -0.1},
        {"retry_on": ("ValueError",)},
        {"retry_on": (int,)},
    ],
)
def test_a_retry_policy_rejects_bad_values(options: dict[str, Any]) -> None:
    with pytest.raises(PipelineDefinitionException):
        RetryPolicy(**options)


def test_retry_on_accepts_a_list() -> None:
    assert RetryPolicy(retry_on=[KeyError]).retry_on == (KeyError,)  # type: ignore[arg-type]


def test_a_transient_failure_is_retried_with_back_off(
    execute: Callable[..., PipelineRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []

    def no_sleep(_token: object, seconds: float) -> bool:
        waits.append(seconds)
        return False

    monkeypatch.setattr(worker, "pause", no_sleep)
    attempts: list[int] = []

    def flaky(ctx: TaskContext) -> str:
        attempts.append(ctx.attempt)
        if ctx.attempt < 5:
            raise StorageTransientException("throttled")
        return "through"

    pipeline = Pipeline("retrying")
    pipeline.task(
        "flaky", flaky, retry=RetryPolicy(max_attempts=5, backoff_base=1.0, backoff_cap=3.0)
    )
    run = execute(pipeline)
    state = run.tasks["flaky"]
    assert attempts == [1, 2, 3, 4, 5]
    assert waits == [1.0, 2.0, 3.0, 3.0]
    assert state.status is TaskStatus.SUCCEEDED
    assert state.attempts == 5
    assert state.result == "through"
    assert state.error is None
    assert run.status is RunStatus.SUCCEEDED


def test_retry_gives_up_after_max_attempts(
    execute: Callable[..., PipelineRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(worker, "pause", lambda _token, seconds: waits.append(seconds) or False)

    def down(_ctx: TaskContext) -> None:
        raise ConnectionError("refused")

    pipeline = Pipeline("giving-up")
    pipeline.task("down", down, retry=RetryPolicy(max_attempts=3, backoff_base=0.5))
    run = execute(pipeline)
    assert run.tasks["down"].status is TaskStatus.FAILED
    assert run.tasks["down"].attempts == 3
    assert run.tasks["down"].error == "ConnectionError: refused"
    assert waits == [0.5, 1.0]


def test_an_error_outside_retry_on_fails_at_once(
    execute: Callable[..., PipelineRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(worker, "pause", lambda _token, seconds: waits.append(seconds) or False)

    def bug(_ctx: TaskContext) -> None:
        raise KeyError("typo")

    pipeline = Pipeline("bug")
    pipeline.task("bug", bug, retry=RetryPolicy(max_attempts=4, backoff_base=1.0))
    pipeline.task(
        "wanted",
        bug,
        retry=RetryPolicy(max_attempts=2, retry_on=(KeyError,)),
    )
    run = execute(pipeline)
    assert run.tasks["bug"].attempts == 1
    assert run.tasks["wanted"].attempts == 2
    assert waits == [0.0]


def test_a_back_off_ends_when_the_run_is_cancelled(
    store: MemoryRunStore, bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiting = threading.Event()
    real_pause = worker.pause

    def announced(token: worker.TaskToken, seconds: float) -> bool:
        waiting.set()
        return real_pause(token, seconds)

    monkeypatch.setattr(worker, "pause", announced)

    def flaky(_ctx: TaskContext) -> None:
        raise ConnectionError("down")

    pipeline = Pipeline("cancelled-back-off")
    pipeline.task("flaky", flaky, retry=RetryPolicy(max_attempts=3, backoff_base=600.0))
    run = pipeline.start(store=store, bus=bus)
    assert waiting.wait(WAIT)
    run.cancel()
    assert run.wait(WAIT) is True  # the ten-minute back-off was not slept through
    state = run.tasks["flaky"]
    assert state.status is TaskStatus.CANCELLED
    assert state.attempts == 1
    assert state.error == "ConnectionError: down"
    assert run.status is RunStatus.CANCELLED


# ---------------------------------------------------------------------- timeout


def test_a_task_past_its_timeout_is_marked_and_the_run_goes_on(
    execute: Callable[..., PipelineRun], bus: EventBus
) -> None:
    release, saw_cancel = threading.Event(), threading.Event()

    def stuck(ctx: TaskContext) -> str:
        release.wait(WAIT)  # ignores its token until the test lets it go
        if ctx.cancel.is_cancelled:
            saw_cancel.set()
        return "too late"

    pipeline = Pipeline("slow")
    pipeline.task("stuck", stuck, timeout=0.05)
    pipeline.task("other", lambda ctx: "ran")
    pipeline.task("after", lambda ctx: "never", depends_on=["stuck"])
    pipeline.task("cleanup", lambda ctx: "cleaned", depends_on=["stuck"], when="on_failure")
    try:
        run = execute(pipeline)
        state = run.tasks["stuck"]
        assert state.status is TaskStatus.TIMEOUT
        assert state.error == "TimeoutError: no result within 0.05 s"
        assert state.result is None
        assert state.finished_at is not None
        assert run.tasks["other"].status is TaskStatus.SUCCEEDED
        assert run.tasks["after"].status is TaskStatus.SKIPPED
        assert run.tasks["after"].reason == "upstream_failed"
        assert run.tasks["cleanup"].result == "cleaned"
        assert run.status is RunStatus.FAILED
        assert run.error == "did not succeed: stuck"
    finally:
        release.set()
    join_task_thread("slow", "stuck")
    # The thread could not be killed: it finished later, saw its token, and changed nothing.
    assert saw_cancel.is_set()
    assert run.tasks["stuck"].status is TaskStatus.TIMEOUT
    assert run.tasks["stuck"].result is None
    assert bus.recent(limit=1)[0].type == "pipeline.failed"


def test_a_task_inside_its_timeout_succeeds(execute: Callable[..., PipelineRun]) -> None:
    pipeline = Pipeline("quick")
    pipeline.task("quick", lambda ctx: "in time", timeout=WAIT)
    run = execute(pipeline)
    assert run.tasks["quick"].status is TaskStatus.SUCCEEDED
    assert run.tasks["quick"].result == "in time"


def test_the_timeout_covers_the_waits_between_attempts(
    execute: Callable[..., PipelineRun],
) -> None:
    def down(_ctx: TaskContext) -> None:
        raise ConnectionError("down")

    pipeline = Pipeline("budget")
    pipeline.task("down", down, retry=RetryPolicy(max_attempts=5, backoff_base=600.0), timeout=0.05)
    run = execute(pipeline)
    assert run.tasks["down"].status is TaskStatus.TIMEOUT
    assert run.tasks["down"].attempts == 1
    join_task_thread("budget", "down")
    assert run.tasks["down"].status is TaskStatus.TIMEOUT


# ---------------------------------------------------------------------- cancellation


def test_cancel_stops_a_background_run(store: MemoryRunStore, bus: EventBus) -> None:
    entered = threading.Event()
    ran: list[str] = []

    def watches(ctx: TaskContext) -> None:
        entered.set()
        assert until(lambda: ctx.cancel.is_cancelled)
        ctx.cancel.raise_if_cancelled()

    pipeline = Pipeline("cancelled")
    pipeline.task("first", watches)
    pipeline.task("second", lambda ctx: ran.append("second"), depends_on=["first"])
    pipeline.task("cleanup", lambda ctx: ran.append("cleanup"), depends_on=["first"], when="always")
    run = pipeline.start(store=store, bus=bus)
    assert entered.wait(WAIT)
    run.cancel()
    assert run.wait(WAIT) is True
    assert ran == []
    assert statuses(run) == {"first": "cancelled", "second": "cancelled", "cleanup": "cancelled"}
    assert run.tasks["first"].error == "CancelledException: operation cancelled"
    assert run.tasks["second"].attempts == 0
    assert run.status is RunStatus.CANCELLED
    assert run.error == "the run was cancelled"
    assert store.get_run(run.run_id).to_dict() == run.to_dict()


def test_a_token_cancelled_beforehand_runs_nothing(execute: Callable[..., PipelineRun]) -> None:
    ran: list[str] = []
    token = CancellationToken()
    token.cancel()
    pipeline = Pipeline("pre-cancelled")
    pipeline.task("first", lambda ctx: ran.append("first"))
    pipeline.task("second", lambda ctx: ran.append("second"), depends_on=["first"])
    run = execute(pipeline, cancel=token)
    assert ran == []
    assert statuses(run) == {"first": "cancelled", "second": "cancelled"}
    assert run.status is RunStatus.CANCELLED
    assert run.cancel_token is token


def test_a_running_task_that_ignores_cancellation_keeps_its_outcome(
    store: MemoryRunStore, bus: EventBus
) -> None:
    entered, release = threading.Event(), threading.Event()

    def deaf(_ctx: TaskContext) -> str:
        entered.set()
        release.wait(WAIT)
        return "finished anyway"

    token = CancellationToken()
    pipeline = Pipeline("deaf")
    pipeline.task("deaf", deaf)
    pipeline.task("next", lambda ctx: "never", depends_on=["deaf"])
    run = pipeline.start(store=store, bus=bus, cancel=token)
    assert entered.wait(WAIT)
    token.cancel()
    assert until(lambda: run.tasks["next"].status is TaskStatus.CANCELLED)
    assert run.done is False  # the run waits for what is still in the air
    release.set()
    assert run.wait(WAIT) is True
    assert run.tasks["deaf"].status is TaskStatus.SUCCEEDED
    assert run.tasks["deaf"].result == "finished anyway"
    assert run.status is RunStatus.CANCELLED


def test_a_task_cancelled_on_its_own_counts_as_a_failure(
    execute: Callable[..., PipelineRun],
) -> None:
    def gives_up(_ctx: TaskContext) -> None:
        raise CancelledException("transfer cancelled")

    pipeline = Pipeline("self-cancelled")
    pipeline.task("transfer", gives_up)
    pipeline.task("cleanup", lambda ctx: "cleaned", depends_on=["transfer"], when="on_failure")
    run = execute(pipeline)
    assert run.tasks["transfer"].status is TaskStatus.CANCELLED
    assert run.tasks["cleanup"].status is TaskStatus.SUCCEEDED
    assert run.status is RunStatus.FAILED


# ---------------------------------------------------------------------- conditions


def _outcomes(execute: Callable[..., PipelineRun], upstream_fails: bool, when: Any) -> PipelineRun:
    def upstream(_ctx: TaskContext) -> str:
        if upstream_fails:
            raise ValueError("upstream broke")
        return "fine"

    pipeline = Pipeline("conditions")
    pipeline.task("upstream", upstream)
    pipeline.task("conditional", lambda ctx: "ran", depends_on=["upstream"], when=when)
    return execute(pipeline)


@pytest.mark.parametrize(
    "when,upstream_fails,status,reason",
    [
        ("on_success", False, "succeeded", None),
        ("on_success", True, "skipped", "upstream_failed"),
        ("on_failure", True, "succeeded", None),
        ("on_failure", False, "skipped", "condition"),
        ("always", False, "succeeded", None),
        ("always", True, "succeeded", None),
    ],
)
def test_when_decides_whether_a_task_runs(
    execute: Callable[..., PipelineRun],
    when: str,
    upstream_fails: bool,
    status: str,
    reason: str | None,
) -> None:
    run = _outcomes(execute, upstream_fails, when)
    state = run.tasks["conditional"]
    assert state.status == status
    assert state.reason == reason
    assert state.result == ("ran" if status == "succeeded" else None)


def test_on_success_is_the_default() -> None:
    pipeline = Pipeline("default")
    assert pipeline.task("a", lambda ctx: None).when == "on_success"


def test_on_failure_without_dependencies_never_runs(execute: Callable[..., PipelineRun]) -> None:
    pipeline = Pipeline("orphan")
    pipeline.task("cleanup", lambda ctx: "ran", when="on_failure")
    run = execute(pipeline)
    assert run.tasks["cleanup"].status is TaskStatus.SKIPPED
    assert run.tasks["cleanup"].reason == "condition"
    assert run.status is RunStatus.SUCCEEDED


def test_a_callable_condition_sees_the_context(execute: Callable[..., PipelineRun]) -> None:
    seen: list[TaskContext] = []

    def big_enough(ctx: TaskContext) -> bool:
        seen.append(ctx)
        return ctx.results["count"] >= ctx.params["minimum"]

    pipeline = Pipeline("callable-when")
    pipeline.task("count", lambda ctx: 7)
    pipeline.task("report", lambda ctx: "reported", depends_on=["count"], when=big_enough)
    run = execute(pipeline, params={"minimum": 5})
    assert run.tasks["report"].status is TaskStatus.SUCCEEDED
    assert (seen[0].task, seen[0].attempt, seen[0].run_id) == ("report", 0, run.run_id)
    skipped = execute(pipeline, params={"minimum": 50})
    assert skipped.tasks["report"].status is TaskStatus.SKIPPED
    assert skipped.tasks["report"].reason == "condition"
    assert len(seen) == 2  # asked exactly once per run


def test_a_condition_that_raises_fails_its_task(execute: Callable[..., PipelineRun]) -> None:
    def broken(_ctx: TaskContext) -> bool:
        raise LookupError("no such result")

    ran: list[str] = []
    pipeline = Pipeline("broken-when")
    pipeline.task("guarded", lambda ctx: ran.append("guarded"), when=broken)
    run = execute(pipeline)
    assert ran == []
    assert run.tasks["guarded"].status is TaskStatus.FAILED
    assert run.tasks["guarded"].error == "when: LookupError: no such result"
    assert run.tasks["guarded"].attempts == 0
    assert run.status is RunStatus.FAILED


def test_a_skip_propagates_to_on_success_dependents_only(
    execute: Callable[..., PipelineRun],
) -> None:
    pipeline = Pipeline("propagation")
    pipeline.task("gate", lambda ctx: "ran", when=lambda ctx: False)
    pipeline.task("child", lambda ctx: "ran", depends_on=["gate"])
    pipeline.task("grandchild", lambda ctx: "ran", depends_on=["child"])
    pipeline.task("regardless", lambda ctx: "ran", depends_on=["gate"], when="always")
    pipeline.task("on-error", lambda ctx: "ran", depends_on=["gate"], when="on_failure")
    run = execute(pipeline)
    assert statuses(run) == {
        "gate": "skipped",
        "child": "skipped",
        "regardless": "succeeded",
        "on-error": "skipped",
        "grandchild": "skipped",
    }
    assert run.tasks["gate"].reason == "condition"
    assert run.tasks["child"].reason == "upstream_skipped"
    assert run.tasks["grandchild"].reason == "upstream_skipped"
    assert run.tasks["on-error"].reason == "condition"
    assert run.status is RunStatus.SUCCEEDED  # nothing failed


def test_a_failure_outranks_a_skip_as_the_reason(execute: Callable[..., PipelineRun]) -> None:
    def boom(_ctx: TaskContext) -> None:
        raise ValueError("boom")

    pipeline = Pipeline("mixed")
    pipeline.task("skipped", lambda ctx: "ran", when=lambda ctx: False)
    pipeline.task("failed", boom)
    pipeline.task("both", lambda ctx: "ran", depends_on=["skipped", "failed"])
    run = execute(pipeline)
    assert run.tasks["both"].reason == "upstream_failed"


# ---------------------------------------------------------------------- context and results


def test_a_callable_gets_its_context(execute: Callable[..., PipelineRun]) -> None:
    seen: dict[str, TaskContext] = {}

    def remember(ctx: TaskContext) -> str:
        seen[ctx.task] = ctx
        return f"{ctx.task}-result"

    pipeline = Pipeline("context", params={"date": "2026-01-01", "region": "emea"})
    pipeline.task("a", remember)
    pipeline.task("b", remember, depends_on=["a"])
    pipeline.task("c", remember, depends_on=["b"])
    pipeline.task("unrelated", remember)
    run = execute(pipeline, params={"date": "2026-10-08"})
    ctx = seen["c"]
    assert ctx.pipeline == "context"
    assert ctx.run_id == run.run_id
    assert ctx.task == "c"
    assert ctx.attempt == 1
    assert ctx.dry_run is False
    assert dict(ctx.params) == {"date": "2026-10-08", "region": "emea"}
    assert dict(ctx.results) == {"a": "a-result", "b": "b-result"}  # every upstream task
    assert isinstance(ctx.cancel, CancellationToken)
    assert ctx.cancel.is_cancelled is False
    assert dict(seen["a"].results) == {}
    with pytest.raises(TypeError):
        ctx.params["date"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        ctx.results["a"] = "changed"  # type: ignore[index]
    assert run.params == {"date": "2026-10-08", "region": "emea"}
    assert pipeline.params == {"date": "2026-01-01", "region": "emea"}


def test_results_hold_only_the_upstream_tasks_that_succeeded(
    execute: Callable[..., PipelineRun],
) -> None:
    def boom(_ctx: TaskContext) -> None:
        raise ValueError("boom")

    pipeline = Pipeline("partial")
    pipeline.task("good", lambda ctx: 1)
    pipeline.task("bad", boom)
    pipeline.task(
        "report", lambda ctx: dict(ctx.results), depends_on=["good", "bad"], when="always"
    )
    run = execute(pipeline)
    assert run.tasks["report"].result == {"good": 1}


def test_a_result_json_cannot_hold_stays_an_object_in_memory(
    execute: Callable[..., PipelineRun], store: MemoryRunStore
) -> None:
    marker = object()
    pipeline = Pipeline("objects")
    pipeline.task("make", lambda ctx: marker)
    pipeline.task("use", lambda ctx: ctx.results["make"] is marker, depends_on=["make"])
    run = execute(pipeline)
    assert run.tasks["make"].result is marker
    assert run.tasks["make"].result_is_repr is False
    assert run.tasks["use"].result is True
    document = run.to_dict()["tasks"]["make"]
    assert document["result"] == repr(marker)
    assert document["result_is_repr"] is True
    stored = store.get_run(run.run_id).tasks["make"]
    assert stored.result == repr(marker)
    assert stored.result_is_repr is True


# ---------------------------------------------------------------------- action tasks


def test_the_three_action_shapes(
    execute: Callable[..., PipelineRun], registry: ActionRegistry
) -> None:
    pipeline = Pipeline("actions", registry=registry)
    pipeline.task("bare", ["T_constant"])
    pipeline.task("keywords", ["T_echo", {"a": 1, "b": "two"}])
    pipeline.task("positional", ["T_echo", [1, "two"]])
    run = execute(pipeline)
    assert run.tasks["bare"].result == "constant"
    assert run.tasks["keywords"].result == {"args": [], "kwargs": {"a": 1, "b": "two"}}
    assert run.tasks["positional"].result == {"args": [1, "two"], "kwargs": {}}


def test_an_action_resolves_through_the_shared_registry(
    execute: Callable[..., PipelineRun],
) -> None:
    pipeline = Pipeline("shared")
    pipeline.task("schemes", ["FA_storage_schemes"])
    run = execute(pipeline)
    assert "memory" in run.tasks["schemes"].result


def test_an_action_that_fails_raises_into_its_task(
    execute: Callable[..., PipelineRun], registry: ActionRegistry
) -> None:
    def refuse(path: str) -> None:
        raise PermissionError(f"denied: {path}")

    registry.register("T_refuse", refuse)
    pipeline = Pipeline("action-errors", registry=registry)
    pipeline.task("refused", ["T_refuse", {"path": "/etc"}])
    pipeline.task("unknown", ["T_missing"])
    pipeline.task("wrong-arguments", ["T_constant", {"surplus": 1}])
    run = execute(pipeline)
    assert run.tasks["refused"].error == "PermissionError: denied: /etc"
    assert run.tasks["unknown"].error == "PipelineException: unknown action 'T_missing'"
    assert run.tasks["wrong-arguments"].error.startswith("TypeError: ")
    assert run.status is RunStatus.FAILED


def test_parameters_and_results_are_substituted(
    execute: Callable[..., PipelineRun], registry: ActionRegistry
) -> None:
    listing = {"files": ["a.csv", "b.csv"]}
    pipeline = Pipeline("substitution", registry=registry, params={"limit": 20})
    pipeline.task("list", lambda ctx: listing)
    pipeline.task(
        "use",
        [
            "T_echo",
            {
                "text": "report-${params.date}-${params.limit}.csv",
                "limit": "${params.limit}",
                "listing": "${tasks.list.result}",
                "nested": {"again": ["${tasks.list.result}", "x-${params.date}"], "number": 3},
                "untouched": "${env:HOME} and ${date:%Y} stay",
            },
        ],
        depends_on=["list"],
    )
    run = execute(pipeline, params={"date": "2026-10-08"})
    kwargs = run.tasks["use"].result["kwargs"]
    assert kwargs["text"] == "report-2026-10-08-20.csv"
    assert kwargs["limit"] == 20  # a whole-string parameter keeps its type
    assert kwargs["listing"] is listing  # the result object itself
    assert kwargs["nested"] == {"again": [listing, "x-2026-10-08"], "number": 3}
    assert kwargs["untouched"] == "${env:HOME} and ${date:%Y} stay"
    assert pipeline.tasks[1].work[1]["limit"] == "${params.limit}"  # the definition is not changed


def test_positional_arguments_are_substituted(
    execute: Callable[..., PipelineRun], registry: ActionRegistry
) -> None:
    pipeline = Pipeline("positional-substitution", registry=registry)
    pipeline.task("first", lambda ctx: [1, 2])
    pipeline.task("second", ["T_same", ["${tasks.first.result}"]], depends_on=["first"])
    run = execute(pipeline)
    assert run.tasks["second"].result == [1, 2]


def test_the_result_of_a_failed_upstream_task_is_none(
    execute: Callable[..., PipelineRun], registry: ActionRegistry
) -> None:
    def boom(_ctx: TaskContext) -> None:
        raise ValueError("boom")

    pipeline = Pipeline("failed-upstream", registry=registry)
    pipeline.task("broken", boom)
    pipeline.task(
        "notify",
        ["T_same", {"value": "${tasks.broken.result}"}],
        depends_on=["broken"],
        when="always",
    )
    run = execute(pipeline)
    assert run.tasks["notify"].status is TaskStatus.SUCCEEDED
    assert run.tasks["notify"].result is None


# ---------------------------------------------------------------------- dry run


def test_a_dry_run_plans_every_task_and_executes_nothing(
    store: MemoryRunStore, bus: EventBus, registry: ActionRegistry
) -> None:
    ran: list[str] = []
    pipeline = Pipeline("planned", registry=registry)
    pipeline.task("report", ["T_echo", {"rows": "${tasks.load.result}"}], depends_on=["load"])
    pipeline.task("load", lambda ctx: ran.append("load"), depends_on=["fetch"])
    pipeline.task("fetch", ["T_constant"], idempotency_key="fetch-${params.date}")
    pipeline.task("side", lambda ctx: ran.append("side"), when=lambda ctx: ran.append("when"))
    run = pipeline.run(params={"date": "2026-10-08"}, dry_run=True, store=store, bus=bus)
    assert ran == []
    assert run.dry_run is True
    assert run.done is True
    assert run.status is RunStatus.SUCCEEDED
    assert run.error is None
    assert [(task_id, state.status.value, state.level) for task_id, state in run.tasks.items()] == [
        ("fetch", "planned", 0),
        ("side", "planned", 0),
        ("load", "planned", 1),
        ("report", "planned", 2),
    ]
    assert all(state.error is None and state.attempts == 0 for state in run.tasks.values())
    assert store.list_runs() == []
    assert bus.recent() == []
    assert run.to_dict()["dry_run"] is True


def test_a_dry_run_reports_unknown_actions_and_missing_parameters(
    registry: ActionRegistry,
) -> None:
    pipeline = Pipeline("planned-with-problems", registry=registry)
    pipeline.task("typo", ["T_ecko", {"path": "${params.path}"}])
    pipeline.task("fine", ["T_constant"], depends_on=["typo"])
    pipeline.task("keyed", ["T_constant"], idempotency_key="k-${params.date}")
    run = pipeline.run(dry_run=True)
    assert statuses(run) == {"typo": "planned", "keyed": "planned", "fine": "planned"}
    assert run.tasks["typo"].error == (
        "tasks.typo.action[1].path: unknown parameter 'path';"
        " tasks.typo.action[0]: unknown action 'T_ecko'"
    )
    assert run.tasks["keyed"].error == "tasks.keyed.idempotency_key: unknown parameter 'date'"
    assert run.tasks["fine"].error is None
    assert run.status is RunStatus.FAILED
    assert run.error == "would not run as planned: typo, keyed"


def test_a_dry_run_still_rejects_a_broken_graph() -> None:
    pipeline = Pipeline("planned-cycle")
    pipeline.task("a", lambda ctx: None, depends_on=["b"])
    pipeline.task("b", lambda ctx: None, depends_on=["a"])
    with pytest.raises(PipelineDefinitionException, match="dependency cycle: a -> b -> a"):
        pipeline.run(dry_run=True)
