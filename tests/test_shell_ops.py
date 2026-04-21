from __future__ import annotations

import sys

import pytest

from automation_file import ShellException, build_default_registry, run_shell


def test_run_shell_echoes_stdout() -> None:
    result = run_shell([sys.executable, "-c", "print('hi')"])
    assert result["returncode"] == 0
    assert "hi" in str(result["stdout"])


def test_run_shell_rejects_string_argv() -> None:
    with pytest.raises(ShellException):
        run_shell("echo hi")  # type: ignore[arg-type]


def test_run_shell_rejects_empty_argv() -> None:
    with pytest.raises(ShellException):
        run_shell([])


def test_run_shell_rejects_non_string_items() -> None:
    with pytest.raises(ShellException):
        run_shell([sys.executable, 42])  # type: ignore[list-item]


def test_run_shell_raises_on_nonzero_exit_when_check() -> None:
    with pytest.raises(ShellException):
        run_shell([sys.executable, "-c", "raise SystemExit(3)"])


def test_run_shell_returns_nonzero_when_check_false() -> None:
    result = run_shell(
        [sys.executable, "-c", "raise SystemExit(3)"],
        check=False,
    )
    assert result["returncode"] == 3


def test_run_shell_times_out() -> None:
    with pytest.raises(ShellException):
        run_shell(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=0.5,
        )


def test_run_shell_missing_executable_raises() -> None:
    with pytest.raises(ShellException):
        run_shell(["this-binary-definitely-does-not-exist-12345"])


def test_run_shell_is_registered() -> None:
    registry = build_default_registry()
    assert "FA_run_shell" in registry


def test_run_shell_captures_stderr() -> None:
    result = run_shell(
        [sys.executable, "-c", "import sys; sys.stderr.write('oops')"],
    )
    assert "oops" in str(result["stderr"])


def test_run_shell_no_capture_returns_empty_strings() -> None:
    result = run_shell(
        [sys.executable, "-c", "print('x')"],
        capture_output=False,
    )
    assert result["stdout"] == ""
    assert result["stderr"] == ""


def test_run_shell_rejects_zero_timeout() -> None:
    with pytest.raises(ShellException):
        run_shell([sys.executable, "-c", "pass"], timeout=0)
