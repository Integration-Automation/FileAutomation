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


class DagException(FileAutomationException):
    """Raised when a DAG action list has a cycle, unknown dep, or duplicate id."""


class RateLimitExceededException(FileAutomationException):
    """Raised when a rate-limited call cannot acquire a token in the allotted wait."""


class CircuitOpenException(FileAutomationException):
    """Raised when a circuit breaker is open and short-circuits the protected call."""


class LockTimeoutException(FileAutomationException):
    """Raised when a lock acquire waits past its timeout."""


class QueueException(FileAutomationException):
    """Raised by the persistent action queue on storage / dispatch errors."""


class CASException(FileAutomationException):
    """Raised by the content-addressable store on integrity / I/O failures."""


class TemplateException(FileAutomationException):
    """Raised when template rendering fails (missing engine, syntax, I/O)."""


class DiffException(FileAutomationException):
    """Raised when diff computation or patch application fails."""


class VersioningException(FileAutomationException):
    """Raised by the versioning helpers on retention / I/O failures."""


class ArchiveException(FileAutomationException):
    """Raised when an archive format is unsupported or extraction fails."""


class WebDAVException(FileAutomationException):
    """Raised by the WebDAV client on transport / protocol failures."""


class SMBException(FileAutomationException):
    """Raised by the SMB/CIFS client on connection / protocol failures."""


class MCPServerException(FileAutomationException):
    """Raised by the MCP server bridge when a tool invocation fails."""


class FsspecException(FileAutomationException):
    """Raised by the fsspec bridge on missing dependency or backend failures."""


class TextOpsException(FileAutomationException):
    """Raised by text / binary file helpers (split, merge, sed, encoding_convert)."""


class DataOpsException(FileAutomationException):
    """Raised by CSV / JSONL / YAML / Parquet helpers."""


class OneDriveException(FileAutomationException):
    """Raised by the OneDrive (Microsoft Graph) backend."""


class BoxException(FileAutomationException):
    """Raised by the Box backend."""


class TracingException(FileAutomationException):
    """Raised when OpenTelemetry tracing setup cannot be completed."""


_ARGPARSE_EMPTY_MESSAGE = "argparse received no actionable argument"
_BAD_TRIGGER_FUNCTION = "trigger name is not registered in the executor"
_BAD_CALLBACK_METHOD = "callback_param_method must be 'kwargs' or 'args'"
_ADD_COMMAND_NOT_CALLABLE = "command value must be a callable"
_ACTION_LIST_EMPTY = "action list is empty or wrong type"
_ACTION_LIST_MISSING_KEY = "action dict missing 'auto_control' key"
_CANT_FIND_JSON = "can't read JSON file"
_CANT_SAVE_JSON = "can't write JSON file"
