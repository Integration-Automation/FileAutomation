"""Exceptions raised by the pipeline runtime."""

from __future__ import annotations

from collections.abc import Iterable

from automation_file.exceptions import FileAutomationException


class PipelineException(FileAutomationException):
    """Raised when a pipeline cannot be run, resumed, or written to its store."""


class PipelineDefinitionException(PipelineException):
    """Raised when a pipeline definition is invalid.

    ``problems`` holds every finding, each one starting with the path of the
    offending entry (``tasks.verify.depends_on[0]: unknown task 'x'``).
    """

    def __init__(self, problems: Iterable[str] | str) -> None:
        self.problems: tuple[str, ...] = (
            (problems,) if isinstance(problems, str) else tuple(problems)
        )
        super().__init__("; ".join(self.problems))
