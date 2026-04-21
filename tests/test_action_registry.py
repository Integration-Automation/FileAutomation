"""Tests for automation_file.core.action_registry."""
from __future__ import annotations

import pytest

from automation_file.core.action_registry import ActionRegistry, build_default_registry
from automation_file.exceptions import AddCommandException


def test_register_and_resolve() -> None:
    registry = ActionRegistry()
    registry.register("echo", lambda x: x)
    assert "echo" in registry
    assert registry.resolve("echo")("hi") == "hi"


def test_register_rejects_non_callable() -> None:
    registry = ActionRegistry()
    with pytest.raises(AddCommandException):
        registry.register("bad", 42)  # type: ignore[arg-type]


def test_register_many_and_update() -> None:
    registry = ActionRegistry()
    registry.register_many({"a": lambda: 1, "b": lambda: 2})
    registry.update({"c": lambda: 3})
    assert set(registry) == {"a", "b", "c"}
    assert len(registry) == 3


def test_unregister() -> None:
    registry = ActionRegistry({"x": lambda: 1})
    registry.unregister("x")
    assert "x" not in registry
    registry.unregister("missing")  # no error


def test_default_registry_has_builtin_commands() -> None:
    registry = build_default_registry()
    for expected in (
        "FA_copy_file",
        "FA_create_dir",
        "FA_zip_file",
        "FA_download_file",
        "FA_drive_search_all_file",
    ):
        assert expected in registry


def test_event_dict_is_a_live_view() -> None:
    registry = ActionRegistry()
    registry.register("k", lambda: 1)
    assert "k" in registry.event_dict
