"""The exception of the application layer."""

from __future__ import annotations

from automation_file.exceptions import FileAutomationException


class AppException(FileAutomationException):
    """Raised when the application layer cannot carry out what a user interface asked for.

    The domain packages keep their own exceptions (``StorageException``,
    ``PipelineException`` ...); this one covers what only the application layer
    checks: an edit a draft refuses, a form value that cannot be read, a request
    for something that is not there.
    """
