"""Background scheduler for cron-scheduled action lists.

The scheduler thread wakes once a minute (aligned to wall-clock minute
boundaries), iterates registered jobs, and dispatches each matching job's
action list through the shared :class:`ActionExecutor`. Dispatch happens on a
short-lived worker thread so a long-running action cannot block subsequent
jobs — but callers are still responsible for keeping their action lists
reasonable in duration.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Any

from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.scheduler.cron import CronExpression


class SchedulerException(FileAutomationException):
    """Raised for duplicate / missing / invalid scheduled jobs."""


@dataclass
class ScheduledJob:
    """One named cron expression paired with an action list."""

    name: str
    cron: CronExpression
    action_list: list[list[Any]]
    last_run: dt.datetime | None = field(default=None)
    runs: int = field(default=0)
    allow_overlap: bool = field(default=False)
    running: bool = field(default=False)
    skipped: int = field(default=0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cron": self.cron.source,
            "actions": len(self.action_list),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "runs": self.runs,
            "allow_overlap": self.allow_overlap,
            "running": self.running,
            "skipped": self.skipped,
        }


class Scheduler:
    """Process-wide scheduler — one background thread drives every job."""

    _TICK_SECONDS = 1.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, ScheduledJob] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _ensure_running(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="fa-scheduler", daemon=True)
        thread.start()
        self._thread = thread

    def _run(self) -> None:
        last_minute: tuple[int, int, int, int, int] | None = None
        while not self._stop.is_set():
            now = dt.datetime.now().replace(second=0, microsecond=0)
            key = (now.year, now.month, now.day, now.hour, now.minute)
            if key != last_minute:
                last_minute = key
                self._fire_due(now)
            self._stop.wait(self._TICK_SECONDS)

    def _fire_due(self, moment: dt.datetime) -> None:
        with self._lock:
            due = [job for job in self._jobs.values() if job.cron.matches(moment)]
        for job in due:
            self._dispatch(job, moment)

    def _dispatch(self, job: ScheduledJob, moment: dt.datetime) -> None:
        with self._lock:
            if job.running and not job.allow_overlap:
                job.skipped += 1
                file_automation_logger.warning(
                    "scheduler[%s]: previous run still active — skipping (skipped=%d)",
                    job.name,
                    job.skipped,
                )
                return
            job.running = True
            job.last_run = moment
            job.runs += 1
            run_no = job.runs
        file_automation_logger.info(
            "scheduler[%s]: firing at %s (run #%d)", job.name, moment.isoformat(), run_no
        )
        worker = threading.Thread(
            target=self._run_job,
            args=(job,),
            name=f"fa-scheduler-{job.name}",
            daemon=True,
        )
        worker.start()

    def _run_job(self, job: ScheduledJob) -> None:
        try:
            _safe_execute(job.name, job.action_list)
        finally:
            with self._lock:
                job.running = False

    def add(
        self,
        name: str,
        cron_expression: str,
        action_list: list[list[Any]],
        *,
        allow_overlap: bool = False,
    ) -> dict[str, Any]:
        cron = CronExpression.parse(cron_expression)
        with self._lock:
            if name in self._jobs:
                raise SchedulerException(f"job already registered: {name}")
            job = ScheduledJob(
                name=name,
                cron=cron,
                action_list=list(action_list),
                allow_overlap=allow_overlap,
            )
            self._jobs[name] = job
            snapshot = job.as_dict()
        self._ensure_running()
        file_automation_logger.info(
            "scheduler: added job %r (cron=%r allow_overlap=%s)",
            name,
            cron.source,
            allow_overlap,
        )
        return snapshot

    def remove(self, name: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.pop(name, None)
        if job is None:
            raise SchedulerException(f"no such job: {name}")
        file_automation_logger.info("scheduler: removed job %r", name)
        return job.as_dict()

    def remove_all(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshots = [job.as_dict() for job in self._jobs.values()]
            self._jobs.clear()
        return snapshots

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.as_dict() for job in self._jobs.values()]

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._jobs


def _safe_execute(job_name: str, action_list: list[list[Any]]) -> None:
    from automation_file.core.action_executor import executor
    from automation_file.notify.manager import notify_on_failure

    try:
        executor.execute_action(action_list)
    except FileAutomationException as error:
        file_automation_logger.warning("scheduler[%s]: dispatch failed: %r", job_name, error)
        notify_on_failure(f"scheduler[{job_name}]", error)


scheduler: Scheduler = Scheduler()


def schedule_add(
    name: str,
    cron_expression: str,
    action_list: list[list[Any]],
    *,
    allow_overlap: bool = False,
) -> dict[str, Any]:
    """Register a named job that fires ``action_list`` on ``cron_expression``.

    When ``allow_overlap`` is False (the default), a tick that fires while a
    previous run is still active is skipped and counted in ``skipped``.
    """
    return scheduler.add(name, cron_expression, action_list, allow_overlap=allow_overlap)


def schedule_remove(name: str) -> dict[str, Any]:
    """Remove the named job."""
    return scheduler.remove(name)


def schedule_remove_all() -> list[dict[str, Any]]:
    """Remove every registered job and return their final snapshots."""
    return scheduler.remove_all()


def schedule_list() -> list[dict[str, Any]]:
    """Return a snapshot of every registered job."""
    return scheduler.list()


def register_scheduler_ops(registry: ActionRegistry) -> None:
    """Wire ``FA_schedule_*`` actions into a registry."""
    registry.register_many(
        {
            "FA_schedule_add": schedule_add,
            "FA_schedule_remove": schedule_remove,
            "FA_schedule_remove_all": schedule_remove_all,
            "FA_schedule_list": schedule_list,
        }
    )
