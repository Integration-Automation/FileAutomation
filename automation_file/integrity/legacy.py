"""What the first ``IntegrityMonitor`` (``automation_file.core.fim``) gave its callers.

``check_once()`` returned a summary dictionary -- ``matched``, ``missing``,
``modified``, ``extra``, ``ok``, and ``error`` when the pass failed -- handed
the same dictionary to ``on_drift`` and sent one notification. Those three
things are kept here so code written for that monitor keeps working. New code
reads the :class:`~automation_file.integrity.report.DriftReport` and subscribes
to the event bus instead.

Additions do not count as drift in this summary unless ``alert_on_extra`` is
set, and a rename appears as its two halves, as it always did.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

from automation_file.exceptions import FileAutomationException
from automation_file.integrity.detector import ChangeKind
from automation_file.integrity.report import DriftReport
from automation_file.logging_config import file_automation_logger

if TYPE_CHECKING:
    from automation_file.notify.manager import NotificationManager

OnDrift = Callable[[dict[str, Any]], None]

_MISSING = "missing"
_MODIFIED = "modified"
_EXTRA = "extra"
_ERROR = "error"
_PREVIEW = 5
_NOTIFICATION_LEVEL = "error"


def summary_of(report: DriftReport, examined: Iterable[str]) -> dict[str, Any]:
    """Return the legacy summary of ``report``; ``examined`` are the baseline paths it covered."""
    missing: list[str] = []
    modified: list[str] = []
    extra: list[str] = []
    for change in report.changes:
        if change.kind is ChangeKind.DELETED:
            missing.append(change.path)
        elif change.kind is ChangeKind.MODIFIED:
            modified.append(change.path)
        elif change.kind is ChangeKind.CREATED:
            extra.append(change.path)
        elif change.kind is ChangeKind.RENAMED and change.previous_path is not None:
            missing.append(change.previous_path)
            extra.append(change.path)
    unmatched = {*missing, *modified}
    return {
        "matched": [path for path in examined if path not in unmatched],
        _MISSING: sorted(missing),
        _MODIFIED: sorted(modified),
        _EXTRA: sorted(extra),
        "ok": not missing and not modified,
    }


def error_summary(error: BaseException) -> dict[str, Any]:
    """Return the legacy summary of a pass that could not run."""
    return {
        "matched": [],
        _MISSING: [],
        _MODIFIED: [],
        _EXTRA: [],
        "ok": False,
        _ERROR: repr(error),
    }


def format_body(summary: dict[str, Any]) -> str:
    """Return the text of the legacy notification: the first few paths of each list."""
    parts: list[str] = []
    if summary.get(_ERROR):
        parts.append(f"error: {summary[_ERROR]}")
    for key in (_MISSING, _MODIFIED, _EXTRA):
        items = summary.get(key) or []
        if items:
            preview = ", ".join(items[:_PREVIEW])
            suffix = f" (+{len(items) - _PREVIEW} more)" if len(items) > _PREVIEW else ""
            parts.append(f"{key}: {preview}{suffix}")
    return "\n".join(parts) if parts else "no drift detected"


def _process_wide_manager() -> NotificationManager:
    """Return the shared manager, looked up when it is needed so a test may replace it."""
    from automation_file import notify

    return notify.notification_manager


class LegacyHooks:
    """The ``on_drift`` callback and the notification of the first monitor.

    The notification goes through the manager the caller passed, or through the
    process-wide ``notification_manager`` when none was: what the first monitor
    did. ``notify=False`` sends none.
    """

    def __init__(
        self,
        subject: str,
        *,
        on_drift: OnDrift | None = None,
        manager: NotificationManager | None = None,
        alert_on_extra: bool = False,
        notify: bool = True,
    ) -> None:
        self._subject = subject
        self._on_drift = on_drift
        self._manager = manager
        self._notifies = bool(notify)
        self._alert_on_extra = bool(alert_on_extra)

    def is_drift(self, summary: dict[str, Any]) -> bool:
        """Say whether ``summary`` counts as drift by the first monitor's rule."""
        if summary.get(_ERROR) or summary.get(_MISSING) or summary.get(_MODIFIED):
            return True
        return bool(self._alert_on_extra and summary.get(_EXTRA))

    def handle(self, summary: dict[str, Any]) -> None:
        """Call ``on_drift`` and notify the manager when ``summary`` shows drift."""
        if not self.is_drift(summary):
            return
        if self._on_drift is not None:
            self._call_back(self._on_drift, summary)
        if self._notifies:
            self._notify(self._manager or _process_wide_manager(), summary)

    def _call_back(self, on_drift: OnDrift, summary: dict[str, Any]) -> None:
        try:
            on_drift(summary)
        except Exception as error:  # pylint: disable=broad-except
            # Boundary: a caller's callback must not stop the monitor that called it.
            file_automation_logger.error("integrity: on_drift raised: %r", error)

    def _notify(self, manager: NotificationManager, summary: dict[str, Any]) -> None:
        try:
            manager.notify(
                subject=self._subject, body=format_body(summary), level=_NOTIFICATION_LEVEL
            )
        except FileAutomationException as error:
            file_automation_logger.error("integrity: notify failed: %r", error)
