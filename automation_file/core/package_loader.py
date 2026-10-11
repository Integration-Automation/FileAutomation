"""Dynamic plugin registration into an :class:`ActionRegistry`.

``PackageLoader`` imports an external package by name and registers every
top-level function / class / builtin under the key ``"<package>_<member>"``
(je_action_core's package manager with FileAutomation's settings).
"""

from __future__ import annotations

from types import ModuleType

from je_action_core import PackageGate, PackageManager, PackageManagerSettings

from automation_file.core.action_registry import ActionRegistry
from automation_file.logging_config import file_automation_logger

_SETTINGS = PackageManagerSettings(
    import_errors=(ImportError,),
    # No FA_* command reaches the loader (Python-only, see CLAUDE.md, Plugin / package loading),
    # so je_action_core's package gate would only warn the host itself. tests/test_package_loader.py
    # fails if a command that loads packages is added; switch the gate on then (workspace X-12).
    gate=PackageGate.OFF,
    log_error=file_automation_logger.error,
)


class PackageLoader(PackageManager):
    """Load packages lazily and register their public callables."""

    def __init__(self, registry: ActionRegistry) -> None:
        super().__init__(_SETTINGS)
        self.registry: ActionRegistry = registry
        self.executor = registry

    def load(self, package: str) -> ModuleType | None:
        """Import ``package`` once and return the module (cached)."""
        return self.check_package(package)

    def add_package_to_executor(self, package: str) -> int:  # type: ignore[override]
        """Register every function / class / builtin from ``package``.

        Returns the number of commands that were registered.
        """
        count = self.check_and_add(package, self.registry)
        file_automation_logger.info("PackageLoader: registered %d members from %s", count, package)
        return count
