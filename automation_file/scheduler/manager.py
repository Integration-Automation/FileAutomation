"""The scheduler: every job, whatever fires it, runs through here and leaves a record.

A job pairs a target (an action list or a pipeline) with triggers: cron
expressions with an optional time zone, file events, events on the bus, the end
of another pipeline's run, or none at all for a job that is only fired by hand.
One background thread wakes every second: it fires the cron jobs due in the
current minute and closes the runs whose timeout has passed. Every run gets a
thread of its own, so a long job cannot hold up the others.

Overlap protection is part of the contract: unless a job says
``allow_overlap``, a firing that arrives while the job is still running is
recorded as ``skipped`` and nothing is started.

The module-level :data:`scheduler` is the process-wide instance behind the
``FA_schedule_*`` actions.
"""

from __future__ import annotations

import datetime as dt
import math
import threading
from collections.abc import Mapping
from functools import partial
from typing import Any

from automation_file.core.action_registry import ActionRegistry
from automation_file.core.progress import CancellationToken
from automation_file.events import Event, EventBus, event_bus
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.scheduler.dispatch import Clock, Dispatcher, Firing, Services
from automation_file.scheduler.errors import SchedulerException
from automation_file.scheduler.job import ScheduledJob
from automation_file.scheduler.runs import (
    DEFAULT_HISTORY,
    DEFAULT_QUERY_LIMIT,
    JobRun,
    RunHistory,
    RunState,
    TriggerKind,
    as_utc,
)
from automation_file.scheduler.targets import (
    Outcome,
    describe,
    fill_params,
    load_pipeline,
    run_actions,
)
from automation_file.scheduler.triggers import (
    CronTrigger,
    Disarm,
    TriggerPort,
    as_triggers,
)

_LISTED_FAILURES = 5
_MAX_TIMEOUT = 366 * 24 * 3600.0


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _checked_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise SchedulerException(f"job name: expected a non-empty string, got {name!r}")
    return name


def _checked_timeout(timeout: Any) -> float | None:
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise SchedulerException(f"timeout: expected seconds above 0, got {timeout!r}")
    if not math.isfinite(timeout) or not 0 < timeout <= _MAX_TIMEOUT:
        raise SchedulerException(
            f"timeout: expected seconds above 0 and at most a year, got {timeout!r}"
        )
    return float(timeout)


def _checked_params(params: Any) -> dict[str, Any]:
    if params is None:
        return {}
    if not isinstance(params, Mapping):
        raise SchedulerException(f"params: expected a mapping, got {type(params).__name__}")
    try:
        fill_params(params, _utc_now())
    except ValueError as error:
        raise SchedulerException(f"params: a ${{date:...}} format is not valid: {error}") from error
    return dict(params)


def _disarm(name: str, disarms: list[Disarm]) -> None:
    """Stop the watchers and subscriptions of one job; one that fails does not keep the rest."""
    for disarm in disarms:
        try:
            disarm()
        except (RuntimeError, OSError) as error:
            file_automation_logger.error(
                "scheduler[%s]: a trigger could not be stopped: %r", name, error
            )


def _safe_execute(
    job_name: str,
    action_list: list[list[Any]],
    cancel: CancellationToken | None = None,
) -> Outcome:
    """Run ``action_list`` and say how it went; never raises for a failing list.

    An action that raises fails the run and the list goes on. A list the
    executor rejects is reported through ``notify_on_failure``, which publishes
    the ``scheduler.error`` event itself.
    """
    from automation_file.notify.manager import notify_on_failure

    try:
        failures = run_actions(action_list, CancellationToken() if cancel is None else cancel)
    except FileAutomationException as error:
        file_automation_logger.warning("scheduler[%s]: dispatch failed: %r", job_name, error)
        notify_on_failure(f"scheduler[{job_name}]", error)
        return Outcome(RunState.FAILED, describe(error), reported=True)
    if not failures:
        return Outcome(RunState.COMPLETED)
    listed = "; ".join(failures[:_LISTED_FAILURES])
    more = len(failures) - _LISTED_FAILURES
    if more > 0:
        listed = f"{listed}; and {more} more"
    return Outcome(
        RunState.FAILED, f"{len(failures)} of {len(action_list)} actions failed: {listed}"
    )


class Scheduler:
    """Process-wide scheduler — one background thread drives every job.

    ``clock`` returns the current time as an aware ``datetime`` (UTC by default)
    and ``bus`` is the event bus the scheduler listens and reports on (the
    process-wide one by default). ``history_limit`` bounds the remembered runs.
    With ``autostart=False`` no thread is started until :meth:`start` is called:
    drive the scheduler with :meth:`tick` instead, which is what the tests do.
    """

    _TICK_SECONDS = 1.0

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        bus: EventBus | None = None,
        history_limit: int = DEFAULT_HISTORY,
        autostart: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, ScheduledJob] = {}
        self._armed: dict[str, list[Disarm]] = {}
        self._clock: Clock = _utc_now if clock is None else clock
        self._bus = event_bus if bus is None else bus
        self._history = RunHistory(history_limit)
        self._runs = Dispatcher(
            Services(self._lock, self._bus, self._clock, self._history, _safe_execute)
        )
        self._autostart = autostart
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_minute: dt.datetime | None = None

    # ------------------------------------------------------------------ the clock

    def _ensure_running(self) -> None:
        if self._autostart:
            self.start()

    def start(self) -> None:
        """Start the background thread and arm every trigger; safe to call again.

        Needed after :meth:`shutdown`, and for a scheduler made with
        ``autostart=False``. Adding a job starts an ``autostart`` scheduler.
        """
        waiting: list[tuple[ScheduledJob, list[Disarm]]] = []
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                # A stop flag of its own: a thread that is slow to end still ends.
                stop = threading.Event()
                thread = threading.Thread(
                    target=self._run, args=(stop,), name="fa-scheduler", daemon=True
                )
                thread.start()
                self._stop, self._thread = stop, thread
            for name, job in self._jobs.items():
                if name not in self._armed:
                    self._armed[name] = []
                    waiting.append((job, self._armed[name]))
        for job, slot in waiting:
            try:
                self._arm(job, slot)
            except (FileAutomationException, OSError) as error:
                file_automation_logger.error(
                    "scheduler[%s]: its triggers could not be armed: %r", job.name, error
                )

    def _run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception as error:  # pylint: disable=broad-except
                # Boundary of the scheduler's thread: one bad tick must not end scheduling.
                file_automation_logger.error("scheduler: tick failed: %r", error)
            stop.wait(self._TICK_SECONDS)

    def tick(self, now: dt.datetime | None = None) -> list[JobRun]:
        """Bring the scheduler to ``now`` and return the records of what it fired.

        Runs whose timeout has passed are closed, and every cron job due in the
        minute of ``now`` is fired; a minute is handled once, however often it is
        ticked. ``now`` defaults to the scheduler's clock; a naive ``datetime``
        is taken as local time. The background thread calls this every second.
        """
        instant = as_utc(self._clock() if now is None else now)
        self._runs.expire(instant)
        minute = instant.replace(second=0, microsecond=0)
        with self._lock:
            if minute == self._last_minute:
                return []
            self._last_minute = minute
        return self._fire_due(minute, instant)

    def _fire_due(self, minute: dt.datetime, now: dt.datetime | None = None) -> list[JobRun]:
        with self._lock:
            jobs = list(self._jobs.values())
        fired: list[JobRun] = []
        for job in jobs:
            trigger = job.due(minute)
            if trigger is None:
                continue
            detail = {"cron": trigger.cron, "timezone": trigger.timezone}
            firing = Firing(TriggerKind.CRON, minute, now, detail)
            fired.append(self._dispatch(job, trigger.moment(minute), firing))
        return fired

    def _dispatch(
        self, job: ScheduledJob, moment: dt.datetime, firing: Firing | None = None
    ) -> JobRun:
        """Fire ``job`` at ``moment`` (the time as the job reads it); skip it if it overlaps."""
        chosen = Firing(TriggerKind.CRON, as_utc(moment)) if firing is None else firing
        return self._runs.dispatch(job, moment, chosen)

    def _fire(
        self,
        name: str,
        kind: TriggerKind,
        detail: Mapping[str, Any],
        cause: Event | None = None,
    ) -> JobRun | None:
        """A trigger's moment has come: fire the job ``name`` unless it is gone.

        ``cause`` is the event that fired it; a run of this scheduler that
        published the event makes the new run one link longer in its chain.
        """
        with self._lock:
            job = self._jobs.get(name)
        if job is None:
            return None
        now = as_utc(self._clock())
        depth = 0 if cause is None else self._runs.depth_after(cause)
        return self._dispatch(job, job.local(now), Firing(kind, now, detail=detail, depth=depth))

    # ------------------------------------------------------------------ jobs

    def add(
        self,
        name: str,
        cron_expression: str,
        action_list: list[list[Any]],
        *,
        allow_overlap: bool = False,
        timezone: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Register an action list on a cron expression and return the job's snapshot.

        ``timezone`` is an IANA name (``"Asia/Taipei"``) or ``"UTC"``; without it
        the expression is read in local time. ``timeout`` is in seconds.
        """
        trigger = CronTrigger(cron_expression, timezone)
        job = ScheduledJob(
            name=name,
            cron=trigger.expression,
            action_list=list(action_list),
            allow_overlap=allow_overlap,
            triggers=(trigger,),
            timeout=_checked_timeout(timeout),
        )
        return self._register(job)

    def add_job(
        self,
        name: str,
        target: Any,
        *,
        triggers: Any = None,
        allow_overlap: bool = False,
        timeout: float | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a job with any triggers and return its snapshot.

        ``target`` is an action list, or a pipeline: a ``Pipeline``, a definition
        mapping or the path of a definition file. ``triggers`` is one trigger or
        several (objects or their mappings); without any, the job runs only when
        it is fired with :meth:`run_now`. ``params`` are the parameters of a
        pipeline's runs; ``${date:FORMAT}`` in them is filled in at every firing.
        A pipeline's own ``schedule`` is not read here: see :meth:`add_pipeline`.
        """
        is_actions = isinstance(target, (list, tuple))
        if is_actions and params:
            raise SchedulerException("params belong to a pipeline; an action list takes none")
        job = ScheduledJob(
            name=_checked_name(name),
            cron=None,
            action_list=list(target) if is_actions else [],
            allow_overlap=bool(allow_overlap),
            triggers=as_triggers(triggers),
            pipeline=None if is_actions else load_pipeline(target),
            params=_checked_params(params),
            timeout=_checked_timeout(timeout),
        )
        return self._register(job)

    def add_pipeline(
        self,
        pipeline: Any,
        *,
        name: str | None = None,
        triggers: Any = None,
        allow_overlap: bool = False,
        timeout: float | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a pipeline as a job, on the schedule it declares.

        ``pipeline`` is a ``Pipeline``, a definition mapping or the path of a
        definition file. Its ``schedule`` becomes a cron trigger, time zone
        included; ``triggers`` adds more. The job is named after the pipeline
        unless ``name`` is given. A definition file is read once, now: remove the
        job and register it again after changing the file.
        """
        loaded = load_pipeline(pipeline)
        chosen = as_triggers(triggers)
        if loaded.schedule is not None:
            schedule = CronTrigger(loaded.schedule.cron, loaded.schedule.timezone)
            chosen = (schedule, *chosen)
        return self.add_job(
            loaded.name if name is None else name,
            loaded,
            triggers=chosen,
            allow_overlap=allow_overlap,
            timeout=timeout,
            params=params,
        )

    def _register(self, job: ScheduledJob) -> dict[str, Any]:
        slot: list[Disarm] = []
        with self._lock:
            if job.name in self._jobs:
                raise SchedulerException(f"job already registered: {job.name}")
            self._jobs[job.name] = job
            self._armed[job.name] = slot
            snapshot = job.as_dict()
        armed = False
        try:
            self._arm(job, slot)
            armed = True
        finally:
            if not armed:
                with self._lock:
                    if self._jobs.get(job.name) is job:
                        del self._jobs[job.name]
        self._ensure_running()
        file_automation_logger.info(
            "scheduler: added job %r (cron=%r target=%s allow_overlap=%s)",
            job.name,
            snapshot["cron"],
            job.target,
            job.allow_overlap,
        )
        return snapshot

    def _arm(self, job: ScheduledJob, slot: list[Disarm]) -> None:
        """Start the job's watchers and subscriptions; on failure none of them is left.

        ``slot`` is the list registered for the job in ``_armed``. When the job
        was removed, or the scheduler shut down, while its triggers were being
        armed, the slot is no longer registered and what was armed is stopped.
        """
        port = TriggerPort(
            job=job.name,
            bus=self._bus,
            fire=partial(self._fire, job.name),
            is_own=partial(self._runs.is_own, job.name),
        )
        disarms: list[Disarm] = []
        armed = False
        try:
            for trigger in job.triggers:
                disarm = trigger.arm(port)
                if disarm is not None:
                    disarms.append(disarm)
            armed = True
        finally:
            with self._lock:
                registered = self._armed.get(job.name) is slot
                if registered and armed:
                    slot.extend(disarms)
                    disarms = []
                elif registered:
                    del self._armed[job.name]
            _disarm(job.name, disarms)

    def remove(self, name: str) -> dict[str, Any]:
        """Remove the job ``name`` and stop its triggers; a run in progress goes on."""
        with self._lock:
            job = self._jobs.pop(name, None)
            disarms = self._armed.pop(name, [])
        if job is None:
            raise SchedulerException(f"no such job: {name}")
        _disarm(name, disarms)
        file_automation_logger.info("scheduler: removed job %r", name)
        return job.as_dict()

    def remove_all(self) -> list[dict[str, Any]]:
        """Remove every job and stop every trigger; return the final snapshots."""
        with self._lock:
            jobs = list(self._jobs.values())
            armed = self._armed
            self._jobs.clear()
            self._armed = {}
        for name, disarms in armed.items():
            _disarm(name, disarms)
        return [job.as_dict() for job in jobs]

    # ------------------------------------------------------------------ runs

    def run_now(self, name: str) -> JobRun:
        """Fire the job ``name`` by hand and return the record of that firing.

        The record is ``skipped`` when the job is still running and does not
        allow overlap. ``record.wait(timeout)`` blocks until the run has ended.
        """
        with self._lock:
            job = self._jobs.get(name)
        if job is None:
            raise SchedulerException(f"no such job: {name}")
        now = as_utc(self._clock())
        return self._dispatch(job, job.local(now), Firing(TriggerKind.MANUAL, now))

    def cancel(self, name: str) -> list[JobRun]:
        """Cancel the runs in progress of the job ``name`` and return their records.

        The records become ``cancelled`` at once. A pipeline stops through its
        cancellation token; an action list stops before its next action, since
        the one in progress cannot be interrupted. The list is empty when the
        job is not running.
        """
        if not isinstance(name, str):
            raise SchedulerException(f"no such job: {name!r}")
        with self._lock:
            known = name in self._jobs
        cancelled = self._runs.cancel(name)
        if not known and not cancelled:
            raise SchedulerException(f"no such job: {name}")
        return cancelled

    def history(
        self,
        job: str | None = None,
        state: RunState | str | None = None,
        limit: int = DEFAULT_QUERY_LIMIT,
    ) -> list[JobRun]:
        """Return up to ``limit`` run records, newest first, of one job and/or in one state."""
        return self._history.query(job, state, limit)

    def list(self) -> list[dict[str, Any]]:
        """Return a snapshot of every registered job."""
        with self._lock:
            return [job.as_dict() for job in self._jobs.values()]

    def shutdown(self, timeout: float = 5.0, *, cancel_running: bool = False) -> None:
        """Stop the background thread, every file watcher and every bus subscription.

        The jobs stay registered and :meth:`start` brings them back. Runs in
        progress are left to finish unless ``cancel_running`` is set.
        """
        with self._lock:
            self._stop.set()
            thread = self._thread
            self._thread = None
            armed = self._armed
            self._armed = {}
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        for name, disarms in armed.items():
            _disarm(name, disarms)
        if cancel_running:
            self._runs.cancel()

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._jobs


scheduler: Scheduler = Scheduler()


def schedule_add(
    name: str,
    cron_expression: str,
    action_list: list[list[Any]],
    *,
    allow_overlap: bool = False,
    timezone: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Register a named job that fires ``action_list`` on ``cron_expression``.

    When ``allow_overlap`` is False (the default), a firing that arrives while a
    previous run is still active is skipped and counted in ``skipped``.
    ``timezone`` is an IANA name such as ``"Asia/Taipei"`` (local time without
    it) and ``timeout`` the seconds a run may take.
    """
    return scheduler.add(
        name,
        cron_expression,
        action_list,
        allow_overlap=allow_overlap,
        timezone=timezone,
        timeout=timeout,
    )


def schedule_remove(name: str) -> dict[str, Any]:
    """Remove the named job."""
    return scheduler.remove(name)


def schedule_remove_all() -> list[dict[str, Any]]:
    """Remove every registered job and return their final snapshots."""
    return scheduler.remove_all()


def schedule_list() -> list[dict[str, Any]]:
    """Return a snapshot of every registered job."""
    return scheduler.list()


def schedule_job(
    name: str,
    action_list: list[list[Any]],
    triggers: list[dict[str, Any]] | None = None,
    allow_overlap: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Register an action list fired by any triggers, or only by hand when there are none.

    Each trigger is a mapping with its ``kind`` (``cron``, ``file``, ``event``
    or ``pipeline``) and that kind's arguments.
    """
    if not isinstance(action_list, list):
        raise SchedulerException(
            f"action_list: expected a list of actions, got {type(action_list).__name__}"
        )
    return scheduler.add_job(
        name, action_list, triggers=triggers, allow_overlap=allow_overlap, timeout=timeout
    )


def schedule_pipeline(
    definition: Any,
    name: str | None = None,
    triggers: list[dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    allow_overlap: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Register a pipeline definition (a mapping or a YAML/JSON file path) as a job.

    The definition's ``schedule`` becomes a cron trigger with its time zone;
    ``triggers`` adds more. ``params`` are the parameters of every run, with
    ``${date:FORMAT}`` filled in when the job fires.
    """
    return scheduler.add_pipeline(
        definition,
        name=name,
        triggers=triggers,
        allow_overlap=allow_overlap,
        timeout=timeout,
        params=params,
    )


def schedule_run(name: str) -> dict[str, Any]:
    """Fire the named job now and return the record of that firing."""
    return scheduler.run_now(name).to_dict()


def schedule_history(
    job: str | None = None,
    state: str | None = None,
    limit: int = DEFAULT_QUERY_LIMIT,
) -> list[dict[str, Any]]:
    """Return the latest run records, newest first, of one job and/or in one state."""
    return [run.to_dict() for run in scheduler.history(job, state, limit)]


def schedule_cancel(name: str) -> list[dict[str, Any]]:
    """Cancel the runs in progress of the named job and return their records."""
    return [run.to_dict() for run in scheduler.cancel(name)]


def register_scheduler_ops(registry: ActionRegistry) -> None:
    """Wire ``FA_schedule_*`` actions into a registry."""
    registry.register_many(
        {
            "FA_schedule_add": schedule_add,
            "FA_schedule_remove": schedule_remove,
            "FA_schedule_remove_all": schedule_remove_all,
            "FA_schedule_list": schedule_list,
            "FA_schedule_job": schedule_job,
            "FA_schedule_pipeline": schedule_pipeline,
            "FA_schedule_run": schedule_run,
            "FA_schedule_history": schedule_history,
            "FA_schedule_cancel": schedule_cancel,
        }
    )
