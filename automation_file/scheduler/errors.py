"""The scheduler's exception."""

from __future__ import annotations

from automation_file.exceptions import FileAutomationException


class SchedulerException(FileAutomationException):
    """Raised for duplicate / missing / invalid scheduled jobs."""
