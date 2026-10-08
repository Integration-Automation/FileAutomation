"""Remediation: what a monitor may do about drift. Off unless a policy is passed.

Monitoring is read-only. A :class:`RemediationPolicy` given to the monitor
turns on, per kind of change, one of two actions:

``quarantine``
    Move the offending file out of the tree into
    ``<quarantine>/<UTC timestamp>/<path>``. Nothing there is ever overwritten.
``restore``
    Copy the file back from ``restore_from``, a mirror of the baseline. The
    mirror's copy is hashed first and refused when it does not match the
    baseline; the restored file is hashed again before the step counts as done.
    A modified file is moved to the quarantine first when one is configured;
    without one its content is overwritten.

A rename is treated as its two halves: the old path as deleted, the new one as
created. Every step is returned as a
:class:`~automation_file.integrity.report.RemediationStep`; a step that fails is
reported, never raised.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from automation_file.exceptions import FileAutomationException
from automation_file.integrity.detector import Change, ChangeKind
from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.hashing import HashEngine
from automation_file.integrity.report import RemediationStep
from automation_file.integrity.snapshot import SnapshotEntry
from automation_file.integrity.target import Target
from automation_file.logging_config import file_automation_logger
from automation_file.storage.storage import Storage
from automation_file.storage.uri import StorageURI, URILike, parse_storage_uri

ACTION_NONE = "none"
ACTION_QUARANTINE = "quarantine"
ACTION_RESTORE = "restore"
_ON_CREATED = (ACTION_NONE, ACTION_QUARANTINE)
_ON_MODIFIED = (ACTION_NONE, ACTION_QUARANTINE, ACTION_RESTORE)
_ON_DELETED = (ACTION_NONE, ACTION_RESTORE)
_STAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"


def _checked_action(name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise IntegrityException(f"{name} must be one of {', '.join(allowed)}; got {value!r}")


@dataclass(frozen=True)
class RemediationPolicy:
    """Which changes are acted on, and with which storage."""

    quarantine: URILike | None = None
    restore_from: URILike | None = None
    on_created: str = ACTION_NONE
    on_modified: str = ACTION_NONE
    on_deleted: str = ACTION_NONE

    def __post_init__(self) -> None:
        _checked_action("on_created", self.on_created, _ON_CREATED)
        _checked_action("on_modified", self.on_modified, _ON_MODIFIED)
        _checked_action("on_deleted", self.on_deleted, _ON_DELETED)
        chosen = (self.on_created, self.on_modified, self.on_deleted)
        if ACTION_QUARANTINE in chosen and self.quarantine is None:
            raise IntegrityException("a policy that quarantines needs a quarantine= storage URI")
        if ACTION_RESTORE in chosen and self.restore_from is None:
            raise IntegrityException("a policy that restores needs a restore_from= storage URI")

    @property
    def active(self) -> bool:
        """True when at least one kind of change is acted on."""
        return (self.on_created, self.on_modified, self.on_deleted) != (ACTION_NONE,) * 3

    @property
    def quarantine_uri(self) -> StorageURI | None:
        return None if self.quarantine is None else parse_storage_uri(self.quarantine)

    @property
    def restore_uri(self) -> StorageURI | None:
        return None if self.restore_from is None else parse_storage_uri(self.restore_from)


def _failure(error: FileAutomationException) -> str:
    return f"{type(error).__name__}: {error}"


class Remediator:
    """Carries out a :class:`RemediationPolicy` on one :class:`Target`."""

    def __init__(self, policy: RemediationPolicy, target: Target) -> None:
        if not isinstance(policy, RemediationPolicy):
            raise IntegrityException(
                f"remediation must be a RemediationPolicy, got {type(policy).__name__}"
            )
        self._policy = policy
        self._target = target
        self._quarantine = self._outside_storage(policy.quarantine_uri, "quarantine")
        self._mirror = self._outside_storage(policy.restore_uri, "restore_from")

    def _outside_storage(self, uri: StorageURI | None, name: str) -> Storage | None:
        if uri is None:
            return None
        if self._target.relative(uri) is not None:
            raise IntegrityException(
                f"{name} {uri} lies inside the monitored target {self._target.uri}; "
                "keep it outside the tree it serves"
            )
        return Storage(uri, resolver=self._target.resolver)

    def apply(self, changes: Iterable[Change], engine: HashEngine) -> list[RemediationStep]:
        """Act on ``changes`` as the policy says and return every step taken.

        ``engine`` must hash with the baseline's algorithm: a restore is checked
        against the baseline's checksums.
        """
        if not self._policy.active:
            return []
        stamp = datetime.now(timezone.utc).strftime(_STAMP_FORMAT)
        steps: list[RemediationStep] = []
        for change in changes:
            steps.extend(self._handle(change, stamp, engine))
        for step in steps:
            file_automation_logger.info(
                "integrity: %s of %s %s", step.action, step.path, "done" if step.ok else "failed"
            )
        return steps

    def _handle(self, change: Change, stamp: str, engine: HashEngine) -> list[RemediationStep]:
        if change.kind is ChangeKind.CREATED:
            return self._created(change.path, change.kind, stamp)
        if change.kind is ChangeKind.MODIFIED:
            return self._modified(change, stamp, engine)
        if change.kind is ChangeKind.DELETED:
            return self._deleted(change.path, change.before, change.kind, engine)
        if change.kind is ChangeKind.RENAMED and change.previous_path is not None:
            return [
                *self._deleted(change.previous_path, change.before, change.kind, engine),
                *self._created(change.path, change.kind, stamp),
            ]
        return []

    def _created(self, path: str, kind: ChangeKind, stamp: str) -> list[RemediationStep]:
        if self._policy.on_created != ACTION_QUARANTINE:
            return []
        return [self._quarantined(path, kind, stamp)]

    def _modified(self, change: Change, stamp: str, engine: HashEngine) -> list[RemediationStep]:
        if self._policy.on_modified == ACTION_QUARANTINE:
            return [self._quarantined(change.path, change.kind, stamp)]
        if self._policy.on_modified != ACTION_RESTORE:
            return []
        refusal = self._mirror_refusal(change.path, change.before, engine)
        if refusal is not None:
            return [self._restore_step(change.path, change.kind, refusal)]
        if self._quarantine is None:
            return [self._restored(change.path, change.before, change.kind, engine)]
        set_aside = self._quarantined(change.path, change.kind, stamp)
        if not set_aside.ok:
            reason = "the modified file could not be quarantined, so it was left in place"
            return [set_aside, self._restore_step(change.path, change.kind, reason)]
        return [set_aside, self._restored(change.path, change.before, change.kind, engine)]

    def _deleted(
        self, path: str, expected: SnapshotEntry | None, kind: ChangeKind, engine: HashEngine
    ) -> list[RemediationStep]:
        if self._policy.on_deleted != ACTION_RESTORE:
            return []
        refusal = self._mirror_refusal(path, expected, engine)
        if refusal is not None:
            return [self._restore_step(path, kind, refusal)]
        return [self._restored(path, expected, kind, engine)]

    def _quarantined(self, path: str, kind: ChangeKind, stamp: str) -> RemediationStep:
        """Move ``path`` out of the tree into this pass's quarantine directory."""
        if self._quarantine is None:
            raise IntegrityException("no quarantine storage is configured")
        source = self._target.storage.file(path)
        destination = self._quarantine.file(f"{stamp}/{path}")
        error: str | None = None
        try:
            source.move_to(destination, overwrite=False)
        except FileAutomationException as failure:
            error = _failure(failure)
        return RemediationStep(
            action=ACTION_QUARANTINE,
            path=path,
            kind=kind.value,
            ok=error is None,
            source=str(source),
            destination=str(destination),
            error=error,
        )

    def _mirror_refusal(
        self, path: str, expected: SnapshotEntry | None, engine: HashEngine
    ) -> str | None:
        """Say why the mirror's copy of ``path`` must not be restored, or ``None`` if it may."""
        if self._mirror is None:
            raise IntegrityException("no restore_from storage is configured")
        if expected is None or not expected.checksum:
            return "the baseline records no checksum for it, so a restore could not be verified"
        try:
            digest = engine.hash_file(self._mirror, path)
        except FileAutomationException as failure:
            return f"the mirror could not be read: {_failure(failure)}"
        if digest is None:
            return f"the mirror {self._mirror} has no copy of it"
        if digest != expected.checksum:
            return "the mirror's copy does not match the baseline checksum; nothing was copied"
        return None

    def _restored(
        self, path: str, expected: SnapshotEntry | None, kind: ChangeKind, engine: HashEngine
    ) -> RemediationStep:
        """Copy the verified mirror copy of ``path`` into place and check it again there."""
        if self._mirror is None or expected is None:
            raise IntegrityException("a restore needs a mirror and a baseline entry")
        try:
            self._mirror.file(path).copy_to(self._target.storage.file(path))
            digest = engine.hash_file(self._target.storage, path)
        except FileAutomationException as failure:
            return self._restore_step(path, kind, _failure(failure))
        if digest != expected.checksum:
            reason = "the restored file does not match the baseline checksum"
            return self._restore_step(path, kind, reason)
        return self._restore_step(path, kind, None)

    def _restore_step(self, path: str, kind: ChangeKind, error: str | None) -> RemediationStep:
        return RemediationStep(
            action=ACTION_RESTORE,
            path=path,
            kind=kind.value,
            ok=error is None,
            source=str(self._mirror.file(path)) if self._mirror is not None else "",
            destination=str(self._target.storage.file(path)),
            error=error,
        )
