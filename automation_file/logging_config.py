"""Module-level logger for automation_file.

A single :data:`file_automation_logger` is exposed. It mirrors INFO+ to stderr
and writes DEBUG+ to ``~/.automation_file/logs/FileAutomation.log`` unless
``FILE_AUTOMATION_LOG_FILE`` names another path (a relative one resolves against
the cwd at import time; ``os.devnull`` turns the file off). The handler list is
rebuilt only once, even if the module is reloaded, so tests can import this safely.

The file used to be ``FileAutomation.log`` in the working directory, opened at
import, so every process that imported the package (PyBreeze, TestPioneer, test
runs) left one wherever it started. It is now opened on the first record, so
importing writes nothing; every process on the account appends to it with its
process id on each line, and it is rotated only when a process opens it, since
Windows cannot rename a file another process holds open.
"""

from __future__ import annotations

import logging
import os
import sys
import warnings
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(process)d | %(name)s | %(levelname)s | %(message)s"
_LOGGER_NAME = "automation_file"

#: Environment variable that overrides where the log file is written.
LOG_FILE_ENV = "FILE_AUTOMATION_LOG_FILE"

#: A file past this size is moved to ``<name>.1`` when a process opens it.
ROTATE_AT_BYTES = 10 * 1024 * 1024


def default_log_file() -> Path:
    """Return the log file path: ``$FILE_AUTOMATION_LOG_FILE``, else the home-directory default."""
    configured = os.environ.get(LOG_FILE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".automation_file" / "logs" / "FileAutomation.log"


def _rotate_if_large(path: Path, limit: int) -> None:
    """Move ``path`` to ``<path>.1`` past ``limit`` bytes; best effort while it is held."""
    try:
        if limit <= 0 or not path.is_file() or path.stat().st_size <= limit:
            return
        os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        return


class FileAutomationFileHandler(RotatingFileHandler):
    """Append-mode UTF-8 file handler.

    A file that cannot be opened becomes ``os.devnull`` with one warning.
    """

    def __init__(self, filename: str, delay: bool = True) -> None:
        super().__init__(
            filename=filename, mode="a", encoding="utf-8", errors="backslashreplace", delay=delay
        )

    def _open(self):
        path = Path(self.baseFilename)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_large(path, ROTATE_AT_BYTES)
            return super()._open()
        except OSError as error:
            warnings.warn(
                f"FileAutomation log file {path} unavailable, file logging off: {error!r}",
                RuntimeWarning,
                stacklevel=2,
            )
            # The handler owns this stream and closes it in close().
            return open(os.devnull, self.mode, encoding=self.encoding, errors=self.errors)  # pylint: disable=consider-using-with


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

    file_handler = FileAutomationFileHandler(str(default_log_file()))
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    stream_handler = _StderrHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)
    logger.addHandler(stream_handler)

    logger._file_automation_initialised = True  # type: ignore[attr-defined]  # pylint: disable=protected-access  # stamp our own init marker on the shared logger
    return logger


file_automation_logger: logging.Logger = _build_logger()
