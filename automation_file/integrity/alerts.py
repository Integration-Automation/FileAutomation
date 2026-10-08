"""Alert Engine: drift becomes events on the bus.

The integrity subsystem never calls a notification sink or the audit log. It
publishes, and whoever cares subscribes:

* one :class:`~automation_file.events.IntegrityViolation` per verification that
  found drift, or that could not run at all;
* one :class:`IntegrityRemediated` per remediation step.

Every event has ``source="integrity"`` and, in its payload, ``resource`` (the
target URI) and ``backend``. The severity of a violation is the worst severity
among the kinds of change it found; :class:`AlertPolicy` sets the severity of
each kind.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from automation_file.events.bus import EventBus, event_bus
from automation_file.events.model import Event, IntegrityViolation, Severity
from automation_file.integrity.detector import Change, ChangeKind
from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.report import DriftReport, RemediationStep

SOURCE = "integrity"
STATUS_DRIFT = "drift"
STATUS_ERROR = "error"
STATUS_OK = "ok"
STATUS_FAILED = "failed"
_ACTION_VERIFY = "verify"
_DEFAULT_MAX_CHANGES = 20

#: Additions and metadata are worth a look; anything that alters or removes what the
#: baseline holds is an error.
DEFAULT_SEVERITIES: Mapping[ChangeKind, Severity] = {
    ChangeKind.CREATED: Severity.WARNING,
    ChangeKind.METADATA_CHANGED: Severity.WARNING,
    ChangeKind.MODIFIED: Severity.ERROR,
    ChangeKind.DELETED: Severity.ERROR,
    ChangeKind.RENAMED: Severity.ERROR,
    ChangeKind.PERMISSION_CHANGED: Severity.ERROR,
}


@dataclass(frozen=True, kw_only=True)
class IntegrityRemediated(Event):
    """A remediation step ran: a file was quarantined or restored, or the attempt failed."""

    type: ClassVar[str] = "integrity.remediated"


@dataclass(frozen=True)
class AlertPolicy:
    """How loud each kind of change is, and how many changes an event lists.

    ``severities`` overrides :data:`DEFAULT_SEVERITIES` kind by kind; keys and
    values may be the enum members or their names (``{"created": "error"}``).
    """

    severities: Mapping[Any, Any] = field(default_factory=dict, hash=False)
    max_changes: int = _DEFAULT_MAX_CHANGES

    def __post_init__(self) -> None:
        if self.max_changes < 0:
            raise IntegrityException("max_changes must not be negative")
        table = dict(DEFAULT_SEVERITIES)
        try:
            table.update(
                (ChangeKind(kind), Severity(severity)) for kind, severity in self.severities.items()
            )
        except ValueError as error:
            raise IntegrityException(f"invalid alert severity setting: {error}") from error
        object.__setattr__(self, "severities", table)

    def severity_of(self, kind: ChangeKind) -> Severity:
        """Return the severity of one kind of change."""
        return Severity(self.severities[kind])

    def severity_for(self, changes: Iterable[Change]) -> Severity:
        """Return the worst severity among ``changes`` (``info`` when there are none)."""
        worst = Severity.INFO
        for change in changes:
            severity = self.severity_of(change.kind)
            if severity.rank > worst.rank:
                worst = severity
        return worst


def _described(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{count} {kind}" for kind, count in counts.items() if count)


def _payload(
    action: str, resource: str, backend: str, status: str, **details: Any
) -> dict[str, Any]:
    """Return a payload that opens with the four keys every integrity event carries."""
    return {
        "action": action,
        "resource": resource,
        "backend": backend,
        "status": status,
        **details,
    }


class AlertEngine:
    """Publishes what a monitor finds on one :class:`~automation_file.events.EventBus`."""

    def __init__(self, bus: EventBus | None = None, policy: AlertPolicy | None = None) -> None:
        self._bus = bus if bus is not None else event_bus
        self._policy = policy if policy is not None else AlertPolicy()

    def violation(self, report: DriftReport) -> IntegrityViolation | None:
        """Publish the drift ``report`` found; a clean report publishes nothing."""
        if report.ok:
            return None
        limit = self._policy.max_changes
        payload = _payload(
            _ACTION_VERIFY,
            report.target,
            report.backend,
            STATUS_DRIFT,
            baseline=report.baseline,
            algorithm=report.algorithm,
            deep=report.deep,
            partial=report.partial,
            counts=report.counts,
            total=len(report.changes),
            changes=[change.brief() for change in report.changes[:limit]],
            truncated=len(report.changes) > limit,
        )
        if report.remediation:
            succeeded = sum(1 for step in report.remediation if step.ok)
            payload["remediation"] = {
                STATUS_OK: succeeded,
                STATUS_FAILED: len(report.remediation) - succeeded,
            }
        event = IntegrityViolation(
            source=SOURCE,
            subject=f"integrity drift: {report.target} ({_described(report.counts)})",
            severity=self._policy.severity_for(report.changes),
            payload=payload,
        )
        self._bus.publish(event)
        return event

    def failure(self, resource: str, backend: str, error: BaseException) -> IntegrityViolation:
        """Publish that ``resource`` could not be verified at all."""
        event = IntegrityViolation(
            source=SOURCE,
            subject=f"integrity verification failed: {resource}",
            severity=Severity.ERROR,
            payload=_payload(
                _ACTION_VERIFY,
                resource,
                backend,
                STATUS_ERROR,
                error=f"{type(error).__name__}: {error}",
            ),
        )
        self._bus.publish(event)
        return event

    def remediated(self, step: RemediationStep, resource: str, backend: str) -> IntegrityRemediated:
        """Publish one remediation step; ``resource`` is the URI of the file it concerned."""
        outcome = "done" if step.ok else "failed"
        event = IntegrityRemediated(
            source=SOURCE,
            subject=f"integrity {step.action} {outcome}: {resource}",
            severity=Severity.INFO if step.ok else Severity.ERROR,
            payload=_payload(
                step.action,
                resource,
                backend,
                STATUS_OK if step.ok else STATUS_FAILED,
                path=step.path,
                kind=step.kind,
                source=step.source,
                destination=step.destination,
                error=step.error,
            ),
        )
        self._bus.publish(event)
        return event
