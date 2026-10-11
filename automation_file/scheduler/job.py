"""A scheduled job: what fires it, what it runs, and its counters."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from automation_file.scheduler.cron import CronExpression
from automation_file.scheduler.errors import SchedulerException
from automation_file.scheduler.runs import TARGET_ACTIONS, TARGET_PIPELINE
from automation_file.scheduler.triggers import CronTrigger, PipelineTrigger, Trigger

if TYPE_CHECKING:
    from automation_file.pipeline import Pipeline


@dataclass
class ScheduledJob:
    """One named job: its triggers, its target and what happened to it so far.

    ``cron`` and ``timezone`` mirror the job's first cron trigger, and
    ``action_list`` is empty for a pipeline target. ``running`` stays true until
    the thread of the last run has really ended, also after a timeout or a
    cancellation, so that overlap protection never lets two runs collide.
    """

    name: str
    cron: CronExpression | None
    action_list: list[list[Any]]
    last_run: dt.datetime | None = field(default=None)
    runs: int = field(default=0)
    allow_overlap: bool = field(default=False)
    running: bool = field(default=False)
    skipped: int = field(default=0)
    timezone: str | None = field(default=None)
    triggers: tuple[Trigger, ...] = field(default=())
    pipeline: Pipeline | None = field(default=None)
    params: dict[str, Any] = field(default_factory=dict)
    timeout: float | None = field(default=None)
    last_state: str | None = field(default=None)
    active: int = field(default=0)

    def __post_init__(self) -> None:
        self.triggers = tuple(self.triggers)
        crons = [trigger for trigger in self.triggers if isinstance(trigger, CronTrigger)]
        if self.cron is not None and not crons:
            self.triggers = (CronTrigger(self.cron, self.timezone), *self.triggers)
        elif crons:
            self.cron = crons[0].expression
            self.timezone = crons[0].timezone
        if self.pipeline is None:
            return
        for trigger in self.triggers:
            if isinstance(trigger, PipelineTrigger) and trigger.pipeline == self.pipeline.name:
                raise SchedulerException(
                    f"job {self.name!r}: a pipeline cannot be fired by its own runs"
                )

    @property
    def target(self) -> str:
        """``"pipeline"`` or ``"actions"``: what the job runs."""
        return TARGET_ACTIONS if self.pipeline is None else TARGET_PIPELINE

    def due(self, instant: dt.datetime) -> CronTrigger | None:
        """Return the first cron trigger that fires at ``instant``, ``None`` when none does."""
        for trigger in self.triggers:
            if isinstance(trigger, CronTrigger) and trigger.due(instant):
                return trigger
        return None

    def local(self, instant: dt.datetime) -> dt.datetime:
        """Return ``instant`` in the job's own time: its first cron trigger's, else local time."""
        for trigger in self.triggers:
            if isinstance(trigger, CronTrigger):
                return trigger.moment(instant)
        return instant.astimezone().replace(tzinfo=None)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of the job."""
        return {
            "name": self.name,
            "cron": "" if self.cron is None else self.cron.source,
            "actions": len(self.action_list),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "runs": self.runs,
            "allow_overlap": self.allow_overlap,
            "running": self.running,
            "skipped": self.skipped,
            "timezone": self.timezone,
            "triggers": [trigger.to_dict() for trigger in self.triggers],
            "target": self.target,
            "pipeline": None if self.pipeline is None else self.pipeline.name,
            "timeout": self.timeout,
            "last_state": self.last_state,
        }
