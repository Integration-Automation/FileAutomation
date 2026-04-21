"""Conditional execution primitives for action lists.

``FA_if_exists`` / ``FA_if_newer`` / ``FA_if_size_gt`` dispatch one of two
inline action lists based on a filesystem predicate. Each branch is itself
an action list and is executed through the shared
:class:`~automation_file.core.action_executor.ActionExecutor`, so results /
errors are captured exactly the way a top-level invocation would be.

A branch may be ``None`` (or omitted) to mean "do nothing". The function
returns::

    {"matched": bool, "results": {...}}

where ``results`` is the return value of ``execute_action`` for the branch
that actually ran, or ``{}`` when the matching branch was empty.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger


def if_exists(
    path: str,
    then: list | None = None,
    else_: list | None = None,
) -> dict[str, Any]:
    """Run ``then`` when ``path`` exists, otherwise run ``else_``."""
    return _dispatch(Path(path).exists(), then, else_, reason=f"exists({path})")


def if_newer(
    path: str,
    reference: str,
    then: list | None = None,
    else_: list | None = None,
) -> dict[str, Any]:
    """Run ``then`` when ``path`` is newer than ``reference``.

    Missing ``path`` is treated as "not newer". Missing ``reference`` is
    treated as "anything else wins" — ``then`` runs.
    """
    source = Path(path)
    ref = Path(reference)
    if not source.exists():
        matched = False
    elif not ref.exists():
        matched = True
    else:
        matched = source.stat().st_mtime > ref.stat().st_mtime
    return _dispatch(matched, then, else_, reason=f"newer({path},{reference})")


def if_size_gt(
    path: str,
    bytes_threshold: int,
    then: list | None = None,
    else_: list | None = None,
) -> dict[str, Any]:
    """Run ``then`` when ``path`` exists and is strictly larger than ``bytes_threshold``."""
    if bytes_threshold < 0:
        raise FileAutomationException("bytes_threshold must be >= 0")
    source = Path(path)
    matched = source.is_file() and source.stat().st_size > bytes_threshold
    return _dispatch(matched, then, else_, reason=f"size_gt({path},{bytes_threshold})")


def _dispatch(
    matched: bool,
    then: list | None,
    else_: list | None,
    *,
    reason: str,
) -> dict[str, Any]:
    branch = then if matched else else_
    file_automation_logger.info("conditional %s -> matched=%s", reason, matched)
    if not branch:
        return {"matched": matched, "results": {}}
    # Deferred import keeps this module cheap to load and avoids an import cycle
    # with ActionExecutor at module-initialisation time.
    from automation_file.core.action_executor import executor

    return {"matched": matched, "results": executor.execute_action(branch)}
