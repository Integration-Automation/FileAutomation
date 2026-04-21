"""Retry helper for transient network failures.

``retry_on_transient`` is a small wrapper around exponential back-off. It is
intentionally dependency-free so that modules which do not actually use
``requests`` or ``googleapiclient`` can import it without pulling those in.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from automation_file.exceptions import RetryExhaustedException
from automation_file.logging_config import file_automation_logger

F = TypeVar("F", bound=Callable[..., Any])


def retry_on_transient(
    max_attempts: int = 3,
    backoff_base: float = 0.5,
    backoff_cap: float = 8.0,
    retriable: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError, OSError),
) -> Callable[[F], F]:
    """Return a decorator that retries ``retriable`` exceptions with back-off.

    On the final failure raises :class:`RetryExhaustedException` chained to the
    underlying error so callers can still inspect the cause.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retriable as error:
                    last_error = error
                    if attempt >= max_attempts:
                        break
                    delay = min(backoff_cap, backoff_base * (2 ** (attempt - 1)))
                    file_automation_logger.warning(
                        "retry_on_transient: %s attempt %d/%d failed (%r); sleeping %.2fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        error,
                        delay,
                    )
                    time.sleep(delay)
            raise RetryExhaustedException(
                f"{func.__name__} failed after {max_attempts} attempts"
            ) from last_error

        return wrapper  # type: ignore[return-value]

    return decorator
