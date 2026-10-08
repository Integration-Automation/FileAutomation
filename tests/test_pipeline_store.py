"""Run stores, checkpoints, resume, idempotency and the execution history."""

# pylint: disable=broad-exception-caught  # the test records whatever was raised
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import inspect
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from automation_file.events import EventBus
from automation_file.pipeline import (
    MemoryRunStore,
    Pipeline,
    PipelineDefinitionException,
    PipelineException,
    PipelineRun,
    RetryPolicy,
    RunStatus,
    RunStore,
    SQLiteRunStore,
    TaskContext,
    TaskRun,
    TaskStatus,
    default_run_store,
    set_default_run_store,
    worker,
)

WAIT = 5.0
START = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> RunStore:
    if request.param == "memory":
        return MemoryRunStore()
    return SQLiteRunStore(tmp_path / "runs" / "pipelines.db")


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


def until(condition: Callable[[], bool], timeout: float = WAIT) -> bool:
    """Poll ``condition`` until it holds; for state another thread is about to reach."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.002)
    return condition()


def a_run(run_id: str = "run-1", pipeline: str = "daily", minutes: int = 0) -> PipelineRun:
    return PipelineRun(
        run_id=run_id,
        pipeline=pipeline,
        params={"date": "2026-10-08"},
        started_at=START + timedelta(minutes=minutes),
        tasks={"load": TaskRun(task="load"), "report": TaskRun(task="report", level=1)},
    )


def a_success(
    task: str = "load", key: str | None = None, result: Any = None, minutes: int = 0
) -> TaskRun:
    return TaskRun(
        task=task,
        status=TaskStatus.SUCCEEDED,
        attempts=2,
        result=result,
        idempotency_key=key,
        started_at=START + timedelta(minutes=minutes),
        finished_at=START + timedelta(minutes=minutes, seconds=3),
    )


# ---------------------------------------------------------------------- the store contract


def test_a_saved_run_comes_back_equal(store: RunStore) -> None:
    run = a_run()
    run.tasks["load"] = a_success(key="load-2026-10-08", result={"rows": 3, "files": ["a", "b"]})
    store.save_run(run)
    loaded = store.get_run("run-1")
    assert loaded is not None and loaded is not run
    assert loaded.to_dict() == run.to_dict()
    assert list(loaded.tasks) == ["load", "report"]
    assert loaded.tasks["load"].started_at == START
    assert loaded.tasks["load"].duration_ms == pytest.approx(3000.0)
    assert loaded.tasks["report"].level == 1
    assert loaded.status is RunStatus.RUNNING
    assert loaded.done is False
    assert loaded.params == {"date": "2026-10-08"}


def test_an_unknown_run_is_none(store: RunStore) -> None:
    assert store.get_run("nope") is None


def test_save_task_records_one_transition(store: RunStore) -> None:
    store.save_run(a_run())
    store.save_task("run-1", a_success(result=[1, 2]))
    failed = TaskRun(task="report", status=TaskStatus.FAILED, level=1, attempts=1, error="X: y")
    store.save_task("run-1", failed)
    store.save_task(
        "run-1", TaskRun(task="added-later", status=TaskStatus.SKIPPED, reason="condition")
    )
    loaded = store.get_run("run-1")
    assert list(loaded.tasks) == ["load", "report", "added-later"]
    assert loaded.tasks["load"].status is TaskStatus.SUCCEEDED
    assert loaded.tasks["load"].result == [1, 2]
    assert loaded.tasks["report"].error == "X: y"
    assert loaded.tasks["added-later"].reason == "condition"


def test_save_task_needs_a_stored_run(store: RunStore) -> None:
    with pytest.raises(PipelineException, match="unknown run 'ghost'"):
        store.save_task("ghost", TaskRun(task="load"))


def test_save_run_replaces_the_whole_run(store: RunStore) -> None:
    store.save_run(a_run())
    changed = a_run()
    changed.status = RunStatus.SUCCEEDED
    changed.finished_at = START + timedelta(seconds=9)
    changed.error = None
    changed.tasks = {"report": TaskRun(task="report"), "extra": TaskRun(task="extra", level=1)}
    store.save_run(changed)
    loaded = store.get_run("run-1")
    assert list(loaded.tasks) == ["report", "extra"]
    assert loaded.status is RunStatus.SUCCEEDED
    assert loaded.done is True
    assert loaded.finished_at == changed.finished_at
    assert len(store.list_runs()) == 1


def test_what_a_store_returns_is_a_copy(store: RunStore) -> None:
    result = {"rows": [1]}
    run = a_run()
    run.tasks["load"] = a_success(result=result)
    store.save_run(run)
    result["rows"].append(2)  # the live object changes after the checkpoint
    loaded = store.get_run("run-1")
    assert loaded.tasks["load"].result == {"rows": [1]}
    loaded.tasks["load"].result["rows"].append(99)
    loaded.params["date"] = "changed"
    again = store.get_run("run-1")
    assert again.tasks["load"].result == {"rows": [1]}
    assert again.params == {"date": "2026-10-08"}
    assert store.list_runs()[0].tasks["load"].result == {"rows": [1]}


def test_list_runs_is_newest_first_and_filters(store: RunStore) -> None:
    store.save_run(a_run("run-1", "daily", minutes=0))
    store.save_run(a_run("run-3", "daily", minutes=20))
    store.save_run(a_run("run-2", "weekly", minutes=10))
    assert [run.run_id for run in store.list_runs()] == ["run-3", "run-2", "run-1"]
    assert [run.run_id for run in store.list_runs("daily")] == ["run-3", "run-1"]
    assert [run.run_id for run in store.list_runs(pipeline="weekly")] == ["run-2"]
    assert store.list_runs("unknown") == []
    assert [run.run_id for run in store.list_runs(limit=2)] == ["run-3", "run-2"]
    assert store.list_runs(limit=0) == []
    assert list(store.list_runs()[0].tasks) == ["load", "report"]
    assert inspect.signature(RunStore.list_runs).parameters["limit"].default == 50


def test_runs_started_at_the_same_moment_list_the_latest_saved_first(store: RunStore) -> None:
    for run_id in ("first", "second", "third"):
        store.save_run(a_run(run_id))
    store.save_run(a_run("first"))  # saving again does not move it
    assert [run.run_id for run in store.list_runs()] == ["third", "second", "first"]


def test_find_idempotent_returns_the_latest_succeeded_execution(store: RunStore) -> None:
    def record(run_id: str, pipeline: str, state: TaskRun) -> None:
        run = a_run(run_id, pipeline)
        run.tasks["load"] = state
        store.save_run(run)

    record("run-1", "daily", a_success(key="k1", result="old", minutes=1))
    record("run-2", "daily", a_success(key="k1", result="new", minutes=5))
    record("run-3", "daily", a_success(key="k1", result="middle", minutes=3))
    failed = TaskRun(task="load", status=TaskStatus.FAILED, idempotency_key="k1")
    record("run-4", "daily", failed)
    reused = TaskRun(
        task="load",
        status=TaskStatus.SKIPPED,
        reason="idempotent",
        idempotency_key="k1",
        result="reused",
        finished_at=START + timedelta(minutes=9),
    )
    record("run-5", "daily", reused)
    record("run-6", "weekly", a_success(key="k1", result="weekly", minutes=7))
    found = store.find_idempotent("daily", "load", "k1")
    assert found is not None
    assert (found.result, found.status, found.attempts) == ("new", TaskStatus.SUCCEEDED, 2)
    assert found.idempotency_key == "k1"
    assert store.find_idempotent("weekly", "load", "k1").result == "weekly"
    assert store.find_idempotent("daily", "load", "k2") is None
    assert store.find_idempotent("daily", "report", "k1") is None
    assert store.find_idempotent("monthly", "load", "k1") is None


def test_a_result_json_cannot_hold_is_stored_as_its_repr_and_flagged(store: RunStore) -> None:
    marker = object()
    run = a_run()
    run.tasks["load"] = a_success(result=marker)
    run.tasks["report"] = a_success("report", result=(1, {"when": START}))
    run.params["client"] = marker
    store.save_run(run)
    store.save_task("run-1", a_success("tuple", result=(1, 2)))
    loaded = store.get_run("run-1")
    assert loaded.tasks["load"].result == repr(marker)
    assert loaded.tasks["load"].result_is_repr is True
    assert loaded.tasks["report"].result == repr((1, {"when": START}))
    assert loaded.tasks["report"].result_is_repr is True
    assert loaded.tasks["tuple"].result == [1, 2]  # JSON has no tuple
    assert loaded.tasks["tuple"].result_is_repr is False
    assert loaded.params == {"date": "2026-10-08", "client": repr(marker)}
    assert loaded.to_dict()["tasks"]["load"]["result_is_repr"] is True  # the flag stays


def test_names_are_never_part_of_the_sql(store: RunStore) -> None:
    hostile = "x'; DROP TABLE pipeline_runs; --"
    run = a_run(hostile, hostile)
    run.tasks = {hostile: a_success(hostile, key=hostile, result=hostile)}
    store.save_run(run)
    store.save_task(hostile, run.tasks[hostile])
    assert store.get_run(hostile).to_dict() == run.to_dict()
    assert [found.run_id for found in store.list_runs(hostile)] == [hostile]
    assert store.find_idempotent(hostile, hostile, hostile).result == hostile


def test_a_store_is_safe_to_share_between_threads(store: RunStore) -> None:
    store.save_run(a_run())
    errors: list[Exception] = []

    def write(worker_index: int) -> None:
        try:
            for step in range(5):
                store.save_task("run-1", a_success(f"w{worker_index}-{step}", result=step))
                store.list_runs()
        except Exception as error:  # collected for the assertion below
            errors.append(error)

    threads = [threading.Thread(target=write, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)
    assert errors == []
    assert len(store.get_run("run-1").tasks) == 2 + 20


def test_run_store_is_abstract() -> None:
    with pytest.raises(TypeError):
        RunStore()  # type: ignore[abstract]  # pylint: disable=abstract-class-instantiated  # the refusal is the test


# ---------------------------------------------------------------------- memory


def test_the_memory_store_drops_its_oldest_runs() -> None:
    store = MemoryRunStore(max_runs=2)
    for index in (1, 2, 3):
        store.save_run(a_run(f"run-{index}", minutes=index))
    assert [run.run_id for run in store.list_runs()] == ["run-3", "run-2"]
    assert store.get_run("run-1") is None
    with pytest.raises(ValueError, match="max_runs"):
        MemoryRunStore(max_runs=0)


# ---------------------------------------------------------------------- sqlite


def test_the_sqlite_store_outlives_its_object(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "er" / "runs.db"
    first = SQLiteRunStore(path)
    assert first.path == path
    run = a_run()
    run.tasks["load"] = a_success(key="k", result={"rows": 3})
    first.save_run(run)
    second = SQLiteRunStore(str(path))
    assert second.get_run("run-1").to_dict() == run.to_dict()
    assert second.find_idempotent("daily", "load", "k").result == {"rows": 3}


def test_the_sqlite_file_carries_a_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "runs.db"
    SQLiteRunStore(path)
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute("SELECT key, value FROM pipeline_meta").fetchall()
        assert rows == [("schema_version", "1")]
        connection.execute(
            "UPDATE pipeline_meta SET value = ? WHERE key = ?", ("99", "schema_version")
        )
        connection.commit()
    with pytest.raises(PipelineException, match="schema version 99 is not supported"):
        SQLiteRunStore(path)


def test_a_sqlite_store_that_cannot_be_opened_raises(tmp_path: Path) -> None:
    with pytest.raises(PipelineException, match="run store"):
        SQLiteRunStore(tmp_path)  # a directory, not a file
    blocker = tmp_path / "file.txt"
    blocker.write_text("not a directory", encoding="utf-8")
    with pytest.raises(PipelineException, match="run store"):
        SQLiteRunStore(blocker / "runs.db")


# ---------------------------------------------------------------------- the default store


@pytest.fixture
def fresh_default() -> Iterator[MemoryRunStore]:
    fresh = MemoryRunStore()
    previous = set_default_run_store(fresh)
    yield fresh
    set_default_run_store(previous)


def test_the_default_store_is_in_memory_and_can_be_replaced() -> None:
    original = default_run_store()
    assert isinstance(original, MemoryRunStore)
    replacement = MemoryRunStore()
    try:
        assert set_default_run_store(replacement) is original
        assert default_run_store() is replacement
        with pytest.raises(PipelineException, match="not a RunStore"):
            set_default_run_store("runs.db")  # type: ignore[arg-type]
        assert default_run_store() is replacement
    finally:
        set_default_run_store(original)
    assert default_run_store() is original


def test_a_run_without_a_store_lands_in_the_default_one(
    fresh_default: MemoryRunStore, bus: EventBus
) -> None:
    pipeline = Pipeline("defaulted")
    pipeline.task("only", lambda ctx: "ran")
    run = pipeline.run(bus=bus)
    assert fresh_default.get_run(run.run_id).to_dict() == run.to_dict()
    assert pipeline.resume(run.run_id, bus=bus).run_id == run.run_id


# ---------------------------------------------------------------------- checkpoints


class RecordingStore(MemoryRunStore):
    """A memory store that remembers every write, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[Any, ...]] = []

    def save_run(self, run: PipelineRun) -> None:
        tasks = {task_id: state.status.value for task_id, state in run.tasks.items()}
        self.writes.append(("run", run.status.value, tasks))
        super().save_run(run)

    def save_task(self, run_id: str, task: TaskRun) -> None:
        self.writes.append(("task", task.task, task.status.value, task.attempts))
        super().save_task(run_id, task)


def test_every_transition_is_written_as_it_happens(
    bus: EventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "pause", lambda _token, _seconds: False)

    def flaky(ctx: TaskContext) -> str:
        if ctx.attempt == 1:
            raise ConnectionError("once")
        return "through"

    def boom(_ctx: TaskContext) -> None:
        raise ValueError("boom")

    store = RecordingStore()
    pipeline = Pipeline("checkpointed", max_workers=1)
    pipeline.task("a", lambda ctx: "a")
    pipeline.task("b", flaky, depends_on=["a"], retry=RetryPolicy(max_attempts=2))
    pipeline.task("c", boom, depends_on=["b"])
    pipeline.task("d", lambda ctx: "never", depends_on=["c"])
    pipeline.run(store=store, bus=bus)
    assert store.writes == [
        ("run", "running", {"a": "pending", "b": "pending", "c": "pending", "d": "pending"}),
        ("task", "a", "running", 1),
        ("task", "a", "succeeded", 1),
        ("task", "b", "running", 1),
        ("task", "b", "running", 1),  # the failed first attempt, with its error
        ("task", "b", "running", 2),
        ("task", "b", "succeeded", 2),
        ("task", "c", "running", 1),
        ("task", "c", "failed", 1),
        ("task", "d", "skipped", 0),
        ("run", "failed", {"a": "succeeded", "b": "succeeded", "c": "failed", "d": "skipped"}),
    ]


def test_the_store_shows_a_run_in_progress(store: RunStore, bus: EventBus) -> None:
    entered, release = threading.Event(), threading.Event()

    def first(_ctx: TaskContext) -> str:
        entered.set()
        release.wait(WAIT)
        return "done"

    pipeline = Pipeline("in-progress")
    pipeline.task("first", first)
    pipeline.task("second", lambda ctx: "after", depends_on=["first"])
    run = pipeline.start(store=store, bus=bus)
    try:
        assert entered.wait(WAIT)
        stored = store.get_run(run.run_id)
        assert stored.status is RunStatus.RUNNING
        assert stored.done is False
        assert stored.tasks["first"].status is TaskStatus.RUNNING
        assert stored.tasks["first"].attempts == 1
        assert stored.tasks["second"].status is TaskStatus.PENDING
        asked = time.monotonic()
        assert stored.wait(WAIT) is False  # a snapshot: nothing will ever end it
        assert time.monotonic() - asked < WAIT / 2
    finally:
        release.set()
    assert run.wait(WAIT) is True
    assert store.get_run(run.run_id).to_dict() == run.to_dict()
    assert store.get_run(run.run_id).status is RunStatus.SUCCEEDED


def test_a_store_that_cannot_write_does_not_stop_the_run(bus: EventBus) -> None:
    class ReadOnly(MemoryRunStore):
        def save_run(self, run: PipelineRun) -> None:
            raise PipelineException("disk full")

        def save_task(self, run_id: str, task: TaskRun) -> None:
            raise PipelineException("disk full")

    store = ReadOnly()
    pipeline = Pipeline("unrecorded")
    pipeline.task("a", lambda ctx: 1)
    pipeline.task("b", lambda ctx: ctx.results["a"] + 1, depends_on=["a"])
    run = pipeline.run(store=store, bus=bus)
    assert run.status is RunStatus.SUCCEEDED
    assert run.tasks["b"].result == 2
    assert store.list_runs() == []


def test_a_store_that_breaks_its_contract_fails_the_task_not_the_run_loop(bus: EventBus) -> None:
    class Misbehaving(MemoryRunStore):
        raised = False

        def save_task(self, run_id: str, task: TaskRun) -> None:
            if not self.raised:
                self.raised = True
                raise RuntimeError("not a PipelineException")
            super().save_task(run_id, task)

    ran: list[str] = []
    pipeline = Pipeline("misbehaving-store")
    pipeline.task("only", lambda ctx: ran.append("only"))
    run = pipeline.run(store=Misbehaving(), bus=bus)
    assert ran == []
    assert run.tasks["only"].status is TaskStatus.FAILED
    assert run.tasks["only"].error == "PipelineException: the task ended without an outcome"
    assert run.status is RunStatus.FAILED
    assert [event.type for event in reversed(bus.recent())] == [
        "pipeline.started",
        "task.failed",
        "pipeline.failed",
    ]


# ---------------------------------------------------------------------- resume


def build_etl(ran: list[str], failing: frozenset[str] = frozenset()) -> Pipeline:
    def step(ctx: TaskContext) -> dict[str, Any]:
        ran.append(ctx.task)
        if ctx.task in failing:
            raise ValueError(f"{ctx.task} broke")
        return {"task": ctx.task, "date": ctx.params["date"], "upstream": sorted(ctx.results)}

    pipeline = Pipeline("etl", params={"date": "a-default"})
    pipeline.task("extract", step)
    pipeline.task("transform", step, depends_on=["extract"])
    pipeline.task("load", step, depends_on=["transform"])
    pipeline.task("audit", step, depends_on=["extract"])
    return pipeline


def test_resume_keeps_what_succeeded_and_runs_the_rest(tmp_path: Path, bus: EventBus) -> None:
    path = tmp_path / "runs.db"
    first_ran: list[str] = []
    first = build_etl(first_ran, frozenset({"transform"})).run(
        params={"date": "2026-10-08"}, store=SQLiteRunStore(path), bus=bus
    )
    assert sorted(first_ran) == ["audit", "extract", "transform"]
    assert first.status is RunStatus.FAILED
    assert first.tasks["load"].status is TaskStatus.SKIPPED

    # A new process: another store object on the same file, another Pipeline object.
    store = SQLiteRunStore(path)
    second_ran: list[str] = []
    resumed = build_etl(second_ran).resume(first.run_id, store=store, bus=bus)
    assert second_ran == ["transform", "load"]
    assert resumed.run_id == first.run_id
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.error is None
    assert resumed.params == {"date": "2026-10-08"}  # the run's parameters, not the defaults
    assert resumed.started_at == first.started_at
    assert {state.status for state in resumed.tasks.values()} == {TaskStatus.SUCCEEDED}
    assert list(resumed.tasks) == ["extract", "transform", "audit", "load"]
    assert resumed.tasks["extract"].finished_at == first.tasks["extract"].finished_at
    assert resumed.tasks["extract"].attempts == 1
    assert resumed.tasks["transform"].result == {
        "task": "transform",
        "date": "2026-10-08",
        "upstream": ["extract"],
    }
    assert resumed.tasks["load"].result["upstream"] == ["extract", "transform"]
    assert resumed.tasks["transform"].error is None
    assert store.get_run(first.run_id).to_dict() == resumed.to_dict()
    assert [run.run_id for run in store.list_runs()] == [first.run_id]


def test_resume_hands_stored_results_to_the_remaining_tasks(store: RunStore, bus: EventBus) -> None:
    marker = object()

    def build(fail: bool) -> Pipeline:
        def use(ctx: TaskContext) -> dict[str, Any]:
            if fail:
                raise ValueError("not yet")
            return dict(ctx.results)

        pipeline = Pipeline("handover")
        pipeline.task("numbers", lambda ctx: (1, 2, 3))
        pipeline.task("object", lambda ctx: marker)
        pipeline.task("use", use, depends_on=["numbers", "object"])
        return pipeline

    first = build(fail=True).run(store=store, bus=bus)
    assert first.tasks["numbers"].result == (1, 2, 3)
    resumed = build(fail=False).resume(first.run_id, store=store, bus=bus)
    assert resumed.tasks["use"].result == {"numbers": [1, 2, 3], "object": repr(marker)}
    assert resumed.tasks["object"].result_is_repr is True
    assert resumed.tasks["numbers"].result_is_repr is False


def test_resume_finishes_a_cancelled_run(store: RunStore, bus: EventBus) -> None:
    ran: list[str] = []
    entered = threading.Event()

    def first(ctx: TaskContext) -> str:
        ran.append("first")
        if len(ran) == 1:  # the first time round, stay until the run is cancelled
            entered.set()
            assert until(lambda: ctx.cancel.is_cancelled)
            ctx.cancel.raise_if_cancelled()
        return "first"

    def build() -> Pipeline:
        pipeline = Pipeline("stopped")
        pipeline.task("first", first)
        pipeline.task("second", lambda ctx: ran.append("second"), depends_on=["first"])
        return pipeline

    run = build().start(store=store, bus=bus)
    assert entered.wait(WAIT)
    run.cancel()
    assert run.wait(WAIT) is True
    assert run.status is RunStatus.CANCELLED
    assert store.get_run(run.run_id).status is RunStatus.CANCELLED
    resumed = build().resume(run.run_id, store=store, bus=bus)
    assert ran == ["first", "first", "second"]
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.cancel_token is not run.cancel_token


def test_resume_refuses_what_it_cannot_continue(store: RunStore, bus: EventBus) -> None:
    ran: list[str] = []
    pipeline = Pipeline("one")
    pipeline.task("only", lambda ctx: ran.append("only"))
    with pytest.raises(PipelineException, match="unknown run 'missing'"):
        pipeline.resume("missing", store=store, bus=bus)
    run = pipeline.run(store=store, bus=bus)
    other = Pipeline("two")
    other.task("only", lambda ctx: ran.append("other"))
    with pytest.raises(PipelineException, match="belongs to pipeline 'one', not 'two'"):
        other.resume(run.run_id, store=store, bus=bus)
    assert ran == ["only"]


def test_resuming_a_succeeded_run_runs_nothing(store: RunStore, bus: EventBus) -> None:
    ran: list[str] = []
    pipeline = Pipeline("finished")
    pipeline.task("only", lambda ctx: ran.append("only"))
    run = pipeline.run(store=store, bus=bus)
    events_before = len(bus.recent())
    again = pipeline.resume(run.run_id, store=store, bus=bus)
    assert ran == ["only"]
    assert again.to_dict() == run.to_dict()
    assert again.done is True
    assert len(bus.recent()) == events_before


def test_resume_checks_the_definition_first(store: RunStore, bus: EventBus) -> None:
    def boom(_ctx: TaskContext) -> None:
        raise ValueError("boom")

    failing = Pipeline("changed")
    failing.task("a", boom)
    run = failing.run(store=store, bus=bus)
    changed = Pipeline("changed")
    changed.task("a", lambda ctx: None, depends_on=["gone"])
    with pytest.raises(PipelineDefinitionException, match="unknown task 'gone'"):
        changed.resume(run.run_id, store=store, bus=bus)
    assert store.get_run(run.run_id).status is RunStatus.FAILED


def test_resume_follows_a_changed_definition(store: RunStore, bus: EventBus) -> None:
    def boom(_ctx: TaskContext) -> None:
        raise ValueError("boom")

    before = Pipeline("evolving")
    before.task("keep", lambda ctx: "kept")
    before.task("drop", boom)
    run = before.run(store=store, bus=bus)
    after = Pipeline("evolving")
    after.task("new", lambda ctx: ctx.results["keep"], depends_on=["keep"])
    after.task("keep", lambda ctx: "ran again")
    resumed = after.resume(run.run_id, store=store, bus=bus)
    assert list(resumed.tasks) == ["keep", "new"]
    assert resumed.tasks["keep"].result == "kept"
    assert resumed.tasks["new"].result == "kept"
    assert list(store.get_run(run.run_id).tasks) == ["keep", "new"]


# ---------------------------------------------------------------------- idempotency


def build_billing(charged: list[str], name: str = "billing", fail: bool = False) -> Pipeline:
    def charge(ctx: TaskContext) -> dict[str, str]:
        charged.append(ctx.params["date"])
        if fail:
            raise ValueError("card declined")
        return {"charged": ctx.params["date"]}

    pipeline = Pipeline(name)
    pipeline.task("charge", charge, idempotency_key="charge-${params.date}")
    pipeline.task("receipt", lambda ctx: ctx.results["charge"], depends_on=["charge"])
    return pipeline


def test_a_key_that_already_succeeded_skips_the_task_and_reuses_its_result(
    store: RunStore, bus: EventBus
) -> None:
    charged: list[str] = []
    first = build_billing(charged).run(params={"date": "2026-10-08"}, store=store, bus=bus)
    assert first.tasks["charge"].status is TaskStatus.SUCCEEDED
    assert first.tasks["charge"].idempotency_key == "charge-2026-10-08"

    second = build_billing(charged).run(params={"date": "2026-10-08"}, store=store, bus=bus)
    state = second.tasks["charge"]
    assert charged == ["2026-10-08"]  # not charged twice
    assert state.status is TaskStatus.SKIPPED
    assert state.reason == "idempotent"
    assert state.result == {"charged": "2026-10-08"}
    assert state.attempts == 0
    assert state.idempotency_key == "charge-2026-10-08"
    assert state.satisfied is True
    assert second.tasks["receipt"].status is TaskStatus.SUCCEEDED
    assert second.tasks["receipt"].result == {"charged": "2026-10-08"}
    assert second.status is RunStatus.SUCCEEDED
    assert second.run_id != first.run_id

    third = build_billing(charged).run(params={"date": "2026-10-09"}, store=store, bus=bus)
    assert charged == ["2026-10-08", "2026-10-09"]  # another key
    assert third.tasks["charge"].status is TaskStatus.SUCCEEDED

    fourth = build_billing(charged).run(params={"date": "2026-10-08"}, store=store, bus=bus)
    assert fourth.tasks["charge"].reason == "idempotent"  # a skipped run does not hide the original
    assert charged == ["2026-10-08", "2026-10-09"]


def test_a_failed_execution_does_not_count(store: RunStore, bus: EventBus) -> None:
    charged: list[str] = []
    failed = build_billing(charged, fail=True).run(params={"date": "d"}, store=store, bus=bus)
    assert failed.tasks["charge"].status is TaskStatus.FAILED
    assert failed.tasks["charge"].idempotency_key == "charge-d"
    retried = build_billing(charged).run(params={"date": "d"}, store=store, bus=bus)
    assert retried.tasks["charge"].status is TaskStatus.SUCCEEDED
    assert charged == ["d", "d"]


def test_a_key_belongs_to_one_pipeline_and_one_task(store: RunStore, bus: EventBus) -> None:
    charged: list[str] = []
    build_billing(charged, "billing").run(params={"date": "d"}, store=store, bus=bus)
    other = build_billing(charged, "other-billing").run(params={"date": "d"}, store=store, bus=bus)
    assert other.tasks["charge"].status is TaskStatus.SUCCEEDED
    assert charged == ["d", "d"]
    renamed = Pipeline("billing")
    renamed.task("charge-again", lambda ctx: charged.append("again"), idempotency_key="charge-d")
    assert renamed.run(store=store, bus=bus).tasks["charge-again"].status is TaskStatus.SUCCEEDED


def test_a_key_is_remembered_after_a_restart(tmp_path: Path, bus: EventBus) -> None:
    path = tmp_path / "runs.db"
    charged: list[str] = []
    build_billing(charged).run(params={"date": "d"}, store=SQLiteRunStore(path), bus=bus)
    later = build_billing(charged).run(params={"date": "d"}, store=SQLiteRunStore(path), bus=bus)
    assert later.tasks["charge"].reason == "idempotent"
    assert later.tasks["charge"].result == {"charged": "d"}
    assert charged == ["d"]


def test_a_key_is_rendered_as_text(store: RunStore, bus: EventBus) -> None:
    pipeline = Pipeline("numbered")
    pipeline.task("batch", lambda ctx: "done", idempotency_key="${params.number}")
    pipeline.task("fixed", lambda ctx: "done", idempotency_key="always-the-same")
    run = pipeline.run(params={"number": 5}, store=store, bus=bus)
    assert run.tasks["batch"].idempotency_key == "5"
    assert run.tasks["fixed"].idempotency_key == "always-the-same"
    assert store.find_idempotent("numbered", "batch", "5").result == "done"


def test_a_condition_is_checked_before_the_key(store: RunStore, bus: EventBus) -> None:
    pipeline = Pipeline("conditional-key")
    pipeline.task("skipped", lambda ctx: "ran", when="on_failure", idempotency_key="k")
    run = pipeline.run(store=store, bus=bus)
    assert run.tasks["skipped"].reason == "condition"
    assert run.tasks["skipped"].idempotency_key is None


def test_a_key_that_cannot_be_looked_up_fails_the_task_without_running_it(bus: EventBus) -> None:
    class Offline(MemoryRunStore):
        def find_idempotent(self, pipeline: str, task: str, key: str) -> TaskRun | None:
            raise PipelineException("store offline")

    charged: list[str] = []
    run = build_billing(charged).run(params={"date": "d"}, store=Offline(), bus=bus)
    assert charged == []
    assert run.tasks["charge"].status is TaskStatus.FAILED
    assert run.tasks["charge"].error == "PipelineException: store offline"
    assert run.tasks["receipt"].reason == "upstream_failed"
    assert run.status is RunStatus.FAILED


# ---------------------------------------------------------------------- history


def test_the_history_of_a_pipeline(store: RunStore, bus: EventBus) -> None:
    def build(name: str, fail: bool) -> Pipeline:
        def step(_ctx: TaskContext) -> str:
            if fail:
                raise ValueError("boom")
            return "ok"

        pipeline = Pipeline(name)
        pipeline.task("step", step)
        return pipeline

    first = build("nightly", fail=False).run(store=store, bus=bus)
    second = build("nightly", fail=True).run(store=store, bus=bus)
    other = build("hourly", fail=False).run(store=store, bus=bus)
    history = store.list_runs("nightly")
    assert [run.run_id for run in history] == [second.run_id, first.run_id]
    assert [run.status for run in history] == [RunStatus.FAILED, RunStatus.SUCCEEDED]
    assert history[0].tasks["step"].error == "ValueError: boom"
    assert history[0].error == "did not succeed: step"
    assert all(run.done for run in history)
    assert [run.run_id for run in store.list_runs(limit=1)] == [other.run_id]
