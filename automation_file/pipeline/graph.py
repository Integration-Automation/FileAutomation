"""Dependency graph checks and ordering for a pipeline.

Every function takes the graph as ``{task ID: IDs it depends on}`` in definition
order, so the same checks serve a :class:`~automation_file.pipeline.pipeline.Pipeline`
built in Python and a definition document that has not become one yet.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from automation_file.pipeline.errors import PipelineDefinitionException

Dependencies = Mapping[str, Sequence[str]]
_ON_PATH = 1
_DONE = 2


def dependency_problems(dependencies: Dependencies) -> list[str]:
    """Return every unknown, repeated or self dependency and any cycle, each with its path."""
    problems: list[str] = []
    for task_id, wanted in dependencies.items():
        seen: set[str] = set()
        for index, dependency in enumerate(wanted):
            path = f"tasks.{task_id}.depends_on[{index}]"
            if dependency == task_id:
                problems.append(f"{path}: a task cannot depend on itself")
            elif dependency not in dependencies:
                problems.append(f"{path}: unknown task {dependency!r}")
            elif dependency in seen:
                problems.append(f"{path}: {dependency!r} is listed twice")
            seen.add(dependency)
    cycle = find_cycle(dependencies)
    if cycle is not None:
        problems.append(f"tasks: dependency cycle: {' -> '.join(cycle)}")
    return problems


def _edges(dependencies: Dependencies, task_id: str) -> Iterator[str]:
    """Yield the dependencies of ``task_id`` that exist and are not the task itself."""
    return (
        dependency
        for dependency in dependencies[task_id]
        if dependency in dependencies and dependency != task_id
    )


def find_cycle(dependencies: Dependencies) -> list[str] | None:
    """Return one dependency cycle as ``[a, b, ..., a]``, or ``None`` when there is none."""
    marks: dict[str, int] = {}
    for root in dependencies:
        if root in marks:
            continue
        cycle = _cycle_from(root, dependencies, marks)
        if cycle is not None:
            return cycle
    return None


def _cycle_from(root: str, dependencies: Dependencies, marks: dict[str, int]) -> list[str] | None:
    path = [root]
    pending = [_edges(dependencies, root)]
    marks[root] = _ON_PATH
    while pending:
        following = next(pending[-1], None)
        if following is None:
            marks[path.pop()] = _DONE
            pending.pop()
        elif marks.get(following) == _ON_PATH:
            return [*path[path.index(following) :], following]
        elif following not in marks:
            marks[following] = _ON_PATH
            path.append(following)
            pending.append(_edges(dependencies, following))
    return None


def task_levels(dependencies: Dependencies) -> dict[str, int]:
    """Return ``{task ID: level}`` in dependency order.

    A task without dependencies is at level 0; any other is one level above its
    deepest dependency. Tasks of one level keep their definition order. The graph
    must be free of the problems :func:`dependency_problems` reports.
    """
    levels: dict[str, int] = {}
    remaining = list(dependencies)
    while remaining:
        waiting: list[str] = []
        for task_id in remaining:
            wanted = dependencies[task_id]
            if all(dependency in levels for dependency in wanted):
                levels[task_id] = 1 + max((levels[dependency] for dependency in wanted), default=-1)
            else:
                waiting.append(task_id)
        if len(waiting) == len(remaining):
            raise PipelineDefinitionException(
                f"tasks: cannot order {', '.join(waiting)}: unknown dependency or cycle"
            )
        remaining = waiting
    position = {task_id: index for index, task_id in enumerate(dependencies)}
    ordered = sorted(levels, key=lambda task_id: (levels[task_id], position[task_id]))
    return {task_id: levels[task_id] for task_id in ordered}


def upstream_tasks(dependencies: Dependencies) -> dict[str, tuple[str, ...]]:
    """Return ``{task ID: every task it depends on, directly or through others}``.

    Each tuple is in definition order. Unknown dependencies are left out and a
    cycle ends the walk, so this is safe to call on a graph that still has problems.
    """
    upstream: dict[str, tuple[str, ...]] = {}
    for task_id in dependencies:
        found: set[str] = set()
        stack = list(_edges(dependencies, task_id))
        while stack:
            current = stack.pop()
            if current in found or current == task_id:
                continue
            found.add(current)
            stack.extend(_edges(dependencies, current))
        upstream[task_id] = tuple(other for other in dependencies if other in found)
    return upstream
