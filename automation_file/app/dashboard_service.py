"""The Dashboard service: one summary of how the installation is doing.

.. code-block:: python

    from automation_file.app import app_services

    summary = app_services().dashboard.summary()
    summary.status                 # "ok" or "attention"
    summary.reasons                # why it needs attention
    summary.running_runs, summary.recent_runs, summary.run_counts
    summary.integrity              # what every monitor last found
    summary.events                 # the latest events of the bus, newest first
    summary.storage                # every backend and whether it can be used

The summary is built from the other services and from the event bus; it reads
state and starts nothing. ``summary.to_dict()`` is JSON-serialisable, so a web
page and a desktop page render the same data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from automation_file.app.audit_service import AuditService
from automation_file.app.integrity_service import IntegrityService
from automation_file.app.masking import mask_secrets
from automation_file.app.notification_service import NotificationService
from automation_file.app.pipeline_service import PipelineService
from automation_file.app.scheduler_service import SchedulerService
from automation_file.app.storage_service import StorageService
from automation_file.events import EventBus, Severity, event_bus
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

STATUS_OK = "ok"
STATUS_ATTENTION = "attention"

_DEFAULT_EVENTS = 20
_DEFAULT_RUNS = 10
_HISTORY_WINDOW = 50
_RUN_STATUSES = ("running", "succeeded", "failed", "cancelled")
_FAILED = "failed"


@dataclass(frozen=True)
class DashboardSources:
    """The services a dashboard reads."""

    pipelines: PipelineService
    integrity: IntegrityService
    storage: StorageService
    scheduler: SchedulerService
    audit: AuditService
    notifications: NotificationService


@dataclass(frozen=True)
class DashboardSummary:
    """Everything a dashboard shows, read at one moment.

    ``status`` is ``"attention"`` when a recent run failed, a monitor found
    drift or could not verify, or the bus holds a recent event of severity
    ``error`` or worse; ``reasons`` says which, one sentence each.
    """

    generated_at: str
    status: str = STATUS_OK
    reasons: tuple[str, ...] = ()
    health: dict[str, Any] = field(default_factory=dict)
    run_counts: dict[str, int] = field(default_factory=dict)
    running_runs: list[dict[str, Any]] = field(default_factory=list)
    recent_runs: list[dict[str, Any]] = field(default_factory=list)
    integrity: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    storage: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the summary."""
        return {
            "generated_at": self.generated_at,
            "status": self.status,
            "reasons": list(self.reasons),
            "health": dict(self.health),
            "run_counts": dict(self.run_counts),
            "running_runs": list(self.running_runs),
            "recent_runs": list(self.recent_runs),
            "integrity": list(self.integrity),
            "events": list(self.events),
            "storage": list(self.storage),
        }


def brief_run(view: dict[str, Any]) -> dict[str, Any]:
    """Return a run without its task details: what a list of runs shows."""
    tasks = view.get("tasks") or {}
    return {
        "run_id": view.get("run_id"),
        "pipeline": view.get("pipeline"),
        "status": view.get("status"),
        "active": bool(view.get("active")),
        "started_at": view.get("started_at"),
        "finished_at": view.get("finished_at"),
        "error": view.get("error"),
        "tasks": len(tasks),
        "task_statuses": dict(Counter(str(state.get("status")) for state in tasks.values())),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DashboardService:
    """Health, runs, integrity drift, recent events and storage status in one place."""

    def __init__(self, sources: DashboardSources, *, bus: EventBus | None = None) -> None:
        self._sources = sources
        self._bus = event_bus if bus is None else bus

    def health(self) -> dict[str, Any]:
        """Return what is alive and configured: counts and switches, no history."""
        sources = self._sources
        return {
            "process": "alive",
            "time": _now(),
            "registry_size": len(sources.pipelines.action_names()),
            "running_runs": len(sources.pipelines.running()),
            "scheduler_jobs": len(sources.scheduler.jobs()),
            "integrity_monitors": len(sources.integrity.status()),
            "notification_sinks": len(sources.notifications.sink_names()),
            "notification_routes": len(sources.notifications.routes()),
            "notification_router_active": sources.notifications.router_active(),
            "audit": sources.audit.status(),
        }

    def runs(self, limit: int = _DEFAULT_RUNS) -> dict[str, Any]:
        """Return the running runs, the latest ended ones, and how the latest runs ended.

        ``counts`` covers the newest runs of the store (at most fifty), so it
        says how things have been going lately, not since the beginning.
        """
        pipelines = self._sources.pipelines
        window = [brief_run(view) for view in pipelines.history(None, _HISTORY_WINDOW)]
        counts = Counter(str(run["status"]) for run in window)
        return {
            "running": [brief_run(view) for view in pipelines.running()],
            "recent": [run for run in window if run["status"] != "running"][: max(limit, 0)],
            "counts": {status: counts.get(status, 0) for status in _RUN_STATUSES},
            "window": len(window),
        }

    def integrity(self) -> list[dict[str, Any]]:
        """Return what every named integrity monitor last found."""
        return [drift.to_dict() for drift in self._sources.integrity.drift()]

    def recent_events(
        self, limit: int = _DEFAULT_EVENTS, min_severity: str = Severity.INFO.value
    ) -> list[dict[str, Any]]:
        """Return the latest events of the bus, newest first, with their secrets masked."""
        events = self._bus.recent(limit, min_severity=Severity(min_severity))
        return [mask_secrets(event.to_dict()) for event in events]

    def storage_status(self) -> list[dict[str, Any]]:
        """Return every storage backend and whether it can be used."""
        return [status.to_dict() for status in self._sources.storage.backends()]

    def summary(self, events: int = _DEFAULT_EVENTS, runs: int = _DEFAULT_RUNS) -> DashboardSummary:
        """Return the whole dashboard. A part that cannot be read is reported, not raised."""
        reasons: list[str] = []
        run_data = self._part("pipeline runs", lambda: self.runs(runs), reasons) or {}
        integrity = self._part("integrity", self.integrity, reasons) or []
        recent = self._part("events", lambda: self.recent_events(events), reasons) or []
        storage = self._part("storage", self.storage_status, reasons) or []
        health = self._part("health", self.health, reasons) or {}
        reasons.extend(_attention(run_data, integrity, recent))
        return DashboardSummary(
            generated_at=_now(),
            status=STATUS_ATTENTION if reasons else STATUS_OK,
            reasons=tuple(reasons),
            health=health,
            run_counts=run_data.get("counts", {}),
            running_runs=run_data.get("running", []),
            recent_runs=run_data.get("recent", []),
            integrity=integrity,
            events=recent,
            storage=storage,
        )

    @staticmethod
    def _part(name: str, read: Callable[[], Any], reasons: list[str]) -> Any:
        try:
            return read()
        except FileAutomationException as error:
            file_automation_logger.warning("dashboard: cannot read %s: %r", name, error)
            reasons.append(f"{name} cannot be read: {type(error).__name__}")
            return None


def _attention(
    run_data: dict[str, Any], integrity: list[dict[str, Any]], events: list[dict[str, Any]]
) -> list[str]:
    reasons: list[str] = []
    failed = run_data.get("counts", {}).get(_FAILED, 0)
    if failed:
        reasons.append(f"{failed} of the last {run_data.get('window', 0)} pipeline runs failed")
    for monitor in integrity:
        if monitor.get("last_error"):
            reasons.append(f"integrity monitor {monitor['name']!r} could not verify")
        elif monitor.get("ok") is False:
            reasons.append(
                f"integrity monitor {monitor['name']!r} found {monitor.get('changes', 0)} change(s)"
            )
    serious = [
        event
        for event in events
        if Severity(event.get("severity", Severity.INFO.value)).at_least(Severity.ERROR)
    ]
    if serious:
        reasons.append(f"{len(serious)} recent event(s) of severity error or worse")
    return reasons
