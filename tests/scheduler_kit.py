"""What the scheduler tests share: a clock set by hand, a gate, and a scheduler driven by ``tick``.

No test waits for a real minute. A :class:`Rig` owns a scheduler that has no
background thread, a clock the test moves, and a private event bus whose events
it collects.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Any

from automation_file import executor
from automation_file.events import Event, EventBus
from automation_file.scheduler import JobRun, Scheduler

START = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)
WAIT = 5.0
_POLL = 0.005
_PREFIX = "scheduler_test_"


def wait_until(predicate: Callable[[], object], timeout: float = WAIT) -> bool:
    """Poll ``predicate`` until it is true or ``timeout`` seconds passed; return its last word."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL)
    return bool(predicate())


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float = 0.0, minutes: float = 0.0) -> datetime:
        self.now += timedelta(seconds=seconds, minutes=minutes)
        return self.now


class Gate:
    """An action that blocks until the test opens it."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.opened = threading.Event()
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        self.entered.set()
        self.opened.wait(WAIT)
        return "through"

    def await_entry(self) -> None:
        assert self.entered.wait(WAIT), "the gated action never started"

    def open(self) -> None:
        self.opened.set()


class Rig:
    """A scheduler driven by hand, with its clock, its bus and every event published on it."""

    def __init__(self, **options: Any) -> None:
        self.clock = FakeClock()
        self.bus = EventBus()
        self.events: list[Event] = []
        self.bus.subscribe(self.events.append)
        options.setdefault("autostart", False)
        self.engine = Scheduler(clock=self.clock, bus=self.bus, **options)
        self._commands: list[str] = []
        self._gates: list[Gate] = []

    def __enter__(self) -> Rig:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        for gate in self._gates:
            gate.open()
        self.engine.remove_all()
        self.engine.shutdown(cancel_running=True)
        for name in self._commands:
            executor.registry.unregister(name)

    def command(self, name: str, function: Callable[..., Any]) -> str:
        """Register ``function`` on the shared executor and return the action name to use."""
        registered = f"{_PREFIX}{name}"
        executor.registry.register(registered, function)
        self._commands.append(registered)
        return registered

    def gate(self, name: str = "gate") -> tuple[str, Gate]:
        """Register a blocking action; return its action name and the gate that releases it."""
        gate = Gate()
        self._gates.append(gate)
        return self.command(name, gate), gate

    def tick(self, seconds: float = 0.0, minutes: float = 0.0) -> list[JobRun]:
        """Move the clock forward and tick the scheduler once."""
        self.clock.advance(seconds=seconds, minutes=minutes)
        return self.engine.tick()

    def errors(self) -> list[Event]:
        """The ``scheduler.error`` events published so far."""
        return [event for event in self.events if event.type == "scheduler.error"]

    def job(self, name: str) -> dict[str, Any]:
        """The current snapshot of the job ``name``."""
        return next(job for job in self.engine.list() if job["name"] == name)

    def idle(self, name: str) -> bool:
        """Wait until the job ``name`` no longer counts as running."""
        return wait_until(lambda: not self.job(name)["running"])

    def runs(self, job: str) -> list[JobRun]:
        """The records of ``job``, newest first."""
        return self.engine.history(job=job)
