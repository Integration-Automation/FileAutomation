"""PySide6 GUI for automation_file.

The main window is organised by workflow: Dashboard, Files, Storage, Pipelines,
Scheduler, Integrity, Audit, Notifications and Settings, each a page over one
service of :mod:`automation_file.app`. An Advanced entry keeps the tools that
address a single action or backend: local file ops, the per-backend transfer
panels, transfer progress, JSON action lists, file triggers and the TCP / HTTP
action servers.

The entry point is :func:`launch_ui` (also mirrored as the ``ui`` subcommand
of ``python -m automation_file``).
"""

from __future__ import annotations

from automation_file.ui.launcher import launch_ui

__all__ = ["launch_ui"]
