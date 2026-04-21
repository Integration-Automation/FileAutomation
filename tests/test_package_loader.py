"""Tests for automation_file.core.package_loader."""
from __future__ import annotations

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
