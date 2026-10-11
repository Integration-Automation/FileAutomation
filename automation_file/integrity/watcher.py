"""Watcher: the threads behind the watch and continuous modes.

* :class:`IntervalRunner` calls a function every N seconds. Continuous mode is
  one of these, and so is :class:`PollingWatcher`, the watcher for a backend
  that cannot report changes by itself.
* :class:`Debouncer` collects the paths a filesystem observer reports and hands
  them over as one batch once they stop arriving, so saving one file ten times
  is one verification.
* :class:`WatchHandle` is what ``IntegrityMonitor.watch()`` returns.

The watchdog-based watcher for a local directory is in
:mod:`automation_file.integrity.local_watcher`, which is imported only when a
local target is watched.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from types import TracebackType
from typing import TypeVar

from automation_file.integrity.errors import IntegrityException

_DEFAULT_JOIN_TIMEOUT = 5.0
# A batch is handed over at the latest after this many quiet periods, however busy the tree.
_MAX_WAIT_FACTOR = 10.0

_HandleT = TypeVar("_HandleT", bound="WatchHandle")


class WatchHandle(ABC):
    """A running watch. ``stop()`` ends it; it is also a context manager."""

    #: ``"events"`` when the backend reports changes, ``"poll"`` when the tree is re-read.
    kind: str = ""

    @abstractmethod
    def start(self) -> None:
        """Begin watching. Starting a running watch changes nothing."""

    @abstractmethod
    def stop(self, timeout: float = _DEFAULT_JOIN_TIMEOUT) -> None:
        """Stop watching and wait up to ``timeout`` seconds for the threads to end."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the watch is active."""

    def __enter__(self: _HandleT) -> _HandleT:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()


class IntervalRunner:
    """Calls ``tick`` every ``interval`` seconds on a daemon thread, first after one interval."""

    def __init__(self, tick: Callable[[], object], interval: float, *, name: str) -> None:
        if interval <= 0:
            raise IntegrityException("interval must be positive")
        self._tick = tick
        self._interval = float(interval)
        self._name = name
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop: threading.Event | None = None

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                return
            stop = threading.Event()
            thread = threading.Thread(target=self._run, args=(stop,), name=self._name, daemon=True)
            thread.start()
            self._thread, self._stop = thread, stop

    def stop(self, timeout: float = _DEFAULT_JOIN_TIMEOUT) -> None:
        with self._lock:
            thread, stop = self._thread, self._stop
            self._thread = self._stop = None
        if stop is not None:
            stop.set()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _run(self, stop: threading.Event) -> None:
        while not stop.wait(self._interval):
            self._tick()


class PollingWatcher(WatchHandle):
    """Watches by re-reading: calls ``tick`` every ``interval`` seconds."""

    kind = "poll"

    def __init__(self, tick: Callable[[], object], interval: float) -> None:
        self._runner = IntervalRunner(tick, interval, name="fa-integrity-poll")

    @property
    def is_running(self) -> bool:
        return self._runner.is_running

    def start(self) -> None:
        self._runner.start()

    def stop(self, timeout: float = _DEFAULT_JOIN_TIMEOUT) -> None:
        self._runner.stop(timeout)


class Debouncer:
    """Collects paths and delivers them as one batch after ``delay`` seconds of quiet."""

    def __init__(self, deliver: Callable[[frozenset[str]], object], delay: float) -> None:
        if delay < 0:
            raise IntegrityException("debounce must not be negative")
        self._deliver = deliver
        self._delay = float(delay)
        self._wake = threading.Condition()
        self._pending: set[str] = set()
        self._first = 0.0
        self._last = 0.0
        self._stopped = False
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        with self._wake:
            self._stopped = False
        thread = threading.Thread(target=self._run, name="fa-integrity-debounce", daemon=True)
        thread.start()
        self._thread = thread

    def add(self, path: str) -> None:
        """Note that ``path`` changed; the batch it joins is delivered once things settle."""
        with self._wake:
            now = time.monotonic()
            if not self._pending:
                self._first = now
            self._pending.add(path)
            self._last = now
            self._wake.notify_all()

    def stop(self, timeout: float = _DEFAULT_JOIN_TIMEOUT) -> None:
        """Stop the thread; paths that were not delivered yet are dropped."""
        with self._wake:
            self._stopped = True
            self._pending.clear()
            self._wake.notify_all()
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            batch = self._next_batch()
            if batch is None:
                return
            self._deliver(batch)

    def _next_batch(self) -> frozenset[str] | None:
        """Wait for paths, then for them to stop arriving; ``None`` once stopped."""
        with self._wake:
            while not self._pending and not self._stopped:
                self._wake.wait()
            while not self._stopped:
                due = min(self._last + self._delay, self._first + self._delay * _MAX_WAIT_FACTOR)
                remaining = due - time.monotonic()
                if remaining <= 0:
                    break
                self._wake.wait(remaining)
            if self._stopped:
                return None
            batch = frozenset(self._pending)
            self._pending.clear()
            return batch
