"""The Pipelines service: check, run, follow and store pipeline definitions.

.. code-block:: python

    from automation_file.app import app_services

    pipelines = app_services().pipelines
    draft = pipelines.load("pipelines/daily-report.yaml")
    pipelines.validate(draft)                         # [] or a list of Problem
    plan = pipelines.dry_run(draft, {"date": "2026-10-08"})
    run = pipelines.start(draft, {"date": "2026-10-08"})   # returns at once
    pipelines.status(run["run_id"])["status"]         # "running", then "succeeded" ...
    pipelines.cancel(run["run_id"])

Every method takes a :class:`~automation_file.app.pipeline_draft.PipelineDraft`
or a definition mapping, and returns plain dictionaries: a run is
``PipelineRun.to_dict()`` with its secrets masked and an ``active`` flag that
says whether this process is still executing it.

A definition is saved as ``.yaml`` / ``.yml`` / ``.json``. The canvas layout goes
into a second file next to it (``<file>.layout.json``), because a definition
refuses unknown keys and a layout is no part of what runs.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from automation_file.app.arguments import ActionInfo, describe_action
from automation_file.app.errors import AppException
from automation_file.app.masking import mask_secrets
from automation_file.app.pipeline_draft import DEFAULT_NAME, PipelineDraft, Problem
from automation_file.core.json_store import read_action_json, write_action_json
from automation_file.core.progress import CancellationToken
from automation_file.events import EventBus, event_bus
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.pipeline import (
    MemoryRunStore,
    Pipeline,
    PipelineDefinitionException,
    PipelineException,
    PipelineRun,
    RunStatus,
    RunStore,
    default_run_store,
    load_definition,
    validate_definition,
)
from automation_file.pipeline.definition import retry_from_dict
from automation_file.pipeline.graph import upstream_tasks

if TYPE_CHECKING:
    from automation_file.core.action_registry import ActionRegistry

Definition = PipelineDraft | Mapping[str, Any]

LAYOUT_SUFFIX = ".layout.json"
_JSON_SUFFIX = ".json"
_YAML_SUFFIXES = (".yaml", ".yml")
_DEFAULT_HISTORY = 20
_DEFAULT_EVENTS = 200
_MAX_TRACKED = 200
_SCAN_LIMIT = 200


@dataclass
class _Tracked:
    """A run this service started or resumed: how to stop it and how to tell it has ended."""

    token: CancellationToken
    run: PipelineRun | None = None
    thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        if self.run is not None:
            return not self.run.done
        return self.thread is not None and self.thread.is_alive()


def layout_path(path: str | os.PathLike[str]) -> Path:
    """Return where the canvas layout of the definition file ``path`` is kept."""
    source = Path(path)
    return source.with_name(source.name + LAYOUT_SUFFIX)


def _constant(value: Any) -> Callable[[Any], Any]:
    return lambda _context: value


def _listed(spec: Any) -> list[str]:
    wanted = spec.get("depends_on", []) if isinstance(spec, Mapping) else []
    return [item for item in wanted if isinstance(item, str)] if isinstance(wanted, list) else []


class PipelineService:
    """Validation, dry run, background runs, history and definition files.

    ``store`` is where runs are recorded; without one the default run store is
    looked up on every call, so :func:`~automation_file.pipeline.set_default_run_store`
    takes effect. ``registry`` is where action names are looked up (the shared
    executor's by default) and ``bus`` receives the events of the runs.
    """

    def __init__(
        self,
        store: RunStore | None = None,
        *,
        registry: ActionRegistry | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._bus = bus
        self._lock = threading.Lock()
        self._tracked: dict[str, _Tracked] = {}

    # ------------------------------------------------------------------ actions

    def action_names(self) -> list[str]:
        """Return the name of every registered action, sorted."""
        return sorted(self._action_registry().event_dict)

    def describe_action(self, name: str) -> ActionInfo:
        """Return the parameters and the summary of the action ``name``."""
        return describe_action(name, self._action_registry().resolve(name))

    # ------------------------------------------------------------------ drafts and files

    def new_draft(self, name: str = DEFAULT_NAME) -> PipelineDraft:
        """Return an empty draft."""
        return PipelineDraft(name)

    def load(self, path: str | os.PathLike[str]) -> PipelineDraft:
        """Read a definition file into a draft, with its stored canvas layout when there is one.

        A file that cannot be read or parsed raises
        :class:`~automation_file.pipeline.PipelineDefinitionException`. A file
        that parses but is not a valid definition still opens: what is wrong
        with it is in ``draft.load_notes`` and in :meth:`validate`.
        """
        draft = PipelineDraft.from_definition(load_definition(path))
        sidecar = layout_path(path)
        if sidecar.is_file():
            try:
                draft.apply_layout(read_action_json(str(sidecar)))
            except FileAutomationException as error:
                file_automation_logger.warning(
                    "pipelines: ignoring the layout %s: %r", sidecar, error
                )
        draft.mark_saved()
        return draft

    def save(self, draft: PipelineDraft, path: str | os.PathLike[str]) -> str:
        """Write the draft's definition to ``path`` and its layout next to it; return the path.

        The suffix picks the format: ``.yaml`` / ``.yml`` or ``.json``. A draft
        that is not valid yet can be saved; validation is a separate step.
        """
        target = Path(path)
        suffix = target.suffix.lower()
        definition = draft.to_definition()
        if suffix == _JSON_SUFFIX:
            write_action_json(str(target), definition)
        elif suffix in _YAML_SUFFIXES:
            _write_yaml(target, definition)
        else:
            raise AppException(f"{target}: save a definition as .yaml, .yml or .json")
        write_action_json(str(layout_path(target)), draft.layout())
        draft.mark_saved()
        file_automation_logger.info("pipelines: saved %s", target)
        return str(target)

    # ------------------------------------------------------------------ checks

    def validate(self, definition: Definition) -> list[Problem]:
        """Return every problem of the definition, each with the path of the entry it is about.

        Next to what :func:`~automation_file.pipeline.validate_definition`
        finds, an action name the registry does not know is a problem too.
        """
        document = _document(definition)
        tasks = document.get("tasks")
        task_ids = tuple(tasks) if isinstance(tasks, Mapping) else ()
        problems = [Problem.parse(text, task_ids) for text in validate_definition(document)]
        registry = self._action_registry()
        for task_id, spec in tasks.items() if isinstance(tasks, Mapping) else ():
            action = spec.get("action") if isinstance(spec, Mapping) else None
            if not (isinstance(action, list) and action and isinstance(action[0], str)):
                continue
            if action[0] and registry.resolve(action[0]) is None:
                problems.append(
                    Problem(
                        path=f"tasks.{task_id}.action[0]",
                        message=f"unknown action {action[0]!r}",
                        task=task_id,
                    )
                )
        return problems

    def dry_run(
        self, definition: Definition, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Plan a run without executing, recording or publishing anything.

        Every task comes back ``planned`` in dependency order; a task that would
        not run as planned says why in its ``error``.
        """
        run = self._pipeline(definition).run(params=params, dry_run=True)
        return self._view(run, active=False)

    def test_task(
        self,
        definition: Definition,
        task_id: str,
        params: Mapping[str, Any] | None = None,
        results: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one task alone and return ``{"run": ..., "events": [...]}``.

        The task's action really runs, with its retry policy and its timeout.
        Its upstream tasks do not: each is replaced by a stand-in that returns
        the value given for it in ``results`` (``None`` by default), so
        ``${tasks.<id>.result}`` placeholders have something to read. The test
        is recorded in no run store and published on no shared bus; its
        condition and its idempotency key are ignored.
        """
        document = _document(definition)
        tasks = document.get("tasks")
        if not isinstance(tasks, Mapping) or task_id not in tasks:
            raise AppException(f"the definition has no task {task_id!r}")
        own = [problem for problem in self.validate(document) if problem.task == task_id]
        if own:
            raise PipelineDefinitionException([str(problem) for problem in own])
        spec = tasks[task_id]
        upstream = upstream_tasks({key: _listed(item) for key, item in tasks.items()})[task_id]
        probe = Pipeline(
            str(document.get("name") or DEFAULT_NAME),
            params=document.get("params"),
            registry=self._registry,
        )
        given = dict(results or {})
        for other in upstream:
            probe.task(other, _constant(given.get(other)))
        probe.task(
            task_id,
            spec["action"],
            depends_on=upstream,
            retry=retry_from_dict(spec["retry"]) if "retry" in spec else None,
            timeout=spec.get("timeout"),
        )
        bus = EventBus()
        run = probe.run(params=params, store=MemoryRunStore(), bus=bus)
        view = self._view(run, active=False)
        view["tasks"] = {task_id: view["tasks"][task_id]}
        return {"run": view, "events": _chronological(bus, run.run_id, _DEFAULT_EVENTS)}

    # ------------------------------------------------------------------ runs

    def start(
        self, definition: Definition, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Start a run in the background and return it at once.

        A definition problem raises here, before anything runs.
        """
        token = CancellationToken()
        run = self._pipeline(definition).start(
            params=params, store=self._run_store(), cancel=token, bus=self._bus
        )
        self._track(run.run_id, _Tracked(token=token, run=run))
        file_automation_logger.info("pipelines: started %s run %s", run.pipeline, run.run_id)
        return self._view(run, active=True)

    def resume(self, run_id: str, definition: Definition) -> dict[str, Any]:
        """Continue a stored run in the background: keep what succeeded, run the rest.

        The run keeps its ID and its parameters. What would stop it at once is
        raised here: an unknown run, a run of another pipeline, a run this
        process is still executing, a definition that cannot run with the
        stored parameters. A run that already succeeded is returned as stored.
        """
        pipeline = self._pipeline(definition)
        store = self._run_store()
        earlier = store.get_run(run_id)
        if earlier is None:
            raise PipelineException(f"unknown run {run_id!r}")
        if earlier.pipeline != pipeline.name:
            raise PipelineException(
                f"run {run_id!r} belongs to pipeline {earlier.pipeline!r}, not {pipeline.name!r}"
            )
        if self._is_active(run_id):
            raise AppException(f"run {run_id!r} is still executing; cancel it or wait for it")
        if earlier.status is RunStatus.SUCCEEDED:
            return self._view(earlier, active=False)
        plan = pipeline.run(params=earlier.params, dry_run=True)
        if plan.status is not RunStatus.SUCCEEDED:
            notes = [state.error for state in plan.tasks.values() if state.error]
            raise PipelineDefinitionException(notes or [plan.error or "the run cannot be resumed"])
        tracked = _Tracked(token=CancellationToken())
        tracked.thread = threading.Thread(
            target=self._resume_in_background,
            args=(pipeline, run_id, store, tracked.token),
            name=f"pipeline-resume-{pipeline.name}",
        )
        self._track(run_id, tracked)
        tracked.thread.start()
        file_automation_logger.info("pipelines: resuming %s run %s", pipeline.name, run_id)
        return self._view(earlier, active=True)

    def retry(self, run_id: str, definition: Definition) -> dict[str, Any]:
        """Start a new run with the parameters of the stored run ``run_id``."""
        earlier = self._run_store().get_run(run_id)
        if earlier is None:
            raise PipelineException(f"unknown run {run_id!r}")
        return self.start(definition, earlier.params)

    def cancel(self, run_id: str) -> bool:
        """Ask a run this service is executing to stop; return whether there was one."""
        with self._lock:
            tracked = self._tracked.get(run_id)
        if tracked is None or not tracked.alive:
            return False
        tracked.token.cancel()
        file_automation_logger.info("pipelines: cancel requested for run %s", run_id)
        return True

    def wait(self, run_id: str, timeout: float | None = None) -> bool:
        """Block until a run this service is executing has ended; return whether it has."""
        with self._lock:
            tracked = self._tracked.get(run_id)
        if tracked is None:
            return True
        if tracked.run is not None:
            return tracked.run.wait(timeout)
        if tracked.thread is not None:
            tracked.thread.join(timeout)
        return not tracked.alive

    def status(self, run_id: str) -> dict[str, Any]:
        """Return the state of the run ``run_id`` and of its tasks."""
        with self._lock:
            tracked = self._tracked.get(run_id)
        if tracked is not None and tracked.run is not None:
            return self._view(tracked.run, active=tracked.alive)
        run = self._run_store().get_run(run_id)
        if run is None:
            raise PipelineException(f"unknown run {run_id!r}")
        return self._view(run, active=tracked is not None and tracked.alive)

    def history(
        self, pipeline: str | None = None, limit: int = _DEFAULT_HISTORY
    ) -> list[dict[str, Any]]:
        """Return the latest recorded runs, newest first, of one pipeline or of all."""
        return [
            self._view(run, active=self._is_active(run.run_id))
            for run in self._run_store().list_runs(pipeline or None, limit)
        ]

    def running(self) -> list[dict[str, Any]]:
        """Return the runs that have not ended: those of this process and those the store says."""
        with self._lock:
            tracked = {run_id: item for run_id, item in self._tracked.items() if item.alive}
        views = {
            run_id: self._view(item.run, active=True)
            for run_id, item in tracked.items()
            if item.run is not None
        }
        for run in self._run_store().list_runs(None, _SCAN_LIMIT):
            if run.status is RunStatus.RUNNING or run.run_id in tracked:
                views.setdefault(run.run_id, self._view(run, active=run.run_id in tracked))
        return sorted(views.values(), key=lambda view: view["started_at"] or "", reverse=True)

    def events(self, run_id: str, limit: int = _DEFAULT_EVENTS) -> list[dict[str, Any]]:
        """Return the events of the run ``run_id`` the bus still remembers, oldest first."""
        return _chronological(event_bus if self._bus is None else self._bus, run_id, limit)

    def follow(self, run_id: str, limit: int = _DEFAULT_EVENTS) -> dict[str, Any]:
        """Return ``{"run": status, "events": [...]}``: one call for a view that follows a run."""
        return {"run": self.status(run_id), "events": self.events(run_id, limit)}

    # ------------------------------------------------------------------ internals

    def _action_registry(self) -> ActionRegistry:
        if self._registry is not None:
            return self._registry
        from automation_file.core.action_executor import executor

        return executor.registry

    def _run_store(self) -> RunStore:
        return default_run_store() if self._store is None else self._store

    def _pipeline(self, definition: Definition) -> Pipeline:
        return Pipeline.from_dict(_document(definition), registry=self._registry)

    def _is_active(self, run_id: str) -> bool:
        with self._lock:
            tracked = self._tracked.get(run_id)
        return tracked is not None and tracked.alive

    def _track(self, run_id: str, tracked: _Tracked) -> None:
        with self._lock:
            self._tracked[run_id] = tracked
            ended = [key for key, item in self._tracked.items() if not item.alive]
            for key in ended[: max(len(self._tracked) - _MAX_TRACKED, 0)]:
                del self._tracked[key]

    def _resume_in_background(
        self, pipeline: Pipeline, run_id: str, store: RunStore, token: CancellationToken
    ) -> None:
        try:
            pipeline.resume(run_id, store=store, cancel=token, bus=self._bus)
        except Exception as error:  # pylint: disable=broad-except
            # Boundary of the background thread: there is no caller left to raise to.
            file_automation_logger.error(
                "pipelines: resuming %s run %s ended with %r", pipeline.name, run_id, error
            )

    @staticmethod
    def _view(run: PipelineRun, *, active: bool) -> dict[str, Any]:
        view: dict[str, Any] = mask_secrets(run.to_dict())
        view["active"] = active
        return view


def _document(definition: Definition) -> Mapping[str, Any]:
    if isinstance(definition, PipelineDraft):
        return definition.to_definition()
    if isinstance(definition, Mapping):
        return definition
    raise AppException(
        f"expected a PipelineDraft or a definition mapping, got {type(definition).__name__}"
    )


def _chronological(bus: EventBus, run_id: str, limit: int) -> list[dict[str, Any]]:
    recent = bus.recent(limit, correlation_id=run_id)
    return [mask_secrets(event.to_dict()) for event in reversed(recent)]


def _write_yaml(target: Path, definition: Mapping[str, Any]) -> None:
    import yaml

    try:
        text = yaml.safe_dump(dict(definition), sort_keys=False, allow_unicode=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
    except (OSError, yaml.YAMLError) as error:
        raise AppException(f"cannot write {target}: {error}") from error
