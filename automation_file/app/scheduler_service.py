"""The Scheduler service: list, add and remove cron jobs.

.. code-block:: python

    from automation_file.app import app_services

    scheduler = app_services().scheduler
    scheduler.add("tick", "*/5 * * * *", [["FA_create_file", {"file_path": "tick.txt"}]])
    scheduler.jobs()                # [{"name": "tick", "cron": "*/5 * * * *", ...}]
    scheduler.remove("tick")

It calls the four scheduler functions that are public (``schedule_add``,
``schedule_remove``, ``schedule_remove_all``, ``schedule_list``) and nothing
else of the scheduler, so the scheduler's internals can change underneath it.
"""

from __future__ import annotations

from typing import Any

from automation_file.app.arguments import parse_json_text
from automation_file.app.errors import AppException
from automation_file.scheduler import (
    schedule_add,
    schedule_list,
    schedule_remove,
    schedule_remove_all,
)


def _action_list(actions: list[Any] | str) -> list[Any]:
    """Return the action list, read from JSON text when a form supplied text."""
    parsed = parse_json_text(actions, "the action list") if isinstance(actions, str) else actions
    if not isinstance(parsed, list) or not parsed:
        raise AppException("the action list must be a non-empty JSON array of actions")
    return parsed


class SchedulerService:
    """Cron jobs of the process-wide scheduler."""

    def jobs(self) -> list[dict[str, Any]]:
        """Return a snapshot of every registered job."""
        return [dict(job) for job in schedule_list()]

    def add(
        self, name: str, cron: str, actions: list[Any] | str, allow_overlap: bool = False
    ) -> dict[str, Any]:
        """Register the job ``name``: run ``actions`` whenever ``cron`` matches.

        ``actions`` is an action list or its JSON text. With ``allow_overlap``
        a tick fires even while the previous run of the job is still going.
        """
        if not name.strip() or not cron.strip():
            raise AppException("a scheduled job needs a name and a cron expression")
        action_list = _action_list(actions)
        if allow_overlap:
            return dict(schedule_add(name.strip(), cron.strip(), action_list, allow_overlap=True))
        return dict(schedule_add(name.strip(), cron.strip(), action_list))

    def remove(self, name: str) -> dict[str, Any]:
        """Remove the job ``name`` and return its last snapshot."""
        return dict(schedule_remove(name))

    def remove_all(self) -> list[dict[str, Any]]:
        """Remove every job and return their last snapshots."""
        return [dict(job) for job in schedule_remove_all()]
