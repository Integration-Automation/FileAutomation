"""Tests for automation_file.core.plugins (entry-point discovery)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import patch

from automation_file.core.plugins import ENTRY_POINT_GROUP, load_entry_point_plugins


class _FakeEntryPoint:
    def __init__(self, name: str, factory: Callable[[], Any]) -> None:
        self.name = name
        self.value = f"fake:{name}"
        self._factory = factory

    def load(self) -> Callable[[], Any]:
        return self._factory


def _patch_entry_points(points: list[_FakeEntryPoint]) -> Any:
    def fake_entry_points(*, group: str) -> list[_FakeEntryPoint]:
        assert group == ENTRY_POINT_GROUP
        return points

    return patch("automation_file.core.plugins.entry_points", fake_entry_points)


def test_plugin_registers_its_commands() -> None:
    def my_action() -> str:
        return "ok"

    def factory() -> dict[str, Callable[..., Any]]:
        return {"my_action": my_action}

    registered: dict[str, Callable[..., Any]] = {}
    with _patch_entry_points([_FakeEntryPoint("demo", factory)]):
        count = load_entry_point_plugins(registered.update)

    assert count == 1
    assert registered["my_action"] is my_action


def test_plugin_load_failure_is_swallowed() -> None:
    ep = _FakeEntryPoint("broken", lambda: {})

    def bad_load() -> Any:
        raise ImportError("no module foo")

    ep.load = bad_load  # type: ignore[method-assign]

    with _patch_entry_points([ep]):
        count = load_entry_point_plugins(lambda _mapping: None)

    assert count == 0


def test_plugin_factory_raising_is_swallowed() -> None:
    def factory() -> dict[str, Callable[..., Any]]:
        raise RuntimeError("boom")

    with _patch_entry_points([_FakeEntryPoint("demo", factory)]):
        count = load_entry_point_plugins(lambda _mapping: None)

    assert count == 0


def test_plugin_returning_non_mapping_rejected() -> None:
    def factory() -> list[str]:
        return ["not", "a", "mapping"]

    with _patch_entry_points([_FakeEntryPoint("demo", factory)]):
        count = load_entry_point_plugins(lambda _mapping: None)

    assert count == 0


def test_one_broken_plugin_does_not_block_others() -> None:
    def good() -> str:
        return "good"

    def bad_factory() -> Any:
        raise RuntimeError("nope")

    def good_factory() -> dict[str, Callable[..., Any]]:
        return {"good_action": good}

    registered: dict[str, Callable[..., Any]] = {}
    with _patch_entry_points(
        [
            _FakeEntryPoint("bad", bad_factory),
            _FakeEntryPoint("good", good_factory),
        ]
    ):
        count = load_entry_point_plugins(registered.update)

    assert count == 1
    assert "good_action" in registered


def test_plugin_register_error_is_swallowed() -> None:
    def factory() -> dict[str, Callable[..., Any]]:
        return {"x": lambda: None}

    def register(_mapping: Mapping[str, Callable[..., Any]]) -> None:
        raise ValueError("registry rejects me")

    with _patch_entry_points([_FakeEntryPoint("demo", factory)]):
        count = load_entry_point_plugins(register)

    assert count == 0


def test_plugins_loaded_by_build_default_registry() -> None:
    from automation_file.core.action_registry import build_default_registry

    def plugin_cmd() -> str:
        return "plugged"

    def factory() -> dict[str, Callable[..., Any]]:
        return {"FA_plugin_demo": plugin_cmd}

    with _patch_entry_points([_FakeEntryPoint("demo", factory)]):
        registry = build_default_registry()

    assert "FA_plugin_demo" in registry
    assert registry.resolve("FA_plugin_demo") is plugin_cmd
