"""Standalone entry point for quickly launching the GUI during development.

Usage::

    python main_ui.py

Equivalent to ``python -m automation_file ui``; kept at the repo root so the
window can be started without remembering the subcommand.
"""

from __future__ import annotations

import sys

from automation_file.ui.launcher import launch_ui

if __name__ == "__main__":
    sys.exit(launch_ui())
