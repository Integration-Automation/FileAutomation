"""Stand-ins for the GUI tests: a thread pool that runs its work at once.

A page hands every service call to a thread pool through ``ActionWorker``. With
:class:`SyncPool` the worker runs in the calling thread, so its ``finished`` and
``failed`` signals are delivered before ``start`` returns and a test can look at
the page right after triggering an action, without an event loop.
"""

from __future__ import annotations

from typing import Any


class SyncPool:
    """Runs each worker immediately, in the thread that starts it."""

    def __init__(self) -> None:
        self.started = 0

    def start(self, worker: Any) -> None:
        self.started += 1
        worker.run()


class HeldPool:
    """Keeps the workers it is given until :meth:`release`, to test what a page does meanwhile."""

    def __init__(self) -> None:
        self.held: list[Any] = []

    def start(self, worker: Any) -> None:
        self.held.append(worker)

    def release(self) -> int:
        """Run every held worker; return how many there were."""
        held, self.held = self.held, []
        for worker in held:
            worker.run()
        return len(held)
