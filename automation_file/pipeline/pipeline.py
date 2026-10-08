"""The pipeline: a named set of tasks with dependencies, and the ways to run it.

.. code-block:: python

    from automation_file.pipeline import Pipeline, RetryPolicy

    pipeline = Pipeline("daily-report")
    pipeline.task("download", ["FA_storage_copy", {"source": "s3://in/report.csv",
                                                   "target": "local:///tmp/report.csv"}])
    pipeline.task("validate", validate, depends_on=["download"],
                  retry=RetryPolicy(max_attempts=3, backoff_base=1.0), timeout=60.0)
    run = pipeline.run(params={"date": "2026-10-08"})
    run.status, run.tasks["validate"].result
"""

from __future__ import annotations

import os
import threading
from collections.abc import Collection, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from automation_file.core.progress import CancellationToken
from automation_file.events import EventBus, current_actor, event_bus, new_correlation_id
from automation_file.logging_config import file_automation_logger
from automation_file.pipeline.definition import (
    SCHEMA_VERSION,
    action_problems,
    depends_on_problems,
    idempotency_key_problems,
    load_definition,
    params_problems,
    retry_from_dict,
    task_to_dict,
    timeout_problems,
    validate_definition,
    when_problems,
)
from automation_file.pipeline.errors import PipelineDefinitionException, PipelineException
from automation_file.pipeline.graph import dependency_problems, task_levels, upstream_tasks
from automation_file.pipeline.model import (
    ON_SUCCESS,
    Condition,
    PipelineRun,
    RetryPolicy,
    RunStatus,
    Schedule,
    Task,
    TaskRun,
    TaskStatus,
    TaskWork,
    utc_now,
)
from automation_file.pipeline.runner import Engine, Plan, Services
from automation_file.pipeline.store import RunStore, default_run_store
from automation_file.pipeline.substitution import (
    NAME_RULE,
    action_reference_problems,
    is_name,
    text_problems,
)

if TYPE_CHECKING:
    from automation_file.core.action_registry import ActionRegistry

DEFAULT_MAX_WORKERS = 4


def _shared_registry() -> ActionRegistry:
    """Return the registry of the shared executor (imported late: it is built at import)."""
    from automation_file.core.action_executor import executor

    return executor.registry


def _task_problems(task: Task, taken: Collection[str]) -> list[str]:
    path = f"tasks.{task.task_id}"
    if not is_name(task.task_id):
        return [f"{path}: invalid task ID, {NAME_RULE}"]
    problems: list[str] = []
    if task.task_id in taken:
        problems.append(f"{path}: duplicate task ID")
    if not callable(task.work):
        problems.extend(action_problems(task.work, f"{path}.action"))
    problems.extend(depends_on_problems(task.depends_on, f"{path}.depends_on"))
    if task.timeout is not None:
        problems.extend(timeout_problems(task.timeout, f"{path}.timeout"))
    if not callable(task.when):
        problems.extend(when_problems(task.when, f"{path}.when"))
    if task.idempotency_key is not None:
        problems.extend(idempotency_key_problems(task.idempotency_key, f"{path}.idempotency_key"))
    return problems


def _carried_over(earlier: TaskRun | None, fresh: TaskRun) -> TaskRun:
    """Return the stored state of a task that succeeded, else the fresh one to run again."""
    if earlier is None or earlier.status is not TaskStatus.SUCCEEDED:
        return fresh
    earlier.level = fresh.level
    return earlier


def _run_in_background(engine: Engine) -> None:
    try:
        engine.execute()
    except Exception as error:  # pylint: disable=broad-except
        # Boundary of the background thread: the engine has already marked the run failed.
        file_automation_logger.error(
            "pipeline %s run %s ended with %r", engine.run.pipeline, engine.run.run_id, error
        )


class Pipeline:
    """A named set of tasks, run in dependency order with independent tasks in parallel.

    ``max_workers`` bounds how many tasks run at once. ``params`` are defaults
    that ``run(params=...)`` adds to or overrides. ``schedule`` is kept for the
    scheduler and not acted on here. ``registry`` is where action tasks are looked
    up; it defaults to the shared executor's registry.
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        max_workers: int = DEFAULT_MAX_WORKERS,
        *,
        params: Mapping[str, Any] | None = None,
        schedule: Schedule | None = None,
        registry: ActionRegistry | None = None,
    ) -> None:
        problems: list[str] = []
        if not (isinstance(name, str) and name.strip()):
            problems.append(f"name: expected a non-empty string, got {name!r}")
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            problems.append(f"max_workers: expected an integer >= 1, got {max_workers!r}")
        if params is not None:
            problems.extend(params_problems(params))
        if problems:
            raise PipelineDefinitionException(problems)
        self.name = name
        self.description = description
        self.max_workers = max_workers
        self.params: dict[str, Any] = dict(params or {})
        self.schedule = schedule
        self._registry = registry
        self._tasks: dict[str, Task] = {}

    def __repr__(self) -> str:
        return f"Pipeline({self.name!r}, tasks={list(self._tasks)})"

    @property
    def tasks(self) -> tuple[Task, ...]:
        """The tasks in the order they were added."""
        return tuple(self._tasks.values())

    # ------------------------------------------------------------------ building

    def task(
        self,
        task_id: str,
        work: TaskWork,
        *,
        depends_on: Iterable[str] | str | None = None,
        retry: RetryPolicy | None = None,
        timeout: float | None = None,
        when: str | Condition = ON_SUCCESS,
        idempotency_key: str | None = None,
    ) -> Task:
        """Add a task and return it.

        ``work`` is a callable taking a :class:`TaskContext`, or an action
        (``[name]``, ``[name, {kwargs}]``, ``[name, [args]]``) whose string
        arguments may hold ``${params.<name>}`` and ``${tasks.<id>.result}``.

        ``timeout`` is the budget in seconds for the whole task, every attempt and
        the waits between them included. A thread cannot be killed: when the
        budget is spent the task is recorded as ``timeout``, its cancellation
        token is set and the run goes on, but the callable keeps running until it
        returns. A long callable must therefore watch ``context.cancel``.

        ``when`` is ``"on_success"`` (every dependency succeeded), ``"on_failure"``
        (at least one failed, timed out or was cancelled), ``"always"``, or a
        callable ``(TaskContext) -> bool``. ``idempotency_key`` (with
        ``${params.<name>}`` placeholders) skips the task when the store already
        holds a succeeded execution under the same key, and reuses its result.

        A dependency may name a task that is added later; the graph is checked
        when the pipeline runs. Anything else that is wrong raises
        :class:`PipelineDefinitionException` here.
        """
        wanted = (depends_on,) if isinstance(depends_on, str) else tuple(depends_on or ())
        added = Task(
            task_id=task_id,
            work=work,
            depends_on=wanted,
            retry=RetryPolicy() if retry is None else retry,
            timeout=timeout,
            when=when,
            idempotency_key=idempotency_key,
        )
        problems = _task_problems(added, self._tasks)
        if problems:
            raise PipelineDefinitionException(problems)
        self._tasks[task_id] = added
        return added

    def _dependencies(self) -> dict[str, tuple[str, ...]]:
        return {task.task_id: task.depends_on for task in self._tasks.values()}

    def problems(self) -> list[str]:
        """Return what keeps the pipeline from running, each finding with its path.

        Checked here: an empty pipeline, unknown, repeated and self dependencies,
        cycles, and placeholders that are malformed or name a task that is not
        upstream.
        """
        if not self._tasks:
            return ["tasks: at least one task is required"]
        dependencies = self._dependencies()
        found = dependency_problems(dependencies)
        upstream = upstream_tasks(dependencies)
        for task in self._tasks.values():
            if not callable(task.work):
                found.extend(
                    action_reference_problems(
                        task.work, f"tasks.{task.task_id}.action", upstream[task.task_id]
                    )
                )
        return found

    def validate(self) -> None:
        """Raise :class:`PipelineDefinitionException` when :meth:`problems` finds any."""
        problems = self.problems()
        if problems:
            raise PipelineDefinitionException(problems)

    # ------------------------------------------------------------------ running

    def run(
        self,
        params: Mapping[str, Any] | None = None,
        *,
        dry_run: bool = False,
        store: RunStore | None = None,
        cancel: CancellationToken | None = None,
        bus: EventBus | None = None,
    ) -> PipelineRun:
        """Run the pipeline in the calling thread and return the finished run.

        A task that fails does not raise here: look at ``run.status`` and
        ``run.tasks``. What does raise, before anything runs, is a definition
        problem (:class:`PipelineDefinitionException`): a cycle, an unknown
        dependency, a placeholder for a parameter the run was not given.

        ``dry_run=True`` executes nothing, records nothing and publishes nothing:
        every task comes back ``planned``, in dependency order with its level,
        and an unknown action name or a missing parameter is reported in the
        task's ``error``. ``store`` records the run (the default store when
        omitted), ``cancel`` stops it from outside, and ``bus`` receives its
        events instead of the process-wide bus.
        """
        merged = {**self.params, **(params or {})}
        if dry_run:
            return self._dry_run(merged)
        engine = self._engine(merged, store, cancel, bus)
        engine.execute()
        return engine.run

    def start(
        self,
        params: Mapping[str, Any] | None = None,
        *,
        store: RunStore | None = None,
        cancel: CancellationToken | None = None,
        bus: EventBus | None = None,
    ) -> PipelineRun:
        """Run the pipeline on a background thread and return its run at once.

        ``run.wait(timeout)`` blocks until it has ended and ``run.cancel()``
        stops it. A definition problem raises here, before the thread starts.
        """
        engine = self._engine({**self.params, **(params or {})}, store, cancel, bus)
        threading.Thread(
            target=_run_in_background, args=(engine,), name=f"pipeline-{self.name}"
        ).start()
        return engine.run

    def resume(
        self,
        run_id: str,
        *,
        store: RunStore | None = None,
        cancel: CancellationToken | None = None,
        bus: EventBus | None = None,
    ) -> PipelineRun:
        """Continue a stored run: keep the tasks that succeeded, run the rest.

        The run keeps its ID and its parameters. Results come from the store, so
        they are JSON values (or a ``repr`` when ``result_is_repr`` is set). A run
        that already succeeded is returned as stored. Do not resume a run that is
        still executing somewhere else.
        """
        chosen = default_run_store() if store is None else store
        earlier = chosen.get_run(run_id)
        if earlier is None:
            raise PipelineException(f"unknown run {run_id!r}")
        if earlier.pipeline != self.name:
            raise PipelineException(
                f"run {run_id!r} belongs to pipeline {earlier.pipeline!r}, not {self.name!r}"
            )
        if earlier.status is RunStatus.SUCCEEDED:
            return earlier
        plan = self._plan(earlier.params)
        run = self._blank_run(plan, earlier.params, cancel)
        run.run_id = run_id
        run.started_at = earlier.started_at or run.started_at
        run.tasks = {
            task_id: _carried_over(earlier.tasks.get(task_id), state)
            for task_id, state in run.tasks.items()
        }
        Engine(plan, run, self._services(chosen, bus)).execute()
        return run

    def _plan(self, params: Mapping[str, Any], *, lenient: bool = False) -> Plan:
        """Order the tasks, or raise with every problem. ``lenient`` leaves missing parameters."""
        problems = self.problems()
        if not problems and not lenient:
            problems = [note for notes in self._input_problems(params).values() for note in notes]
        if problems:
            raise PipelineDefinitionException(problems)
        dependencies = self._dependencies()
        levels = task_levels(dependencies)
        return Plan(
            pipeline=self.name,
            tasks=tuple(self._tasks[task_id] for task_id in levels),
            levels=levels,
            upstream=upstream_tasks(dependencies),
            max_workers=self.max_workers,
        )

    def _input_problems(self, params: Mapping[str, Any]) -> dict[str, list[str]]:
        """Return, per task, the parameters its action or key uses and the run was not given."""
        upstream = upstream_tasks(self._dependencies())
        found: dict[str, list[str]] = {}
        for task in self._tasks.values():
            path = f"tasks.{task.task_id}"
            notes: list[str] = []
            if not callable(task.work):
                notes.extend(
                    action_reference_problems(
                        task.work, f"{path}.action", upstream[task.task_id], params
                    )
                )
            if task.idempotency_key is not None:
                notes.extend(
                    f"{path}.idempotency_key: {problem}"
                    for problem in text_problems(task.idempotency_key, None, params)
                )
            if notes:
                found[task.task_id] = notes
        return found

    def _blank_run(
        self, plan: Plan, params: Mapping[str, Any], cancel: CancellationToken | None
    ) -> PipelineRun:
        return PipelineRun(
            run_id=new_correlation_id(),
            pipeline=self.name,
            params=dict(params),
            tasks={
                task.task_id: TaskRun(task=task.task_id, level=plan.levels[task.task_id])
                for task in plan.tasks
            },
            started_at=utc_now(),
            cancel_token=CancellationToken() if cancel is None else cancel,
        )

    def _action_registry(self) -> ActionRegistry:
        return _shared_registry() if self._registry is None else self._registry

    def _services(self, store: RunStore | None, bus: EventBus | None) -> Services:
        return Services(
            store=default_run_store() if store is None else store,
            bus=event_bus if bus is None else bus,
            registry=self._action_registry(),
            actor=current_actor(),
        )

    def _engine(
        self,
        params: Mapping[str, Any],
        store: RunStore | None,
        cancel: CancellationToken | None,
        bus: EventBus | None,
    ) -> Engine:
        plan = self._plan(params)
        return Engine(plan, self._blank_run(plan, params, cancel), self._services(store, bus))

    def _dry_run(self, params: Mapping[str, Any]) -> PipelineRun:
        plan = self._plan(params, lenient=True)
        run = self._blank_run(plan, params, None)
        run.dry_run = True
        registry = self._action_registry()
        notes = self._input_problems(params)
        for task in plan.tasks:
            state = run.tasks[task.task_id]
            state.status = TaskStatus.PLANNED
            found = list(notes.get(task.task_id, ()))
            name = task.action_name
            if name is not None and registry.resolve(name) is None:
                found.append(f"tasks.{task.task_id}.action[0]: unknown action {name!r}")
            state.error = "; ".join(found) or None
        flagged = [state.task for state in run.tasks.values() if state.error is not None]
        run.status = RunStatus.FAILED if flagged else RunStatus.SUCCEEDED
        run.error = f"would not run as planned: {', '.join(flagged)}" if flagged else None
        run.finished_at = utc_now()
        run.mark_done()
        return run

    # ------------------------------------------------------------------ definitions

    @classmethod
    def from_dict(
        cls, document: Mapping[str, Any], *, registry: ActionRegistry | None = None
    ) -> Pipeline:
        """Build a pipeline from a definition document (``schema_version: 1``).

        Raises :class:`PipelineDefinitionException` carrying every problem
        :func:`validate_definition` finds.
        """
        problems = validate_definition(document)
        if problems:
            raise PipelineDefinitionException(problems)
        schedule = document.get("schedule")
        pipeline = cls(
            document["name"],
            description=document.get("description", ""),
            max_workers=document.get("max_workers", DEFAULT_MAX_WORKERS),
            params=document.get("params"),
            schedule=None if schedule is None else Schedule(**schedule),
            registry=registry,
        )
        for task_id, spec in document["tasks"].items():
            pipeline.task(
                task_id,
                spec["action"],
                depends_on=spec.get("depends_on"),
                retry=retry_from_dict(spec["retry"]) if "retry" in spec else None,
                timeout=spec.get("timeout"),
                when=spec.get("when", ON_SUCCESS),
                idempotency_key=spec.get("idempotency_key"),
            )
        return pipeline

    @classmethod
    def from_file(
        cls, path: str | os.PathLike[str], *, registry: ActionRegistry | None = None
    ) -> Pipeline:
        """Build a pipeline from a ``.yaml`` / ``.yml`` or ``.json`` definition file."""
        return cls.from_dict(load_definition(path), registry=registry)

    def to_dict(self) -> dict[str, Any]:
        """Return the definition document of this pipeline.

        A default (``when: on_success``, no retry ...) is left out. A pipeline
        with a Python callable in it has no document and raises
        :class:`PipelineDefinitionException`.
        """
        document: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "name": self.name}
        if self.description:
            document["description"] = self.description
        document["max_workers"] = self.max_workers
        if self.schedule is not None:
            document["schedule"] = self.schedule.to_dict()
        if self.params:
            document["params"] = dict(self.params)
        document["tasks"] = {task.task_id: task_to_dict(task) for task in self._tasks.values()}
        return document
