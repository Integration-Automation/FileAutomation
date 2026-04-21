"""Module-level logger for automation_file.

A single :data:`file_automation_logger` is exposed. It writes to
``FileAutomation.log`` in append mode and mirrors every record to stderr via a
custom handler. The handler list is rebuilt only once, even if the module is
reloaded, so tests can import this safely.
"""

from __future__ import annotations

import logging
import sys

_LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
_LOG_FILENAME = "FileAutomation.log"
_LOGGER_NAME = "automation_file"


class _StderrHandler(logging.Handler):
    """Mirror log records to stderr so scripts see progress without enabling root."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            print(self.format(record), file=sys.stderr)
        except (OSError, ValueError):
            self.handleError(record)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if getattr(logger, "_file_automation_initialised", False):
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = logging.FileHandler(filename=_LOG_FILENAME, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    stream_handler = _StderrHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)
    logger.addHandler(stream_handler)

    logger._file_automation_initialised = True  # type: ignore[attr-defined]
    return logger


file_automation_logger: logging.Logger = _build_logger()
