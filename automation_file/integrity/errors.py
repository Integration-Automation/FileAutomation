"""Errors of the integrity subsystem."""

from __future__ import annotations

from automation_file.exceptions import FileAutomationException


class IntegrityException(FileAutomationException):
    """Raised when a snapshot, a baseline or a verification cannot be produced or trusted."""
