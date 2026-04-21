"""DAG executor — run actions in dependency order, parallelising independent branches.

A DAG node is a dict:

.. code-block:: python

   {"id": "build", "action": ["FA_create_dir", {"dir_path": "build"}]}
   {"id": "zip", "action": ["FA_zip_dir", ...], "depends_on": ["build"]}

The executor performs Kahn-style topological scheduling: every node whose
dependencies are satisfied becomes runnable and is dispatched to a shared
thread pool immediately — so diamonds and wide fan-outs run in parallel
without the caller hand-tuning ``max_workers`` around dependency edges.

If a node raises, its transitive dependents are marked ``skipped`` by
default (fail-fast semantics). Pass ``fail_fast=False`` to run dependents
regardless (useful for cleanup steps).
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from automation_file.core.action_executor import executor as default_executor
from automation_file.exceptions import DagException

__all__ = ["execute_action_dag"]


def execute_action_dag(
    nodes: list[Mapping[str, Any]],
    max_workers: int = 4,
    fail_fast: bool = True,
) -> dict[str, Any]:
    """Run ``nodes`` in topological order, parallelising independent branches.

    Each node is ``{"id": str, "action": [...], "depends_on": [id, ...]}``.
    ``depends_on`` is optional (default ``[]``). Returns a dict mapping each
    node id to either the action's return value, the repr of its exception,
    or ``"skipped: <reason>"`` when ``fail_fast`` blocks a branch.

    Raises :class:`DagException` for static errors detected before any action
    runs: duplicate ids, unknown dependencies, or cycles.
    """
    graph, indegree = _build_graph(nodes)
    node_map = {_require_id(node): node for node in nodes}
    results: dict[str, Any] = {}
    lock = threading.Lock()

    ready: deque[str] = deque(node_id for node_id, count in indegree.items() if count == 0)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        in_flight: dict[Future[Any], str] = {}

        def submit(node_id: str) -> None:
            action = node_map[node_id].get("action")
            if not isinstance(action, list):
                err = DagException(f"node {node_id!r} missing action list")
                with lock:
                    results[node_id] = repr(err)
                if fail_fast:
                    for dependent in graph.get(node_id, ()):
                        indegree[dependent] -= 1
                        _mark_skipped(dependent, node_id, graph, indegree, results, lock)
                return
            future = pool.submit(_run_action, action)
            in_flight[future] = node_id

        while ready or in_flight:
            while ready:
                submit(ready.popleft())
            if not in_flight:
                break
            done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                node_id = in_flight.pop(future)
                failed = False
                try:
                    value: Any = future.result()
                except Exception as err:  # pylint: disable=broad-except
                    value = repr(err)
                    failed = True
                with lock:
                    results[node_id] = value
                for dependent in graph.get(node_id, ()):
                    indegree[dependent] -= 1
                    if failed and fail_fast:
                        _mark_skipped(dependent, node_id, graph, indegree, results, lock)
                    elif indegree[dependent] == 0 and dependent not in results:
                        ready.append(dependent)

    return results


def _run_action(action: list) -> Any:
    # Use the single-action path so exceptions surface as real exceptions
    # rather than being swallowed by execute_action's per-action try/except.
    return default_executor._execute_event(action)


def _build_graph(
    nodes: list[Mapping[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, int]]:
    graph: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {}
    ids: set[str] = set()

    for node in nodes:
        node_id = _require_id(node)
        if node_id in ids:
            raise DagException(f"duplicate node id: {node_id!r}")
        ids.add(node_id)
        indegree[node_id] = 0

    for node in nodes:
        node_id = _require_id(node)
        deps = node.get("depends_on", []) or []
        if not isinstance(deps, list):
            raise DagException(f"node {node_id!r} depends_on must be list")
        for dep in deps:
            if dep not in ids:
                raise DagException(f"node {node_id!r} depends on unknown id {dep!r}")
            if dep == node_id:
                raise DagException(f"node {node_id!r} depends on itself")
            graph[dep].append(node_id)
            indegree[node_id] += 1

    _detect_cycle(ids, graph, dict(indegree))
    return dict(graph), indegree


def _require_id(node: Mapping[str, Any]) -> str:
    node_id = node.get("id")
    if not isinstance(node_id, str) or not node_id:
        raise DagException(f"node missing non-empty 'id': {node!r}")
    return node_id


def _detect_cycle(
    ids: set[str],
    graph: dict[str, list[str]],
    indegree: dict[str, int],
) -> None:
    queue: deque[str] = deque(node_id for node_id, count in indegree.items() if count == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for dependent in graph.get(current, ()):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if visited != len(ids):
        raise DagException("cycle detected in DAG")


def _mark_skipped(
    dependent: str,
    reason_id: str,
    graph: dict[str, list[str]],
    indegree: dict[str, int],
    results: dict[str, Any],
    lock: threading.Lock,
) -> None:
    with lock:
        if dependent in results:
            return
        results[dependent] = f"skipped: dep {reason_id!r} failed"
    for grandchild in graph.get(dependent, ()):
        indegree[grandchild] -= 1
        _mark_skipped(grandchild, dependent, graph, indegree, results, lock)
