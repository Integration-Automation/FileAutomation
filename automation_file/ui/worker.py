"""Background worker that runs a callable off the UI thread.

Uses :class:`QThreadPool` so we don't block the event loop when an action
touches the network or disk. The worker emits ``finished(result)`` on success
and ``failed(exception)`` on failure; the ``log(message)`` signal fires before
and after the call so the activity panel stays current.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal


class _WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(object)
    log = Signal(str)


class ActionWorker(QRunnable):
    """Run ``target(*args, **kwargs)`` on a Qt thread pool worker."""

    def __init__(
        self,
        target: Callable[..., Any],
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        label: str = "action",
    ) -> None:
        super().__init__()
        self._target = target
        self._args = args or ()
        self._kwargs = kwargs or {}
        self._label = label
        self.signals = _WorkerSignals()

    def run(self) -> None:
        self.signals.log.emit(f"running: {self._label}")
        try:
            result = self._target(*self._args, **self._kwargs)
        except Exception as error:  # pylint: disable=broad-exception-caught  # worker dispatcher boundary — must surface any failure to the UI
            self.signals.log.emit(f"failed: {self._label}: {error!r}")
            self.signals.failed.emit(error)
            return
        self.signals.log.emit(f"done:    {self._label}")
        self.signals.finished.emit(result)
