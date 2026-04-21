"""Per-action quota enforcement.

``Quota`` bundles a maximum byte size and maximum duration. Callers use
``Quota.check_size(bytes)`` before an I/O-heavy action and wrap the action in
``with quota.time_budget(label):`` to bound wall-clock time.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from automation_file.exceptions import QuotaExceededException
from automation_file.logging_config import file_automation_logger


@dataclass(frozen=True)
class Quota:
    """Bundle of per-action limits.

    ``max_bytes`` <= 0 means no size cap; ``max_seconds`` <= 0 means no time
    cap. Defaults allow callers to share one ``Quota`` instance across many
    actions with fine-grained overrides at each call site.
    """

    max_bytes: int = 0
    max_seconds: float = 0.0

    def check_size(self, nbytes: int, label: str = "action") -> None:
        """Raise :class:`QuotaExceededException` if ``nbytes`` exceeds the cap."""
        if self.max_bytes > 0 and nbytes > self.max_bytes:
            raise QuotaExceededException(
                f"{label} size {nbytes} exceeds quota {self.max_bytes}"
            )

    @contextmanager
    def time_budget(self, label: str = "action") -> Iterator[None]:
        """Context manager that raises if the enclosed block runs past the cap."""
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            if self.max_seconds > 0 and elapsed > self.max_seconds:
                file_automation_logger.warning(
                    "quota: %s took %.2fs > %.2fs", label, elapsed, self.max_seconds,
                )
                raise QuotaExceededException(
                    f"{label} took {elapsed:.2f}s exceeding quota {self.max_seconds:.2f}s"
                )

    def wraps(self, label: str, size_fn=None):
        """Return a decorator that enforces the time budget around ``func``.

        If ``size_fn`` is provided it is called with the function's return
        value to derive a byte count for :meth:`check_size`.
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                with self.time_budget(label):
                    result = func(*args, **kwargs)
                if size_fn is not None:
                    self.check_size(int(size_fn(result)), label=label)
                return result
            return wrapper
        return decorator
