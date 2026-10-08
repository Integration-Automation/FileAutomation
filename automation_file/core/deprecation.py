"""Retire a public name without breaking the code that still uses it.

The deprecation policy (``docs``: *Public API and compatibility*) is that a
deprecated name keeps working for at least two minor releases, warns each time it
is used, names its replacement, and is removed only in a major release. This
module is the one way to do the warning half. Python hides a
``DeprecationWarning`` raised outside ``__main__`` by default, and an action list
run from JSON has no ``__main__`` of the user's, so each message is also logged
once per process:

.. code-block:: python

    @deprecated(since="1.1", removal="2.0", replacement="automation_file.File.copy_to")
    def copy_between(source, target): ...

    warn_deprecated("the 'manager=' argument", since="1.1", removal="2.0",
                    replacement="a notification route")
"""

from __future__ import annotations

import functools
import threading
import warnings
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from automation_file.logging_config import file_automation_logger

_P = ParamSpec("_P")
_R = TypeVar("_R")
_logged: set[str] = set()
_logged_guard = threading.Lock()


def deprecation_message(what: str, *, since: str, removal: str, replacement: str | None) -> str:
    """Return the standard wording: what is deprecated, since when, until when, what to use."""
    message = f"{what} is deprecated since {since} and will be removed in {removal}"
    return f"{message}; use {replacement} instead" if replacement else message


def warn_deprecated(
    what: str,
    *,
    since: str,
    removal: str,
    replacement: str | None = None,
    stacklevel: int = 2,
) -> None:
    """Emit a :class:`DeprecationWarning` attributed to the caller of the deprecated thing.

    The same message is logged at warning level the first time it occurs in a process.
    """
    message = deprecation_message(what, since=since, removal=removal, replacement=replacement)
    with _logged_guard:
        first = message not in _logged
        _logged.add(message)
    if first:
        file_automation_logger.warning("%s", message)
    warnings.warn(message, DeprecationWarning, stacklevel=stacklevel + 1)


def deprecated(
    *, since: str, removal: str, replacement: str | None = None
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Mark a function or method as deprecated; calling it warns, then runs it unchanged."""

    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        what = f"{function.__module__}.{function.__qualname__}"

        @functools.wraps(function)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            warn_deprecated(what, since=since, removal=removal, replacement=replacement)
            return function(*args, **kwargs)

        wrapper.__deprecated__ = deprecation_message(  # type: ignore[attr-defined]
            what, since=since, removal=removal, replacement=replacement
        )
        return wrapper

    return decorate
