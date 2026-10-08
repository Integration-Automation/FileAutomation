"""File integrity monitoring (FIM): the legacy import path.

The monitor lives in :mod:`automation_file.integrity`. This module keeps
``from automation_file.core.fim import IntegrityMonitor`` working: the legacy
call ``IntegrityMonitor(root, manifest_path, interval=..., on_drift=...,
manager=..., alert_on_extra=...)`` runs on the new class, reads a manifest
written by :func:`automation_file.core.manifest.write_manifest`, and
``check_once()`` returns the same summary dictionary.

The notification still goes through the ``manager`` passed to the constructor,
or through the process-wide ``notification_manager`` when none is. One thing was
added: drift is also published as an ``IntegrityViolation`` event.
"""

from __future__ import annotations

from automation_file.integrity.legacy import OnDrift
from automation_file.integrity.monitor import IntegrityMonitor

__all__ = ["IntegrityMonitor", "OnDrift"]
