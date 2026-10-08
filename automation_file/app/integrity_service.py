"""The Integrity service: baselines, verification and the named monitors.

.. code-block:: python

    from automation_file.app import app_services

    integrity = app_services().integrity
    integrity.baseline("s3://reports/2026", "local:///var/lib/fa/reports.json")
    report = integrity.verify("s3://reports/2026", "local:///var/lib/fa/reports.json")
    report["ok"], report["counts"]
    integrity.start_monitor("reports", "s3://reports/2026",
                            "local:///var/lib/fa/reports.json", interval=300)
    integrity.drift()               # one summary per monitor, for a dashboard

Everything goes through the ``FA_integrity_*`` functions of
:mod:`automation_file.integrity.actions`, so a monitor started here is the same
named monitor the actions, the CLI and the servers see. Nothing here remediates.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from automation_file.app.errors import AppException
from automation_file.integrity import DEFAULT_ALGORITHM, STRONG_ALGORITHMS, IntegrityException
from automation_file.integrity.actions import (
    integrity_accept,
    integrity_baseline,
    integrity_status,
    integrity_verify,
    integrity_watch_start,
    integrity_watch_stop,
)
from automation_file.logging_config import file_automation_logger

DEFAULT_INTERVAL = 60.0


@dataclass(frozen=True)
class MonitorDrift:
    """What one named monitor last found.

    ``ok`` is ``None`` until the monitor has verified once. ``changes`` is the
    number of differences of the last report and ``counts`` splits it by kind.
    """

    name: str
    target: str
    baseline: str | None
    running: bool
    ok: bool | None = None
    changes: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    last_run: str | None = None
    last_error: str | None = None

    @property
    def needs_attention(self) -> bool:
        """Whether the monitor found drift or could not verify."""
        return self.ok is False or self.last_error is not None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the summary."""
        return {**asdict(self), "needs_attention": self.needs_attention}


def _drift(status: dict[str, Any]) -> MonitorDrift:
    report = status.get("last_report") or {}
    counts = {kind: int(count) for kind, count in (report.get("counts") or {}).items()}
    return MonitorDrift(
        name=str(status.get("name", "")),
        target=str(status.get("target", "")),
        baseline=status.get("baseline"),
        running=bool(status.get("running")),
        ok=report.get("ok") if report else None,
        changes=len(report.get("changes") or ()),
        counts=counts,
        last_run=status.get("last_run"),
        last_error=status.get("last_error"),
    )


def _required(value: str, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppException(f"{what} is required")
    return value.strip()


class IntegrityService:
    """Baseline, verify, accept, and start or stop a monitor."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started: list[str] = []

    def algorithms(self) -> list[str]:
        """Return the digest algorithms a baseline may use, the default first."""
        others = sorted(name for name in STRONG_ALGORITHMS if name != DEFAULT_ALGORITHM)
        return [DEFAULT_ALGORITHM, *others]

    def baseline(
        self, target: str, baseline: str, algorithm: str = DEFAULT_ALGORITHM
    ) -> dict[str, Any]:
        """Snapshot ``target`` and store it at ``baseline`` as the approved state."""
        return integrity_baseline(
            _required(target, "the target"), _required(baseline, "the baseline"), algorithm
        )

    def verify(self, target: str, baseline: str, deep: bool = True) -> dict[str, Any]:
        """Compare ``target`` with ``baseline`` and return the drift report.

        ``deep=False`` hashes only the files whose size, time or etag changed.
        Drift is published as an ``integrity.violation`` event.
        """
        return integrity_verify(
            _required(target, "the target"), _required(baseline, "the baseline"), deep
        )

    def accept(self, target: str, baseline: str) -> dict[str, Any]:
        """Approve the current state of ``target`` as the new baseline."""
        return integrity_accept(
            _required(target, "the target"), _required(baseline, "the baseline")
        )

    def status(self, name: str | None = None) -> list[dict[str, Any]]:
        """Return the status of the monitor ``name``, or of every named monitor."""
        return integrity_status(name)

    def drift(self) -> list[MonitorDrift]:
        """Return what every named monitor last found."""
        return [_drift(status) for status in integrity_status()]

    def start_monitor(
        self, name: str, target: str, baseline: str, interval: float = DEFAULT_INTERVAL
    ) -> dict[str, Any]:
        """Start the monitor ``name``: verify ``target`` every ``interval`` seconds."""
        if interval <= 0:
            raise AppException(f"the interval must be more than 0 seconds, got {interval!r}")
        chosen = _required(name, "the monitor name")
        status = integrity_watch_start(
            chosen, _required(target, "the target"), _required(baseline, "the baseline"), interval
        )
        with self._lock:
            self._started.append(chosen)
        return status

    def stop_monitor(self, name: str) -> dict[str, Any]:
        """Stop the monitor ``name`` and return its last status."""
        status = integrity_watch_stop(name)
        with self._lock:
            if name in self._started:
                self._started.remove(name)
        return status

    def stop_started(self) -> list[str]:
        """Stop the monitors this service started and return their names.

        A user interface calls this when it closes, so the monitors it started
        do not outlive it; monitors started elsewhere are left alone.
        """
        with self._lock:
            names, self._started = self._started, []
        stopped: list[str] = []
        for name in names:
            try:
                integrity_watch_stop(name)
            except IntegrityException as error:
                file_automation_logger.info("integrity: monitor %r was gone: %r", name, error)
            else:
                stopped.append(name)
        return stopped
