"""IntegrityMonitor: is this tree still what was approved?

.. code-block:: python

    from automation_file.integrity import IntegrityMonitor

    monitor = IntegrityMonitor(
        "s3://reports/2026",
        baseline="local:///var/lib/fa/reports.baseline.json",
    )
    monitor.create_baseline()            # approve what is there now
    report = monitor.verify()            # a DriftReport; drift is published as an event
    monitor.accept(report)               # approve what the report saw

Four modes share one comparison:

``snapshot``
    :meth:`IntegrityMonitor.snapshot` reads the tree and stores nothing.
``verify``
    :meth:`IntegrityMonitor.verify` compares the tree with the baseline once.
``watch``
    :meth:`IntegrityMonitor.watch` reacts to changes: filesystem events for a
    local target, a quick re-read on a timer for any other backend.
``continuous``
    :meth:`IntegrityMonitor.start` verifies every ``interval`` seconds on a
    thread until :meth:`IntegrityMonitor.stop`.

The monitor only reads, unless a
:class:`~automation_file.integrity.remediation.RemediationPolicy` is passed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypedDict

from automation_file.events.bus import EventBus
from automation_file.events.context import correlation_scope
from automation_file.exceptions import FileAutomationException
from automation_file.integrity.alerts import AlertEngine, AlertPolicy
from automation_file.integrity.baseline import BaselineManager, is_baseline_path
from automation_file.integrity.detector import detect_changes
from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.hashing import DEFAULT_ALGORITHM, HashEngine
from automation_file.integrity.legacy import LegacyHooks, OnDrift, error_summary, summary_of
from automation_file.integrity.remediation import RemediationPolicy, Remediator
from automation_file.integrity.report import DriftReport, RemediationStep
from automation_file.integrity.snapshot import (
    Snapshot,
    SnapshotEntry,
    build_snapshot,
    quick_matches,
)
from automation_file.integrity.target import Target
from automation_file.integrity.watcher import IntervalRunner, PollingWatcher, WatchHandle
from automation_file.logging_config import file_automation_logger
from automation_file.storage.resolver import StorageResolver
from automation_file.storage.types import FileInfo
from automation_file.storage.uri import URILike, normalize_path

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from automation_file.notify.manager import NotificationManager

_DEFAULT_INTERVAL = 60.0
_DEFAULT_DEBOUNCE = 0.5
_DEFAULT_JOIN_TIMEOUT = 5.0
_Signature = tuple[tuple[str, ...], ...]


def _named(
    value: URILike | None, legacy: URILike | None, name: str, legacy_name: str
) -> URILike | None:
    """Return the argument given under its name or under the first monitor's name for it."""
    if value is not None and legacy is not None:
        raise IntegrityException(f"pass {name}= or its older name {legacy_name}=, not both")
    return value if value is not None else legacy


class MonitorKeywords(TypedDict, total=False):
    """The keyword arguments of :class:`IntegrityMonitor`; each one is optional."""

    algorithm: str
    interval: float
    allow_weak: bool
    max_workers: int | None
    alerts: AlertPolicy | None
    remediation: RemediationPolicy | None
    bus: EventBus | None
    resolver: StorageResolver | None
    on_drift: OnDrift | None
    manager: NotificationManager | None
    notify: bool
    alert_on_extra: bool
    root: URILike | None
    manifest_path: URILike | None


@dataclass(frozen=True)
class _Settings:
    """The keyword arguments one monitor was given, with the default of each."""

    algorithm: str = DEFAULT_ALGORITHM
    interval: float = _DEFAULT_INTERVAL
    allow_weak: bool = False
    max_workers: int | None = None
    alerts: AlertPolicy | None = None
    remediation: RemediationPolicy | None = None
    bus: EventBus | None = None
    resolver: StorageResolver | None = None
    on_drift: OnDrift | None = None
    manager: NotificationManager | None = None
    notify: bool = True
    alert_on_extra: bool = False
    root: URILike | None = None
    manifest_path: URILike | None = None


def _settings(keywords: Mapping[str, Any]) -> _Settings:
    """Return the settings ``keywords`` describe, refusing a name the monitor does not take."""
    unknown = sorted(set(keywords) - {field.name for field in fields(_Settings)})
    if unknown:
        raise TypeError(f"IntegrityMonitor() got an unexpected keyword argument {unknown[0]!r}")
    return _Settings(**keywords)


@dataclass(frozen=True)
class _Pass:
    """One comparison: the part of the baseline examined, what was found, and the whole tree."""

    before: Snapshot
    after: Snapshot
    tree: Snapshot
    deep: bool
    partial: bool
    hashed: int

    def notes(self) -> tuple[str, ...]:
        if self.partial:
            return (
                f"partial pass: only the paths that changed were examined ({len(self.after)} "
                f"current and {len(self.before)} baseline files), not the whole tree",
            )
        if not self.deep:
            return (
                f"quick pass: {self.hashed} of {len(self.after)} files hashed; size, "
                "modification time and etag decided the rest",
            )
        return ()


class IntegrityMonitor:
    """Compares the tree at ``target`` with the baseline stored at ``baseline``.

    Both are storage URIs (or local paths), so either may live in any backend.
    Everything else is a keyword argument (:class:`MonitorKeywords`):

    ``algorithm``
        Used for :meth:`snapshot` and :meth:`create_baseline`; a verification
        hashes with the algorithm of the baseline it reads. ``allow_weak=True``
        admits ``md5`` and ``sha1``.
    ``interval``, ``max_workers``
        Seconds between two passes of continuous mode, and the size of the
        thread pool that hashes.
    ``alerts``, ``bus``
        The :class:`AlertPolicy` and the event bus drift is published on (the
        process-wide one by default).
    ``remediation``
        A :class:`RemediationPolicy`; without one the monitor only reads.
    ``resolver``
        The :class:`StorageResolver` both URIs are resolved with.
    ``on_drift``, ``manager``, ``alert_on_extra``, ``notify``
        The hooks of the first monitor, which work as they did: the callback and
        the notification receive the summary :meth:`check_once` returns, and the
        notification goes through ``manager``, or through the process-wide
        ``notification_manager`` when none is passed. ``notify=False`` sends no
        notification, for when the published event is routed to the sinks instead.
    ``root``, ``manifest_path``
        The first monitor's names for ``target`` and ``baseline``.
    """

    def __init__(
        self,
        target: URILike | None = None,
        baseline: URILike | None = None,
        **keywords: Unpack[MonitorKeywords],
    ) -> None:
        chosen = _settings(keywords)
        self._runner = IntervalRunner(
            self._continuous_tick, chosen.interval, name="fa-integrity-monitor"
        )
        location = _named(target, chosen.root, "target", "root")
        if location is None:
            raise IntegrityException("an IntegrityMonitor needs a target: a storage URI or a path")
        self._target = Target(location, resolver=chosen.resolver)
        self._allow_weak = bool(chosen.allow_weak)
        self._max_workers = chosen.max_workers
        self._algorithm = self._engine(chosen.algorithm).algorithm
        self._baselines = self._baseline_manager(
            _named(baseline, chosen.manifest_path, "baseline", "manifest_path"), chosen.resolver
        )
        self._alerts = AlertEngine(chosen.bus, chosen.alerts)
        self._remediator = (
            None if chosen.remediation is None else Remediator(chosen.remediation, self._target)
        )
        self._legacy = LegacyHooks(
            f"integrity drift: {self._target.uri}",
            on_drift=chosen.on_drift,
            manager=chosen.manager,
            alert_on_extra=chosen.alert_on_extra,
            notify=chosen.notify,
        )
        self._lock = threading.RLock()
        self._last_report: DriftReport | None = None
        self._last_summary: dict[str, Any] | None = None
        self._last_run: datetime | None = None
        self._last_error: str | None = None
        self._announced: _Signature | None = None

    # ------------------------------------------------------------------ what it watches

    @property
    def target(self) -> str:
        """The storage URI of the monitored tree."""
        return str(self._target.uri)

    @property
    def baseline(self) -> str | None:
        """The storage URI of the baseline, or ``None`` when the monitor has none."""
        return None if self._baselines is None else str(self._baselines.uri)

    @property
    def algorithm(self) -> str:
        return self._algorithm

    @property
    def interval(self) -> float:
        return self._runner.interval

    @property
    def is_running(self) -> bool:
        """Whether continuous mode is active."""
        return self._runner.is_running

    @property
    def last_report(self) -> DriftReport | None:
        return self._last_report

    @property
    def last_summary(self) -> dict[str, Any] | None:
        return self._last_summary

    @property
    def last_run(self) -> datetime | None:
        return self._last_run

    @property
    def last_error(self) -> str | None:
        """Why the latest pass could not run, or ``None`` when it did."""
        return self._last_error

    def has_baseline(self) -> bool:
        """Return whether a baseline is configured and stored."""
        return self._baselines is not None and self._baselines.exists()

    def status(self) -> dict[str, Any]:
        """Return a JSON-friendly view: running or not, the last run and the last report."""
        report, last_run = self._last_report, self._last_run
        return {
            "target": self.target,
            "baseline": self.baseline,
            "algorithm": self._algorithm,
            "interval": self.interval,
            "running": self.is_running,
            "last_run": last_run.isoformat() if last_run else None,
            "last_error": self._last_error,
            "last_report": report.to_dict() if report else None,
        }

    # ------------------------------------------------------------------ snapshot and baseline

    def snapshot(self) -> Snapshot:
        """Return the tree as it is now. Nothing is stored."""
        return self._snapshot_with(self._engine(self._algorithm))

    def create_baseline(self) -> Snapshot:
        """Take a snapshot with the monitor's algorithm and store it as the baseline."""
        baselines = self._require_baselines()
        with self._lock:
            snapshot = self.snapshot()
            baselines.save(snapshot)
            self._announced = None
        return snapshot

    def accept(self, report: DriftReport | None = None) -> Snapshot:
        """Approve the current state as the new baseline and return it.

        With ``report``, exactly the tree that verification saw is stored, so a
        change made since is not approved unseen. Without one, or when the
        verification remediated something, the tree is read again. The
        baseline keeps its algorithm.
        """
        baselines = self._require_baselines()
        with self._lock:
            snapshot = self._approved(report, baselines)
            baselines.save(snapshot)
            self._announced = None
        file_automation_logger.info(
            "integrity: accepted the state of %s as its baseline (%d files)",
            self._target.uri,
            len(snapshot),
        )
        return snapshot

    # ------------------------------------------------------------------ verify

    def verify(self, deep: bool = True) -> DriftReport:
        """Compare the tree with the baseline and return a :class:`DriftReport`.

        ``deep=True`` hashes every file. ``deep=False`` hashes only the files
        whose size, modification time or etag differ from the baseline, and the
        report says it was a quick pass: a change that keeps all three goes
        unnoticed. Drift is published as one ``IntegrityViolation`` event.
        """
        return self._verify(deep=deep, repeat=True)[0]

    def verify_paths(self, paths: Iterable[str]) -> DriftReport:
        """Verify only the files at ``paths`` (relative to the target) and under them.

        This is what watch mode runs for the paths that changed; call it when
        something else tells you what changed. Each path is hashed and compared
        with its baseline entry, a directory stands for everything below it,
        and the report is marked ``partial``: the rest of the tree is not read.
        """
        chosen = frozenset(normalize_path(path) for path in paths)
        return self._verify_paths(chosen, repeat=True)[0]

    def check_once(self) -> dict[str, Any]:
        """Verify once and return the first monitor's summary; a failure is in ``error``."""
        try:
            return self._verify(deep=True, repeat=True)[1]
        except FileAutomationException as error:
            return self._record_failure(error, repeat=True)

    # ------------------------------------------------------------------ watch and continuous

    def watch(
        self, *, debounce: float = _DEFAULT_DEBOUNCE, poll_interval: float | None = None
    ) -> WatchHandle:
        """React to changes as they happen and return a handle with ``stop()``.

        A local target is observed through filesystem events: paths that change
        within ``debounce`` seconds of each other are verified together, and
        only those paths are read. Any other backend is polled with a quick
        pass every ``poll_interval`` seconds (``interval`` by default). Either
        way a drift is reported when it appears, not again while it stays the
        same. Watching does not verify the tree when it starts.
        """
        self._require_baselines()
        root = self._target.local_root()
        handle: WatchHandle
        if root is None:
            period = poll_interval if poll_interval is not None else self.interval
            handle = PollingWatcher(self._poll_tick, period)
        else:
            from automation_file.integrity.local_watcher import LocalWatcher

            handle = LocalWatcher(
                root, self._paths_changed, debounce=debounce, ignore=self._target.is_left_out
            )
        handle.start()
        return handle

    def start(self) -> None:
        """Verify every ``interval`` seconds on a thread; the first pass runs after one interval."""
        if self._runner.is_running:
            return
        self._runner.start()
        file_automation_logger.info(
            "integrity: monitoring %s against %s (interval=%.1fs)",
            self._target.uri,
            self.baseline,
            self.interval,
        )

    def stop(self, timeout: float = _DEFAULT_JOIN_TIMEOUT) -> None:
        """End continuous mode."""
        self._runner.stop(timeout)

    # ------------------------------------------------------------------ internals

    def _engine(self, algorithm: str) -> HashEngine:
        return HashEngine(algorithm, allow_weak=self._allow_weak, max_workers=self._max_workers)

    def _baseline_manager(
        self, baseline: URILike | None, resolver: StorageResolver | None
    ) -> BaselineManager | None:
        if baseline is None:
            return None
        baselines = BaselineManager(baseline, resolver=resolver)
        inside = self._target.relative(baselines.uri)
        if inside == "":
            raise IntegrityException(
                f"the baseline and the target are the same location: {baselines.uri}"
            )
        if inside is not None:
            # A baseline kept inside the tree is not part of what the tree is checked for.
            own = self._target.fold(inside)
            self._target.leave_out(lambda path: is_baseline_path(path, own))
        return baselines

    def _require_baselines(self) -> BaselineManager:
        if self._baselines is None:
            raise IntegrityException(
                f"the monitor of {self._target.uri} has no baseline; pass baseline=<URI>"
            )
        return self._baselines

    def _snapshot_with(self, engine: HashEngine) -> Snapshot:
        return build_snapshot(self._target, engine, self._target.files())

    def _approved(self, report: DriftReport | None, baselines: BaselineManager) -> Snapshot:
        if report is not None:
            if report.target != self.target:
                raise IntegrityException(
                    f"the report describes {report.target}, not this monitor's {self.target}"
                )
            if report.snapshot is not None and not report.remediation:
                return report.snapshot
        algorithm = baselines.load().algorithm if baselines.exists() else self._algorithm
        return self._snapshot_with(self._engine(algorithm))

    def _verify(self, *, deep: bool, repeat: bool) -> tuple[DriftReport, dict[str, Any]]:
        with self._lock, correlation_scope() as correlation_id:
            baseline = self._require_baselines().load()
            engine = self._engine(baseline.algorithm)
            infos = self._target.files()
            known = {} if deep else quick_matches(infos, baseline)
            current = build_snapshot(self._target, engine, infos, known=known)
            done = _Pass(
                before=baseline,
                after=current,
                tree=current,
                deep=deep,
                partial=False,
                hashed=sum(1 for entry in current if entry.path not in known),
            )
            return self._conclude(done, engine, correlation_id, repeat=repeat)

    def _verify_paths(
        self, paths: frozenset[str], *, repeat: bool
    ) -> tuple[DriftReport, dict[str, Any]]:
        """Verify only what lies at ``paths``: the watcher's share of a verification."""
        with self._lock, correlation_scope() as correlation_id:
            baseline = self._require_baselines().load()
            engine = self._engine(baseline.algorithm)
            recorded: dict[str, SnapshotEntry] = {}
            found: dict[str, FileInfo] = {}
            for path in sorted(paths):
                recorded.update((entry.path, entry) for entry in baseline.below(path))
                found.update((info.path, info) for info in self._target.at(path))
            after = build_snapshot(self._target, engine, list(found.values()))
            before = Snapshot(
                root=baseline.root,
                backend=baseline.backend,
                algorithm=baseline.algorithm,
                created_at=baseline.created_at,
                entries=tuple(recorded.values()),
            )
            tree = baseline.merged(
                removed=recorded, added=after.entries, root=after.root, backend=after.backend
            )
            done = _Pass(
                before=before, after=after, tree=tree, deep=True, partial=True, hashed=len(after)
            )
            return self._conclude(done, engine, correlation_id, repeat=repeat)

    def _conclude(
        self, done: _Pass, engine: HashEngine, correlation_id: str, *, repeat: bool
    ) -> tuple[DriftReport, dict[str, Any]]:
        """Turn a comparison into a report, remediate, remember it and raise the alerts."""
        changes = detect_changes(done.before, done.after)
        signature: _Signature = tuple(
            (
                change.kind.value,
                change.path,
                change.previous_path or "",
                change.after.checksum if change.after else "",
            )
            for change in changes
        )
        announce = repeat or signature != self._announced
        steps: list[RemediationStep] = []
        if announce and changes and self._remediator is not None:
            steps = self._remediator.apply(changes, engine)
        report = DriftReport(
            target=self.target,
            baseline=self.baseline,
            backend=done.tree.backend,
            algorithm=done.tree.algorithm,
            deep=done.deep,
            partial=done.partial,
            changes=tuple(changes),
            checked=len(done.after),
            hashed=done.hashed,
            notes=done.notes(),
            remediation=tuple(steps),
            correlation_id=correlation_id,
            snapshot=done.tree,
        )
        summary = summary_of(report, done.before.paths)
        self._last_report, self._last_summary = report, summary
        self._last_run, self._last_error = report.verified_at, None
        self._announced = signature
        if report.ok:
            file_automation_logger.debug("integrity: %s matches its baseline", self._target.uri)
        elif announce:
            file_automation_logger.warning(
                "integrity: drift in %s: %s", self._target.uri, report.counts
            )
            self._publish(report)
            self._legacy.handle(summary)
        return report, summary

    def _publish(self, report: DriftReport) -> None:
        self._alerts.violation(report)
        for step in report.remediation:
            resource = str(self._target.uri.joinpath(step.path))
            self._alerts.remediated(step, resource, report.backend)

    def _backend_name(self) -> str:
        try:
            return self._target.backend_name
        except FileAutomationException:
            return ""

    def _record_failure(self, error: Exception, *, repeat: bool) -> dict[str, Any]:
        """Remember that a pass could not run, and say so on the bus and to the legacy hooks."""
        file_automation_logger.error(
            "integrity: verification of %s failed: %r", self._target.uri, error
        )
        summary = error_summary(error)
        message = f"{type(error).__name__}: {error}"
        signature: _Signature = (("error", message),)
        announce = repeat or signature != self._announced
        self._last_summary, self._last_error = summary, message
        self._last_run = datetime.now(timezone.utc)
        self._announced = signature
        if announce:
            with correlation_scope():
                self._alerts.failure(self.target, self._backend_name(), error)
            self._legacy.handle(summary)
        return summary

    def _guarded(self, work: Callable[[], object], *, repeat: bool) -> None:
        try:
            work()
        except Exception as error:  # pylint: disable=broad-except
            # Boundary: a monitor thread must outlive whatever one pass runs into.
            self._record_failure(error, repeat=repeat)

    def _continuous_tick(self) -> None:
        self._guarded(self.check_once, repeat=True)

    def _poll_tick(self) -> None:
        self._guarded(lambda: self._verify(deep=False, repeat=False), repeat=False)

    def _paths_changed(self, paths: frozenset[str]) -> None:
        self._guarded(lambda: self._verify_paths(paths, repeat=False), repeat=False)
