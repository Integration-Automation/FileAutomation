"""Smoke test: the public facade exposes every advertised name."""
from __future__ import annotations

import automation_file


def test_public_api_names_exist() -> None:
    for name in automation_file.__all__:
        assert hasattr(automation_file, name), f"missing re-export: {name}"


def test_shared_registry_is_shared_across_singletons() -> None:
    assert automation_file.callback_executor.registry is automation_file.executor.registry
    assert automation_file.package_manager.registry is automation_file.executor.registry


def test_add_command_flows_through_to_callback() -> None:
    automation_file.add_command_to_executor({"_test_shared": lambda: "ok"})
    assert "_test_shared" in automation_file.callback_executor.registry
    automation_file.executor.registry.unregister("_test_shared")
