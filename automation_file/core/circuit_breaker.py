"""Three-state circuit breaker.

States: CLOSED (normal), OPEN (short-circuit after ``failure_threshold``
consecutive failures), HALF_OPEN (trial one call after ``recovery_timeout``
seconds; one success closes, one failure re-opens). Failures are counted
only for exceptions in ``retriable`` — internal errors surface as-is.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from automation_file.exceptions import CircuitOpenException
from automation_file.logging_config import file_automation_logger

F = TypeVar("F", bound=Callable[..., Any])

_STATE_CLOSED = "closed"
_STATE_OPEN = "open"
_STATE_HALF_OPEN = "half_open"


class CircuitBreaker:
    """Open-close-half-open breaker.

    ``failure_threshold`` — consecutive failures that trip the breaker.
    ``recovery_timeout`` — seconds spent in OPEN before transitioning to HALF_OPEN.
    ``retriable`` — exception types counted as failures; other exceptions pass through.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        retriable: tuple[type[BaseException], ...] = (Exception,),
        name: str = "circuit",
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be > 0")
        self._failure_threshold = failure_threshold
        self._recovery_timeout = float(recovery_timeout)
        self._retriable = retriable
        self._name = name
        self._state = _STATE_CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_transition_locked()
            return self._state

    def _maybe_transition_locked(self) -> None:
        if self._state == _STATE_OPEN and (
            time.monotonic() - self._opened_at >= self._recovery_timeout
        ):
            self._state = _STATE_HALF_OPEN
            file_automation_logger.info("circuit %s: open -> half_open", self._name)

    def _on_success_locked(self) -> None:
        if self._state == _STATE_HALF_OPEN:
            file_automation_logger.info("circuit %s: half_open -> closed", self._name)
        self._state = _STATE_CLOSED
        self._failures = 0

    def _on_failure_locked(self) -> None:
        self._failures += 1
        if self._state == _STATE_HALF_OPEN or self._failures >= self._failure_threshold:
            self._state = _STATE_OPEN
            self._opened_at = time.monotonic()
            file_automation_logger.warning(
                "circuit %s: opened after %d failures", self._name, self._failures
            )

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Invoke ``func`` through the breaker."""
        with self._lock:
            self._maybe_transition_locked()
            if self._state == _STATE_OPEN:
                raise CircuitOpenException(f"circuit {self._name!r} is open")
        try:
            result = func(*args, **kwargs)
        except self._retriable as error:
            with self._lock:
                self._on_failure_locked()
            raise error
        with self._lock:
            self._on_success_locked()
        return result

    def wraps(self) -> Callable[[F], F]:
        """Return a decorator that routes every call through :meth:`call`."""

        def decorator(func: F) -> F:
            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return self.call(func, *args, **kwargs)

            return wrapper  # type: ignore[return-value]

        return decorator

    def reset(self) -> None:
        """Force the breaker back to CLOSED, clearing failure count."""
        with self._lock:
            self._state = _STATE_CLOSED
            self._failures = 0
            self._opened_at = 0.0
