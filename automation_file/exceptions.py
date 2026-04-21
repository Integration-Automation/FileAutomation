"""Exception hierarchy for automation_file.

All custom exceptions inherit from ``FileAutomationException`` so callers can
filter with a single ``except`` and still distinguish specific failures.
"""
from __future__ import annotations


class FileAutomationException(Exception):
    """Root of the automation_file exception tree."""


class FileNotExistsException(FileAutomationException):
    """Raised when a required source file is missing."""


class DirNotExistsException(FileAutomationException):
    """Raised when a required directory is missing."""


class ZipInputException(FileAutomationException):
    """Raised when a zip helper receives an unsupported input type."""


class CallbackExecutorException(FileAutomationException):
    """Raised by ``CallbackExecutor`` for registration / dispatch failures."""


class ExecuteActionException(FileAutomationException):
    """Raised by ``ActionExecutor`` when an action list cannot be run."""


class AddCommandException(FileAutomationException):
    """Raised when a command registered into the executor is not callable."""


class JsonActionException(FileAutomationException):
    """Raised when JSON action files cannot be read or written."""


class ArgparseException(FileAutomationException):
    """Raised when the CLI receives no actionable argument."""


class UrlValidationException(FileAutomationException):
    """Raised when a URL fails scheme / host validation (SSRF guard)."""


class ValidationException(FileAutomationException):
    """Raised when an action list fails pre-execution validation."""


class RetryExhaustedException(FileAutomationException):
    """Raised when a ``@retry_on_transient`` wrapped call runs out of attempts."""


class QuotaExceededException(FileAutomationException):
    """Raised when an action exceeds a configured size or duration quota."""


class PathTraversalException(FileAutomationException):
    """Raised when a user-supplied path escapes the allowed root."""


class TCPAuthException(FileAutomationException):
    """Raised when a TCP client fails shared-secret authentication."""


_ARGPARSE_EMPTY_MESSAGE = "argparse received no actionable argument"
_BAD_TRIGGER_FUNCTION = "trigger name is not registered in the executor"
_BAD_CALLBACK_METHOD = "callback_param_method must be 'kwargs' or 'args'"
_ADD_COMMAND_NOT_CALLABLE = "command value must be a callable"
_ACTION_LIST_EMPTY = "action list is empty or wrong type"
_ACTION_LIST_MISSING_KEY = "action dict missing 'auto_control' key"
_CANT_FIND_JSON = "can't read JSON file"
_CANT_SAVE_JSON = "can't write JSON file"
