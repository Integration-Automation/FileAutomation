"""Tests for automation_file.core.package_loader."""

from __future__ import annotations

from je_action_core import PackageGate

from automation_file.core.action_registry import ActionRegistry
from automation_file.core.package_loader import PackageLoader


def test_load_missing_package_returns_none() -> None:
    loader = PackageLoader(ActionRegistry())
    assert loader.load("not_a_real_package_xyz_123") is None


def test_load_caches_module() -> None:
    loader = PackageLoader(ActionRegistry())
    first = loader.load("json")
    second = loader.load("json")
    assert first is second


def test_add_package_registers_members() -> None:
    registry = ActionRegistry()
    loader = PackageLoader(registry)
    count = loader.add_package_to_executor("json")
    assert count > 0
    assert "json_loads" in registry
    assert "json_dumps" in registry


def test_add_missing_package_returns_zero() -> None:
    registry = ActionRegistry()
    loader = PackageLoader(registry)
    assert loader.add_package_to_executor("not_a_real_package_xyz_123") == 0


def test_no_action_command_loads_packages() -> None:
    """The loader is Python-only, so the package gate stays off (workspace X-12).

    A command that loads packages would let an action list import ``os`` or ``subprocess``;
    adding one means switching the gate on in ``core/package_loader.py`` first.
    """
    from automation_file import executor, package_manager

    assert not [name for name in executor.registry if "package" in name.lower()]
    assert package_manager.settings.gate is PackageGate.OFF
