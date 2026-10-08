"""IntegrityMonitor 2.0: file integrity monitoring over any storage backend.

* :class:`IntegrityMonitor` ties the parts together: ``snapshot()``,
  ``create_baseline()``, ``verify()``, ``accept()``, ``watch()`` and
  ``start()`` / ``stop()``.
* :class:`Snapshot` / :class:`SnapshotEntry` describe a tree;
  :func:`dump_manifest` / :func:`load_manifest` are its versioned JSON form, and
  :class:`BaselineManager` keeps the approved one at a storage URI.
* :class:`HashEngine` hashes files in parallel and refuses weak digests.
* :func:`detect_changes` compares two snapshots into :class:`Change` records,
  and a :class:`DriftReport` is the outcome of one verification.
* :class:`AlertEngine` publishes drift as events; :class:`RemediationPolicy`
  turns on quarantine and restore, which are off by default.
* :func:`register_integrity_ops` adds the ``FA_integrity_*`` actions to a registry.
"""

from __future__ import annotations

from automation_file.integrity.actions import register_integrity_ops
from automation_file.integrity.alerts import (
    DEFAULT_SEVERITIES,
    AlertEngine,
    AlertPolicy,
    IntegrityRemediated,
)
from automation_file.integrity.baseline import BaselineManager
from automation_file.integrity.detector import Change, ChangeKind, detect_changes
from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.hashing import (
    DEFAULT_ALGORITHM,
    STRONG_ALGORITHMS,
    WEAK_ALGORITHMS,
    HashEngine,
)
from automation_file.integrity.manifest import (
    MANIFEST_SCHEMA_VERSION,
    dump_manifest,
    from_manifest,
    load_manifest,
    to_manifest,
)
from automation_file.integrity.monitor import IntegrityMonitor, MonitorKeywords
from automation_file.integrity.remediation import RemediationPolicy, Remediator
from automation_file.integrity.report import DriftReport, RemediationStep
from automation_file.integrity.snapshot import Snapshot, SnapshotEntry, build_snapshot
from automation_file.integrity.target import Target
from automation_file.integrity.watcher import WatchHandle

__all__ = [
    "DEFAULT_ALGORITHM",
    "DEFAULT_SEVERITIES",
    "MANIFEST_SCHEMA_VERSION",
    "STRONG_ALGORITHMS",
    "WEAK_ALGORITHMS",
    "AlertEngine",
    "AlertPolicy",
    "BaselineManager",
    "Change",
    "ChangeKind",
    "DriftReport",
    "HashEngine",
    "IntegrityException",
    "IntegrityMonitor",
    "IntegrityRemediated",
    "MonitorKeywords",
    "RemediationPolicy",
    "RemediationStep",
    "Remediator",
    "Snapshot",
    "SnapshotEntry",
    "Target",
    "WatchHandle",
    "build_snapshot",
    "detect_changes",
    "dump_manifest",
    "from_manifest",
    "load_manifest",
    "register_integrity_ops",
    "to_manifest",
]
