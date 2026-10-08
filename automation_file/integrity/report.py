"""DriftReport: the outcome of one verification.

A report holds the changes, how many there are of each kind, how thorough the
pass was (``deep``, ``partial``, ``hashed`` of ``checked`` files, and ``notes``
that say so in words) and what remediation did. ``to_dict`` is JSON-friendly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from automation_file.integrity.detector import Change, ChangeKind
from automation_file.integrity.hashing import DEFAULT_ALGORITHM
from automation_file.integrity.snapshot import Snapshot


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RemediationStep:
    """One thing remediation did, or tried to do, about a change."""

    action: str
    path: str
    kind: str
    ok: bool
    source: str = ""
    destination: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "path": self.path,
            "kind": self.kind,
            "ok": self.ok,
            "source": self.source,
            "destination": self.destination,
            "error": self.error,
        }


@dataclass(frozen=True)
class DriftReport:
    """What one verification of ``target`` against ``baseline`` found.

    ``deep`` is false for a quick pass, which hashed only the files whose size,
    modification time or etag differ from the baseline. ``partial`` is true
    when only the paths a watcher saw change were examined. ``snapshot`` is the
    tree as this pass saw it; :meth:`IntegrityMonitor.accept` stores it.
    """

    target: str
    baseline: str | None = None
    backend: str = ""
    algorithm: str = DEFAULT_ALGORITHM
    deep: bool = True
    partial: bool = False
    changes: tuple[Change, ...] = ()
    checked: int = 0
    hashed: int = 0
    notes: tuple[str, ...] = ()
    remediation: tuple[RemediationStep, ...] = ()
    verified_at: datetime = field(default_factory=_now)
    correlation_id: str = ""
    snapshot: Snapshot | None = field(default=None, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        """True when nothing differs from the baseline."""
        return not self.changes

    @property
    def counts(self) -> dict[str, int]:
        """The number of changes of every kind, kinds without a change included."""
        totals = {kind.value: 0 for kind in ChangeKind}
        for change in self.changes:
            totals[change.kind.value] += 1
        return totals

    def paths(self, kind: ChangeKind | str) -> list[str]:
        """Return the paths of the changes of one kind."""
        wanted = ChangeKind(kind)
        return [change.path for change in self.changes if change.kind is wanted]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the report, without the snapshot."""
        return {
            "target": self.target,
            "baseline": self.baseline,
            "backend": self.backend,
            "algorithm": self.algorithm,
            "ok": self.ok,
            "deep": self.deep,
            "partial": self.partial,
            "checked": self.checked,
            "hashed": self.hashed,
            "counts": self.counts,
            "changes": [change.to_dict() for change in self.changes],
            "notes": list(self.notes),
            "remediation": [step.to_dict() for step in self.remediation],
            "verified_at": self.verified_at.isoformat(),
            "correlation_id": self.correlation_id,
        }
