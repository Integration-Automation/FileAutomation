"""The scheduler: run action lists and pipelines on a schedule, on an event, or by hand.

A :class:`ScheduledJob` pairs a target (a JSON action list or a
:class:`~automation_file.pipeline.Pipeline`) with triggers:

* :class:`CronTrigger`: a 5-field cron expression (minute hour dom month dow)
  with an optional IANA time zone;
* :class:`FileTrigger`: a file event under a watched path;
* :class:`EventTrigger`: an event on the bus, which is also how a webhook that
  publishes one fires a job;
* :class:`PipelineTrigger`: the end of another pipeline's run;
* no trigger at all: the job is fired by hand (``Scheduler.run_now``).

Every firing leaves a :class:`JobRun` in one of the :class:`RunState` values
``scheduled``, ``started``, ``completed``, ``failed``, ``skipped``, ``timeout``
and ``cancelled``. The module-level :data:`scheduler` owns a background thread
that wakes every second, fires the cron jobs that are due and ends the runs
whose timeout has passed.
"""

from __future__ import annotations

from automation_file.scheduler.cron import CronException, CronExpression, resolve_timezone
from automation_file.scheduler.errors import SchedulerException
from automation_file.scheduler.job import ScheduledJob
from automation_file.scheduler.manager import (
    Scheduler,
    register_scheduler_ops,
    schedule_add,
    schedule_cancel,
    schedule_history,
    schedule_job,
    schedule_list,
    schedule_pipeline,
    schedule_remove,
    schedule_remove_all,
    schedule_run,
    scheduler,
)
from automation_file.scheduler.runs import JobRun, RunHistory, RunState, TriggerKind
from automation_file.scheduler.triggers import (
    CronTrigger,
    EventTrigger,
    FileTrigger,
    PipelineTrigger,
    Trigger,
    trigger_from_dict,
)

__all__ = [
    "CronException",
    "CronExpression",
    "CronTrigger",
    "EventTrigger",
    "FileTrigger",
    "JobRun",
    "PipelineTrigger",
    "RunHistory",
    "RunState",
    "ScheduledJob",
    "Scheduler",
    "SchedulerException",
    "Trigger",
    "TriggerKind",
    "register_scheduler_ops",
    "resolve_timezone",
    "schedule_add",
    "schedule_cancel",
    "schedule_history",
    "schedule_job",
    "schedule_list",
    "schedule_pipeline",
    "schedule_remove",
    "schedule_remove_all",
    "schedule_run",
    "scheduler",
    "trigger_from_dict",
]
