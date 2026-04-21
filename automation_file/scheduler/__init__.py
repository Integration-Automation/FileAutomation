"""Cron-style scheduler — run action lists on a recurring schedule.

A :class:`ScheduledJob` pairs a 5-field cron expression (minute hour dom month
dow) with a JSON action list. The module-level :data:`scheduler` owns a
background thread that wakes every second, checks which jobs are due, and
dispatches their action lists through the shared
:class:`~automation_file.core.action_executor.ActionExecutor`.
"""

from __future__ import annotations

from automation_file.scheduler.cron import CronException, CronExpression
from automation_file.scheduler.manager import (
    ScheduledJob,
    Scheduler,
    register_scheduler_ops,
    schedule_add,
    schedule_list,
    schedule_remove,
    schedule_remove_all,
    scheduler,
)

__all__ = [
    "CronException",
    "CronExpression",
    "ScheduledJob",
    "Scheduler",
    "register_scheduler_ops",
    "schedule_add",
    "schedule_list",
    "schedule_remove",
    "schedule_remove_all",
    "scheduler",
]
