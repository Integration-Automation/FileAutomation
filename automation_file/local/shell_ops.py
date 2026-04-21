"""Safe subprocess execution (Strategy module for the executor).

``run_shell`` is a deliberately narrow wrapper around :mod:`subprocess`:

* ``argv`` must be a non-empty list of strings — never a single string.
  This eliminates shell-injection through concatenated user input.
* ``timeout`` is mandatory (default 60 s) so runaway processes cannot hang
  the executor.
* ``shell=True`` is never used.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

_DEFAULT_TIMEOUT_SECONDS = 60.0


class ShellException(FileAutomationException):
    """Raised when a shell command fails (non-zero exit, timeout, or bad argv)."""


def run_shell(
    argv: Sequence[str],
    *,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> dict[str, object]:
    """Run ``argv`` as a subprocess with a hard timeout.

    ``argv`` must be a non-empty list / tuple of strings. Strings are
    rejected to block shell-injection via concatenated user input.

    Returns ``{"returncode": int, "stdout": str, "stderr": str}`` when
    ``capture_output=True``; ``stdout``/``stderr`` are empty strings
    otherwise.

    Raises :class:`ShellException` when ``check=True`` and the process
    returns a non-zero exit code or times out.
    """
    if isinstance(argv, str) or not isinstance(argv, Sequence):
        raise ShellException("argv must be a list of strings, not a single string")
    argv_list = list(argv)
    if not argv_list or not all(isinstance(part, str) for part in argv_list):
        raise ShellException("argv must be a non-empty list of strings")
    if timeout <= 0:
        raise ShellException("timeout must be positive")

    cwd_path = str(Path(cwd)) if cwd else None
    env_dict = dict(env) if env is not None else None

    try:
        completed = subprocess.run(
            argv_list,
            timeout=timeout,
            cwd=cwd_path,
            env=env_dict,
            capture_output=capture_output,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as err:
        file_automation_logger.error("run_shell: timeout after %.1fs: %s", timeout, argv_list[0])
        raise ShellException(f"timeout after {timeout:.1f}s: {argv_list[0]}") from err
    except FileNotFoundError as err:
        raise ShellException(f"executable not found: {argv_list[0]}") from err
    except OSError as err:
        raise ShellException(f"subprocess failed: {err!r}") from err

    result: dict[str, object] = {
        "returncode": completed.returncode,
        "stdout": completed.stdout or "" if capture_output else "",
        "stderr": completed.stderr or "" if capture_output else "",
    }
    if check and completed.returncode != 0:
        file_automation_logger.error("run_shell: exit %d: %s", completed.returncode, argv_list[0])
        raise ShellException(f"exit {completed.returncode}: {argv_list[0]}")
    file_automation_logger.info("run_shell: %s -> exit %d", argv_list[0], completed.returncode)
    return result
