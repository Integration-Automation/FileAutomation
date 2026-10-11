"""``FA_integrity_*`` actions: the integrity monitor for JSON action lists.

Each function takes storage URIs as plain strings and returns JSON-friendly
values, so the same call works from Python, an action file, the CLI, the TCP
and HTTP action servers and as an MCP tool:

.. code-block:: json

    [
        ["FA_integrity_baseline", {"target": "s3://reports/2026",
                                   "baseline": "local:///var/lib/fa/reports.json"}],
        ["FA_integrity_verify", {"target": "s3://reports/2026",
                                 "baseline": "local:///var/lib/fa/reports.json"}]
    ]

``FA_integrity_watch_start`` keeps a named monitor verifying on a thread until
``FA_integrity_watch_stop``; ``FA_integrity_status`` shows what each one last
found. Drift is published on the process-wide event bus. None of the actions
remediates: a remediation policy can only be given in Python.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.hashing import DEFAULT_ALGORITHM
from automation_file.integrity.monitor import IntegrityMonitor
from automation_file.integrity.snapshot import Snapshot
from automation_file.logging_config import file_automation_logger

if TYPE_CHECKING:
    from automation_file.core.action_registry import ActionRegistry

_DEFAULT_INTERVAL = 60.0

_monitors: dict[str, IntegrityMonitor] = {}
_monitors_lock = threading.Lock()


def _stored(snapshot: Snapshot, baseline: str | None) -> dict[str, Any]:
    return {
        "target": snapshot.root,
        "baseline": baseline,
        "backend": snapshot.backend,
        "algorithm": snapshot.algorithm,
        "created_at": snapshot.created_at.isoformat(),
        "entries": len(snapshot),
    }


def _status(name: str, monitor: IntegrityMonitor) -> dict[str, Any]:
    return {"name": name, **monitor.status()}


def integrity_snapshot(target: str, algorithm: str = DEFAULT_ALGORITHM) -> dict[str, Any]:
    """Return every file below ``target`` with its size, time and checksum. Stores nothing."""
    return IntegrityMonitor(target, algorithm=algorithm).snapshot().to_dict()


def integrity_baseline(
    target: str, baseline: str, algorithm: str = DEFAULT_ALGORITHM
) -> dict[str, Any]:
    """Snapshot ``target`` and store it at ``baseline`` as the approved state."""
    monitor = IntegrityMonitor(target, baseline, algorithm=algorithm)
    return _stored(monitor.create_baseline(), monitor.baseline)


def integrity_verify(target: str, baseline: str, deep: bool = True) -> dict[str, Any]:
    """Compare ``target`` with ``baseline`` and return the drift report.

    ``deep=False`` hashes only the files whose size, modification time or etag changed.
    """
    return IntegrityMonitor(target, baseline).verify(deep=bool(deep)).to_dict()


def integrity_accept(target: str, baseline: str) -> dict[str, Any]:
    """Approve the current state of ``target``: store it at ``baseline`` as the new baseline."""
    monitor = IntegrityMonitor(target, baseline)
    return _stored(monitor.accept(), monitor.baseline)


def integrity_watch_start(
    name: str, target: str, baseline: str, interval: float = _DEFAULT_INTERVAL
) -> dict[str, Any]:
    """Start the monitor ``name``: verify ``target`` against ``baseline`` every ``interval`` s."""
    if not isinstance(name, str) or not name.strip():
        raise IntegrityException("an integrity monitor needs a name")
    monitor = IntegrityMonitor(target, baseline, interval=interval)
    if not monitor.has_baseline():
        raise IntegrityException(
            f"no baseline at {monitor.baseline}; create it first with FA_integrity_baseline"
        )
    with _monitors_lock:
        if name in _monitors:
            raise IntegrityException(f"an integrity monitor named {name!r} is already running")
        monitor.start()
        _monitors[name] = monitor
    file_automation_logger.info("integrity: monitor %r started on %s", name, monitor.target)
    return _status(name, monitor)


def integrity_watch_stop(name: str) -> dict[str, Any]:
    """Stop the monitor ``name`` and return its last status."""
    with _monitors_lock:
        monitor = _monitors.pop(name, None)
    if monitor is None:
        raise IntegrityException(f"no integrity monitor named {name!r}")
    monitor.stop()
    file_automation_logger.info("integrity: monitor %r stopped", name)
    return _status(name, monitor)


def integrity_status(name: str | None = None) -> list[dict[str, Any]]:
    """Return the status of the monitor ``name``, or of every named monitor.

    Each status has ``running``, ``last_run``, ``last_error`` and ``last_report``.
    """
    with _monitors_lock:
        if name is None:
            chosen = dict(_monitors)
        elif name in _monitors:
            chosen = {name: _monitors[name]}
        else:
            raise IntegrityException(f"no integrity monitor named {name!r}")
    return [_status(key, monitor) for key, monitor in chosen.items()]


def stop_all_monitors() -> list[dict[str, Any]]:
    """Stop every named monitor, for an orderly shutdown; returns their last statuses."""
    with _monitors_lock:
        stopped = dict(_monitors)
        _monitors.clear()
    for monitor in stopped.values():
        monitor.stop()
    return [_status(name, monitor) for name, monitor in stopped.items()]


def integrity_commands() -> dict[str, Callable[..., Any]]:
    """Return every ``FA_integrity_*`` action by name."""
    return {
        "FA_integrity_snapshot": integrity_snapshot,
        "FA_integrity_baseline": integrity_baseline,
        "FA_integrity_verify": integrity_verify,
        "FA_integrity_accept": integrity_accept,
        "FA_integrity_watch_start": integrity_watch_start,
        "FA_integrity_watch_stop": integrity_watch_stop,
        "FA_integrity_status": integrity_status,
    }


def register_integrity_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_integrity_*`` command into ``registry``."""
    registry.register_many(integrity_commands())
