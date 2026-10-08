"""An editable draft of a pipeline definition.

A pipeline editor does not edit a :class:`~automation_file.pipeline.Pipeline`:
that object refuses anything invalid, and a definition under construction is
invalid most of the time. A :class:`PipelineDraft` holds whatever the user has
entered so far, answers :meth:`PipelineDraft.problems` with the path of every
finding, and becomes a definition document with :meth:`PipelineDraft.to_definition`.

.. code-block:: python

    from automation_file.app import PipelineDraft

    draft = PipelineDraft("nightly")
    draft.add_task("FA_storage_copy", "download",
                   arguments={"source": "s3://in/a.csv", "target": "local:///tmp/a.csv"})
    draft.add_task("FA_storage_delete", "tidy", arguments={"uri": "local:///tmp/a.csv"})
    draft.connect("download", "tidy")          # tidy depends on download
    draft.problems()                           # [] when the definition is valid
    draft.to_definition()                      # what Pipeline.from_dict takes

The position of every task on a canvas is editor metadata. It lives on the draft
(:meth:`PipelineDraft.set_position`, :meth:`PipelineDraft.layout`) and never
appears in :meth:`PipelineDraft.to_definition`.

A draft is not thread-safe: edit it from one thread, and hand a worker the
document :meth:`PipelineDraft.to_definition` returns.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from automation_file.app.errors import AppException
from automation_file.pipeline import SCHEMA_VERSION, validate_definition
from automation_file.pipeline.model import ON_SUCCESS, WHEN_CHOICES
from automation_file.pipeline.substitution import NAME_RULE, is_name

CHANGE_STRUCTURE = "structure"
CHANGE_TASK = "task"
CHANGE_HEADER = "header"
CHANGE_POSITION = "position"

LAYOUT_VERSION = 1
DEFAULT_NAME = "pipeline"
DEFAULT_MAX_WORKERS = 4
DEFAULT_BACKOFF_CAP = 60.0

_TASKS_PREFIX = "tasks."
_ACTION_PREFIX = "FA_"
_COLUMN_WIDTH = 240.0
_ROW_HEIGHT = 110.0
_MARGIN = 40.0
_PATH_SEPARATORS = (".", "[")
_SINGLE_ATTEMPT = {"max_attempts": 1}

DraftListener = Callable[[str], None]
Arguments = dict[str, Any] | list[Any] | None


@dataclass(frozen=True)
class Problem:
    """One finding of a validation: where it is and what is wrong.

    ``path`` is the path inside the definition (``tasks.verify.depends_on[0]``)
    and ``task`` the ID of the task it belongs to, when it belongs to one.
    """

    path: str
    message: str
    task: str | None = None

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the problem."""
        return {"path": self.path, "message": self.message, "task": self.task}

    @classmethod
    def parse(cls, text: str, task_ids: tuple[str, ...] = ()) -> Problem:
        """Build a problem from the ``"<path>: <message>"`` text the pipeline package returns."""
        path, separator, message = text.partition(": ")
        if not separator:
            return cls(path="", message=text)
        return cls(path=path, message=message, task=_task_of(path, task_ids))


def _task_of(path: str, task_ids: tuple[str, ...]) -> str | None:
    """Return the ID of the task ``path`` points into, the longest ID that fits."""
    if not path.startswith(_TASKS_PREFIX):
        return None
    rest = path[len(_TASKS_PREFIX) :]
    fitting = [
        task_id
        for task_id in task_ids
        if rest == task_id
        or rest.startswith(tuple(f"{task_id}{mark}" for mark in _PATH_SEPARATORS))
    ]
    if fitting:
        return max(fitting, key=len)
    return rest.split(".", 1)[0] or None


@dataclass
class DraftTask:
    """One task of a draft: an action, how it runs, and where it sits on the canvas.

    ``arguments`` is the action's keyword mapping, its positional list, or
    ``None`` for an action without arguments. ``retry`` is the ``retry`` entry
    of a definition (``max_attempts``, ``backoff``, ``backoff_cap``, ``on``) or
    ``None`` for a single attempt. ``x`` and ``y`` are editor metadata.
    """

    task_id: str
    action: str = ""
    arguments: Arguments = None
    depends_on: list[str] = field(default_factory=list)
    retry: dict[str, Any] | None = None
    timeout: float | None = None
    when: str = ON_SUCCESS
    idempotency_key: str | None = None
    x: float = 0.0
    y: float = 0.0

    def to_spec(self) -> dict[str, Any]:
        """Return the task's entry in a definition; defaults and the position are left out."""
        action: list[Any] = [self.action]
        if self.arguments is not None:
            action.append(copy.deepcopy(self.arguments))
        spec: dict[str, Any] = {"action": action}
        if self.depends_on:
            spec["depends_on"] = list(self.depends_on)
        if self.retry:
            spec["retry"] = copy.deepcopy(self.retry)
        if self.timeout is not None:
            spec["timeout"] = self.timeout
        if self.when != ON_SUCCESS:
            spec["when"] = self.when
        if self.idempotency_key:
            spec["idempotency_key"] = self.idempotency_key
        return spec

    def to_dict(self) -> dict[str, Any]:
        """Return the task as a view needs it: its definition entry, its ID and its position."""
        return {"id": self.task_id, **self.to_spec(), "position": [self.x, self.y]}


def _renamed_references(value: Any, old: str, new: str) -> Any:
    """Return ``value`` with every ``${tasks.<old>.result}`` placeholder pointing at ``new``."""
    if isinstance(value, str):
        return value.replace(f"${{tasks.{old}.result}}", f"${{tasks.{new}.result}}")
    if isinstance(value, Mapping):
        return {key: _renamed_references(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed_references(item, old, new) for item in value]
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _task_from_spec(task_id: str, spec: Mapping[str, Any]) -> DraftTask:
    """Read what fits from a definition entry; validation reports what does not."""
    task = DraftTask(task_id=task_id)
    action = spec.get("action")
    if isinstance(action, list) and action:
        task.action = action[0] if isinstance(action[0], str) else ""
        if len(action) > 1 and isinstance(action[1], (dict, list)):
            task.arguments = copy.deepcopy(action[1])
    wanted = spec.get("depends_on")
    if isinstance(wanted, list):
        task.depends_on = [item for item in dict.fromkeys(wanted) if isinstance(item, str)]
    if isinstance(spec.get("retry"), Mapping):
        task.retry = copy.deepcopy(dict(spec["retry"]))
    task.timeout = _number(spec.get("timeout"))
    if isinstance(spec.get("when"), str):
        task.when = spec["when"]
    if isinstance(spec.get("idempotency_key"), str):
        task.idempotency_key = spec["idempotency_key"]
    return task


class PipelineDraft:
    """A pipeline definition being edited, with the canvas layout next to it."""

    def __init__(
        self,
        name: str = DEFAULT_NAME,
        description: str = "",
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        self._name = name
        self._description = description
        self._max_workers = max_workers
        self._params: dict[str, Any] = {}
        self._schedule: dict[str, Any] | None = None
        self._tasks: dict[str, DraftTask] = {}
        self._listeners: list[DraftListener] = []
        self._pending: list[str] | None = None
        self._revision = 0
        self._saved_revision = 0
        #: What validation said about the document this draft was read from.
        self.load_notes: tuple[str, ...] = ()

    # ------------------------------------------------------------------ reading

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def params(self) -> dict[str, Any]:
        """A copy of the default run parameters."""
        return copy.deepcopy(self._params)

    @property
    def schedule(self) -> dict[str, Any] | None:
        """A copy of the ``schedule`` entry (``cron``, ``timezone``), or ``None``."""
        return copy.deepcopy(self._schedule)

    @property
    def tasks(self) -> tuple[DraftTask, ...]:
        """The tasks in the order they were added."""
        return tuple(self._tasks.values())

    @property
    def revision(self) -> int:
        """A number that grows with every change."""
        return self._revision

    @property
    def dirty(self) -> bool:
        """Whether the draft changed since :meth:`mark_saved`."""
        return self._revision != self._saved_revision

    def mark_saved(self) -> None:
        """Remember the current state as the saved one."""
        self._saved_revision = self._revision

    def task_ids(self) -> tuple[str, ...]:
        """Return the task IDs in the order the tasks were added."""
        return tuple(self._tasks)

    def has_task(self, task_id: str) -> bool:
        return task_id in self._tasks

    def task(self, task_id: str) -> DraftTask:
        """Return the task ``task_id``; an unknown ID raises :class:`AppException`."""
        try:
            return self._tasks[task_id]
        except KeyError:
            raise AppException(f"the draft has no task {task_id!r}") from None

    def edges(self) -> list[tuple[str, str]]:
        """Return ``(upstream, downstream)`` for every dependency between two existing tasks."""
        return [
            (dependency, task.task_id)
            for task in self._tasks.values()
            for dependency in task.depends_on
            if dependency in self._tasks
        ]

    # ------------------------------------------------------------------ listeners

    def add_listener(self, listener: DraftListener) -> None:
        """Call ``listener(change)`` after every change; ``change`` is one of the ``CHANGE_*``."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: DraftListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Report the changes made inside the block once each, when the block ends."""
        if self._pending is not None:
            yield
            return
        self._pending = []
        try:
            yield
        finally:
            pending, self._pending = self._pending, None
            for change in dict.fromkeys(pending):
                self._emit(change)

    def _changed(self, change: str) -> None:
        self._revision += 1
        if self._pending is not None:
            self._pending.append(change)
        else:
            self._emit(change)

    def _emit(self, change: str) -> None:
        for listener in list(self._listeners):
            listener(change)

    # ------------------------------------------------------------------ the header

    def set_name(self, name: str) -> None:
        self._name = name.strip()
        self._changed(CHANGE_HEADER)

    def set_description(self, description: str) -> None:
        self._description = description
        self._changed(CHANGE_HEADER)

    def set_max_workers(self, max_workers: int) -> None:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise AppException(f"max_workers must be an integer, 1 or more, got {max_workers!r}")
        self._max_workers = max_workers
        self._changed(CHANGE_HEADER)

    def set_params(self, params: Mapping[str, Any] | None) -> None:
        """Replace the default run parameters."""
        if params is not None and not isinstance(params, Mapping):
            raise AppException(f"params must be a mapping, got {type(params).__name__}")
        self._params = copy.deepcopy(dict(params or {}))
        self._changed(CHANGE_HEADER)

    def set_schedule(self, cron: str | None, timezone: str | None = None) -> None:
        """Set the ``schedule`` entry, or remove it with ``cron=None``."""
        if cron is None or not cron.strip():
            self._schedule = None
        else:
            self._schedule = {"cron": cron.strip()}
            if timezone and timezone.strip():
                self._schedule["timezone"] = timezone.strip()
        self._changed(CHANGE_HEADER)

    # ------------------------------------------------------------------ tasks

    def add_task(
        self,
        action: str = "",
        task_id: str | None = None,
        *,
        arguments: Arguments = None,
        position: tuple[float, float] | None = None,
    ) -> DraftTask:
        """Add a task that calls ``action`` and return it.

        Without ``task_id`` an unused one is derived from the action name.
        Without ``position`` the task is placed below the lowest one.
        """
        chosen = self._unused_id(action) if task_id is None else self._checked_id(task_id)
        x, y = self._free_position() if position is None else position
        task = DraftTask(
            task_id=chosen,
            action=action,
            arguments=_checked_arguments(arguments),
            x=float(x),
            y=float(y),
        )
        self._tasks[chosen] = task
        self._changed(CHANGE_STRUCTURE)
        return task

    def remove_task(self, task_id: str) -> None:
        """Remove a task and every dependency on it."""
        self.task(task_id)
        del self._tasks[task_id]
        for other in self._tasks.values():
            if task_id in other.depends_on:
                other.depends_on.remove(task_id)
        self._changed(CHANGE_STRUCTURE)

    def rename_task(self, task_id: str, new_id: str) -> DraftTask:
        """Give a task another ID, keeping its place, its dependents and their placeholders."""
        task = self.task(task_id)
        if new_id == task_id:
            return task
        self._checked_id(new_id)
        task.task_id = new_id
        self._tasks = {
            (new_id if key == task_id else key): item for key, item in self._tasks.items()
        }
        for other in self._tasks.values():
            other.depends_on = [new_id if item == task_id else item for item in other.depends_on]
            other.arguments = _renamed_references(other.arguments, task_id, new_id)
        self._changed(CHANGE_STRUCTURE)
        return task

    def set_action(self, task_id: str, action: str) -> None:
        self.task(task_id).action = action.strip()
        self._changed(CHANGE_TASK)

    def set_arguments(self, task_id: str, arguments: Arguments) -> None:
        """Set the action's arguments: a keyword mapping, a positional list, or ``None``."""
        self.task(task_id).arguments = _checked_arguments(arguments)
        self._changed(CHANGE_TASK)

    def set_retry(
        self,
        task_id: str,
        max_attempts: int = 1,
        backoff: float = 0.0,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        on: list[str] | None = None,
    ) -> None:
        """Set how a task is retried; the defaults mean one attempt and remove the entry.

        ``on`` lists exception names (see
        :data:`automation_file.pipeline.RETRYABLE_EXCEPTIONS`); ``None`` keeps
        the transient kinds the runtime retries by default.
        """
        task = self.task(task_id)
        retry: dict[str, Any] = {"max_attempts": max_attempts}
        if backoff:
            retry["backoff"] = backoff
        if backoff_cap != DEFAULT_BACKOFF_CAP:
            retry["backoff_cap"] = backoff_cap
        if on:
            retry["on"] = list(on)
        task.retry = None if retry == _SINGLE_ATTEMPT else retry
        self._changed(CHANGE_TASK)

    def set_timeout(self, task_id: str, seconds: float | None) -> None:
        """Set the task's budget in seconds, or remove it with ``None``."""
        self.task(task_id).timeout = seconds
        self._changed(CHANGE_TASK)

    def set_condition(self, task_id: str, when: str) -> None:
        """Set when the task runs: ``on_success``, ``on_failure`` or ``always``."""
        if when not in WHEN_CHOICES:
            raise AppException(f"when must be one of {', '.join(WHEN_CHOICES)}, got {when!r}")
        self.task(task_id).when = when
        self._changed(CHANGE_TASK)

    def set_idempotency_key(self, task_id: str, key: str | None) -> None:
        """Set the task's idempotency key, or remove it with ``None`` or an empty text."""
        self.task(task_id).idempotency_key = key or None
        self._changed(CHANGE_TASK)

    # ------------------------------------------------------------------ dependency edges

    def connect(self, upstream: str, downstream: str) -> bool:
        """Make ``downstream`` depend on ``upstream``; return whether an edge was added.

        An edge from a task to itself and an edge that would close a cycle are
        refused with :class:`AppException`.
        """
        self.task(upstream)
        target = self.task(downstream)
        if upstream == downstream:
            raise AppException(f"task {upstream!r} cannot depend on itself")
        if upstream in target.depends_on:
            return False
        if self._reaches(upstream, downstream):
            raise AppException(
                f"{upstream!r} already depends on {downstream!r}: "
                "the edge would close a dependency cycle"
            )
        target.depends_on.append(upstream)
        self._changed(CHANGE_STRUCTURE)
        return True

    def disconnect(self, upstream: str, downstream: str) -> bool:
        """Remove the dependency of ``downstream`` on ``upstream``; return whether there was one."""
        target = self.task(downstream)
        if upstream not in target.depends_on:
            return False
        target.depends_on.remove(upstream)
        self._changed(CHANGE_STRUCTURE)
        return True

    def set_dependencies(self, task_id: str, depends_on: list[str]) -> None:
        """Make ``depends_on`` the complete list of what ``task_id`` depends on."""
        task = self.task(task_id)
        wanted = list(dict.fromkeys(depends_on))
        with self.batch():
            for dependency in [item for item in task.depends_on if item not in wanted]:
                self.disconnect(dependency, task_id)
            for dependency in wanted:
                self.connect(dependency, task_id)

    def _reaches(self, start: str, goal: str) -> bool:
        """Return whether ``start`` depends on ``goal``, directly or through other tasks."""
        seen: set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current == goal:
                return True
            if current in seen or current not in self._tasks:
                continue
            seen.add(current)
            stack.extend(self._tasks[current].depends_on)
        return False

    # ------------------------------------------------------------------ canvas layout

    def set_position(self, task_id: str, x: float, y: float) -> None:
        """Record where the task sits on the canvas."""
        task = self.task(task_id)
        if (task.x, task.y) == (float(x), float(y)):
            return
        task.x, task.y = float(x), float(y)
        self._changed(CHANGE_POSITION)

    def positions(self) -> dict[str, tuple[float, float]]:
        """Return ``{task ID: (x, y)}``."""
        return {task.task_id: (task.x, task.y) for task in self._tasks.values()}

    def auto_layout(self) -> None:
        """Place the tasks in columns by dependency depth, in the order they were added."""
        rows: dict[int, int] = {}
        for task_id, level in self._levels().items():
            row = rows.get(level, 0)
            rows[level] = row + 1
            task = self._tasks[task_id]
            task.x = _MARGIN + level * _COLUMN_WIDTH
            task.y = _MARGIN + row * _ROW_HEIGHT
        self._changed(CHANGE_POSITION)

    def layout(self) -> dict[str, Any]:
        """Return the editor metadata: the positions, kept apart from the definition."""
        return {
            "layout_version": LAYOUT_VERSION,
            "pipeline": self._name,
            "positions": {task.task_id: [task.x, task.y] for task in self._tasks.values()},
        }

    def apply_layout(self, layout: Any) -> int:
        """Take positions from what :meth:`layout` returned; return how many tasks were placed."""
        positions = layout.get("positions") if isinstance(layout, Mapping) else None
        if not isinstance(positions, Mapping):
            raise AppException("the layout has no 'positions' mapping")
        placed = 0
        for task_id, point in positions.items():
            task = self._tasks.get(task_id)
            if task is None or not isinstance(point, (list, tuple)) or len(point) != 2:
                continue
            x, y = _number(point[0]), _number(point[1])
            if x is None or y is None:
                continue
            task.x, task.y = x, y
            placed += 1
        self._changed(CHANGE_POSITION)
        return placed

    def _levels(self) -> dict[str, int]:
        """Return the dependency depth of every task; a cycle cannot make it endless."""
        levels = dict.fromkeys(self._tasks, 0)
        for _ in self._tasks:
            moved = False
            for task in self._tasks.values():
                depth = 1 + max(
                    (levels[item] for item in task.depends_on if item in levels), default=-1
                )
                depth = min(depth, len(self._tasks) - 1)
                if depth != levels[task.task_id]:
                    levels[task.task_id] = depth
                    moved = True
            if not moved:
                break
        return levels

    def _free_position(self) -> tuple[float, float]:
        if not self._tasks:
            return _MARGIN, _MARGIN
        return _MARGIN, max(task.y for task in self._tasks.values()) + _ROW_HEIGHT

    # ------------------------------------------------------------------ documents

    def to_definition(self) -> dict[str, Any]:
        """Return the definition document (``schema_version: 1``), without any editor metadata."""
        document: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "name": self._name}
        if self._description:
            document["description"] = self._description
        document["max_workers"] = self._max_workers
        if self._schedule is not None:
            document["schedule"] = copy.deepcopy(self._schedule)
        if self._params:
            document["params"] = copy.deepcopy(self._params)
        document["tasks"] = {task.task_id: task.to_spec() for task in self._tasks.values()}
        return document

    def problems(self) -> list[Problem]:
        """Return what keeps the draft from being a valid definition, each with its path."""
        task_ids = self.task_ids()
        return [Problem.parse(text, task_ids) for text in validate_definition(self.to_definition())]

    @classmethod
    def from_definition(cls, document: Any, layout: Any = None) -> PipelineDraft:
        """Build a draft from a definition document, valid or not.

        Whatever has the right shape is taken over, so a broken definition can
        be opened and repaired; what validation says about the document as it
        was is kept in :attr:`load_notes`. With ``layout`` the tasks get their
        stored positions, otherwise they are laid out by dependency depth.
        """
        if not isinstance(document, Mapping):
            raise AppException(f"a pipeline definition is a mapping, got {type(document).__name__}")
        draft = cls()
        draft.load_notes = tuple(validate_definition(document))
        draft._read_header(document)
        tasks = document.get("tasks")
        for task_id, spec in tasks.items() if isinstance(tasks, Mapping) else ():
            if is_name(task_id) and isinstance(spec, Mapping):
                draft._tasks[task_id] = _task_from_spec(task_id, spec)
        draft.auto_layout()
        if layout is not None:
            draft.apply_layout(layout)
        draft._revision = 0
        return draft

    def _read_header(self, document: Mapping[str, Any]) -> None:
        name = document.get("name")
        self._name = name if isinstance(name, str) and name.strip() else DEFAULT_NAME
        description = document.get("description")
        self._description = description if isinstance(description, str) else ""
        workers = document.get("max_workers")
        if isinstance(workers, int) and not isinstance(workers, bool) and workers >= 1:
            self._max_workers = workers
        params = document.get("params")
        self._params = copy.deepcopy(dict(params)) if isinstance(params, Mapping) else {}
        schedule = document.get("schedule")
        self._schedule = copy.deepcopy(dict(schedule)) if isinstance(schedule, Mapping) else None

    # ------------------------------------------------------------------ IDs

    def _checked_id(self, task_id: str) -> str:
        if not is_name(task_id):
            raise AppException(f"invalid task ID {task_id!r}: {NAME_RULE}")
        if task_id in self._tasks:
            raise AppException(f"the draft already has a task {task_id!r}")
        return task_id

    def _unused_id(self, action: str) -> str:
        base = action.strip().removeprefix(_ACTION_PREFIX)
        if not is_name(base):
            base = "task"
        if base not in self._tasks:
            return base
        number = 2
        while f"{base}_{number}" in self._tasks:
            number += 1
        return f"{base}_{number}"


def _checked_arguments(arguments: Any) -> Arguments:
    if arguments is None:
        return None
    if isinstance(arguments, Mapping):
        return copy.deepcopy(dict(arguments))
    if isinstance(arguments, list):
        return copy.deepcopy(arguments)
    raise AppException(
        f"arguments must be a mapping, a list or nothing, got {type(arguments).__name__}"
    )
