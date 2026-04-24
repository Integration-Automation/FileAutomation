"""Tests for opt-in variable substitution."""

from __future__ import annotations

import os
import re
import uuid

import pytest

from automation_file import SubstitutionException, execute_action, substitute
from automation_file.core.action_executor import executor


def test_substitute_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FA_SUB_TEST", "hello")
    assert substitute("${env:FA_SUB_TEST}/suffix") == "hello/suffix"


def test_substitute_env_missing_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FA_SUB_ABSENT", raising=False)
    assert substitute("X${env:FA_SUB_ABSENT}Y") == "XY"


def test_substitute_date_with_format() -> None:
    result = substitute("${date:%Y}")
    assert isinstance(result, str)
    assert re.fullmatch(r"\d{4}", result)


def test_substitute_uuid_is_hex32() -> None:
    result = substitute("${uuid}")
    assert isinstance(result, str)
    uuid.UUID(hex=result)


def test_substitute_cwd() -> None:
    assert substitute("${cwd}") == os.getcwd()


def test_substitute_nested_structures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FA_NESTED", "nested-value")
    payload = [
        ["FA_create_file", {"file_path": "${env:FA_NESTED}"}],
        ["other", ["${cwd}", "static"]],
    ]
    result = substitute(payload)
    assert result[0][1]["file_path"] == "nested-value"
    assert result[1][1][0] == os.getcwd()
    assert result[1][1][1] == "static"


def test_unknown_substitution_raises() -> None:
    with pytest.raises(SubstitutionException):
        substitute("${unknown:foo}")


def test_env_without_arg_raises() -> None:
    with pytest.raises(SubstitutionException):
        substitute("${env:}")


def test_execute_action_substitutes_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FA_EXEC_SUB", "echoed")
    if "test_sub_echo" not in executor.registry:
        executor.registry.register("test_sub_echo", lambda value: value)
    results = execute_action([["test_sub_echo", {"value": "${env:FA_EXEC_SUB}"}]], substitute=True)
    assert "echoed" in next(iter(results.values()))


def test_execute_action_leaves_strings_untouched_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FA_EXEC_SUB", "echoed")
    if "test_sub_echo" not in executor.registry:
        executor.registry.register("test_sub_echo", lambda value: value)
    results = execute_action([["test_sub_echo", {"value": "${env:FA_EXEC_SUB}"}]])
    assert "${env:FA_EXEC_SUB}" in next(iter(results.values()))
