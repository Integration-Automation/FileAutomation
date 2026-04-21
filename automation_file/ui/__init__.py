"""PySide6 GUI for automation_file.

Exposes every registered ``FA_*`` action through a tabbed main window so users
can drive local file ops, HTTP downloads, Google Drive, S3, Azure Blob,
Dropbox, SFTP, JSON action lists, and the TCP / HTTP action servers without
writing any code.

The entry point is :func:`launch_ui` (also mirrored as the ``ui`` subcommand
of ``python -m automation_file``).
"""

from __future__ import annotations

from automation_file.ui.launcher import launch_ui

__all__ = ["launch_ui"]
