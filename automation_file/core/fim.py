"""File integrity monitoring (FIM) — periodic manifest verification.

``IntegrityMonitor(root, manifest_path)`` runs a background thread that
re-verifies the tree against a previously-written manifest at a fixed
interval. When drift is detected (missing or modified files) the monitor

1. invokes the optional ``on_drift`` callback with the verification summary,
2. emits an ``error``-level notification through the supplied
   :class:`~automation_file.notify.NotificationManager` (defaults to the
   process-wide singleton), and
3. logs a single warning describing the counts.

This is the "watchdog" side of manifests: once a baseline has been written
with :func:`write_manifest`, a monitor keeps checking that the tree still
matches and alerts when it does not. Extras (new files not in the manifest)
do not count as drift by default — mirrors the posture of ``verify_manifest``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from automation_file.core.manifest import ManifestException, verify_manifest
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.notify import NotificationManager, notification_manager

OnDrift = Callable[[dict[str, Any]], None]


class IntegrityMonitor:
    """Periodically verify a manifest and fire alerts on drift."""

    def __init__(
        self,
        root: str | Path,
        manifest_path: str | Path,
        *,
        interval: float = 60.0,
        on_drift: OnDrift | None = None,
        manager: NotificationManager | None = None,
        alert_on_extra: bool = False,
    ) -> None:
        if interval <= 0:
            raise FileAutomationException("interval must be positive")
        self._root = Path(root)
        self._manifest_path = Path(manifest_path)
        self._interval = float(interval)
        self._on_drift = on_drift
        self._manager = manager or notification_manager
        self._alert_on_extra = bool(alert_on_extra)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_summary: dict[str, Any] | None = None

    @property
    def last_summary(self) -> dict[str, Any] | None:
        return self._last_summary

    def start(self) -> None:
        """Arm the monitor. The first verification runs on the next tick."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="fa-integrity-monitor", daemon=True)
        thread.start()
        self._thread = thread
        file_automation_logger.info(
            "integrity_monitor: watching %s against %s (interval=%.1fs)",
            self._root,
            self._manifest_path,
            self._interval,
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def check_once(self) -> dict[str, Any]:
        """Run one verification pass and return the summary."""
        try:
            summary = verify_manifest(self._root, self._manifest_path)
        except (ManifestException, FileAutomationException) as err:
            file_automation_logger.error("integrity_monitor: verify failed: %r", err)
            summary = {
                "matched": [],
                "missing": [],
                "modified": [],
                "extra": [],
                "ok": False,
                "error": repr(err),
            }
        self._last_summary = summary
        if self._is_drift(summary):
            self._handle_drift(summary)
        return summary

    def _is_drift(self, summary: dict[str, Any]) -> bool:
        if summary.get("error"):
            return True
        if summary.get("missing") or summary.get("modified"):
            return True
        return bool(self._alert_on_extra and summary.get("extra"))

    def _handle_drift(self, summary: dict[str, Any]) -> None:
        file_automation_logger.warning(
            "integrity_monitor: drift detected missing=%d modified=%d extra=%d",
            len(summary.get("missing") or []),
            len(summary.get("modified") or []),
            len(summary.get("extra") or []),
        )
        if self._on_drift is not None:
            try:
                self._on_drift(summary)
            except FileAutomationException as err:
                file_automation_logger.error("integrity_monitor: on_drift raised: %r", err)
        body = _format_body(summary)
        try:
            self._manager.notify(
                subject=f"integrity drift: {self._root}",
                body=body,
                level="error",
            )
        except FileAutomationException as err:
            file_automation_logger.error("integrity_monitor: notify failed: %r", err)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self._interval)
            if self._stop.is_set():
                break
            self.check_once()


def _format_body(summary: dict[str, Any]) -> str:
    parts: list[str] = []
    if summary.get("error"):
        parts.append(f"error: {summary['error']}")
    for key in ("missing", "modified", "extra"):
        items = summary.get(key) or []
        if items:
            preview = ", ".join(items[:5])
            suffix = f" (+{len(items) - 5} more)" if len(items) > 5 else ""
            parts.append(f"{key}: {preview}{suffix}")
    return "\n".join(parts) if parts else "no drift detected"
