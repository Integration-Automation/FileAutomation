"""Dynamic plugin registration into an :class:`ActionRegistry`.

``PackageLoader`` imports an external package by name and registers every
top-level function / class / builtin under the key ``"<package>_<member>"``.
"""

from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec
from inspect import getmembers, isbuiltin, isclass, isfunction
from types import ModuleType

from automation_file.core.action_registry import ActionRegistry
from automation_file.logging_config import file_automation_logger


class PackageLoader:
    """Load packages lazily and register their public callables."""

    def __init__(self, registry: ActionRegistry) -> None:
        self.registry: ActionRegistry = registry
        self._cache: dict[str, ModuleType] = {}

    def load(self, package: str) -> ModuleType | None:
        """Import ``package`` once and return the module (cached)."""
        cached = self._cache.get(package)
        if cached is not None:
            return cached
        spec = find_spec(package)
        if spec is None:
            file_automation_logger.error("PackageLoader: cannot find %s", package)
            return None
        try:
            module = import_module(spec.name)
        except (ImportError, ModuleNotFoundError) as error:
            file_automation_logger.error("PackageLoader import error: %r", error)
            return None
        self._cache[package] = module
        return module

    def add_package_to_executor(self, package: str) -> int:
        """Register every function / class / builtin from ``package``.

        Returns the number of commands that were registered.
        """
        module = self.load(package)
        if module is None:
            return 0
        count = 0
        for predicate in (isfunction, isbuiltin, isclass):
            for member_name, member in getmembers(module, predicate):
                self.registry.register(f"{package}_{member_name}", member)
                count += 1
        file_automation_logger.info("PackageLoader: registered %d members from %s", count, package)
        return count
