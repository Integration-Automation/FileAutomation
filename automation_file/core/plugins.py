"""Entry-point plugin discovery.

Third-party packages can register additional actions with
``automation_file`` without the library having to import them directly.

A plugin advertises itself in its ``pyproject.toml``::

    [project.entry-points."automation_file.actions"]
    my_plugin = "my_plugin:register"

where ``register`` is a zero-argument callable returning a
``Mapping[str, Callable]`` — the same shape you would pass to
:func:`automation_file.add_command_to_executor`.

:func:`load_entry_point_plugins` is invoked by
:func:`automation_file.core.action_registry.build_default_registry` so
installed plugins populate every freshly-built registry automatically.
Plugin failures are logged and swallowed — one broken plugin must not
break the library for everyone else.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from automation_file.logging_config import file_automation_logger

__all__ = ["ENTRY_POINT_GROUP", "load_entry_point_plugins"]

ENTRY_POINT_GROUP = "automation_file.actions"


def load_entry_point_plugins(
    register: Callable[[Mapping[str, Callable[..., Any]]], None],
) -> int:
    """Discover and register every ``automation_file.actions`` entry point.

    ``register`` receives one ``{name: callable}`` mapping per plugin and
    is responsible for storing it (typically
    :meth:`ActionRegistry.register_many`). Returns the number of plugins
    that registered successfully.
    """
    loaded = 0
    for entry in _iter_entry_points():
        try:
            factory = entry.load()
        except Exception as err:  # pylint: disable=broad-except
            file_automation_logger.error(
                "plugin load failed: %s (%s): %r", entry.name, entry.value, err
            )
            continue
        try:
            mapping = factory()
        except Exception as err:  # pylint: disable=broad-except
            file_automation_logger.error(
                "plugin factory raised: %s (%s): %r", entry.name, entry.value, err
            )
            continue
        if not isinstance(mapping, Mapping):
            file_automation_logger.error(
                "plugin %s returned %s, expected Mapping",
                entry.name,
                type(mapping).__name__,
            )
            continue
        try:
            register(mapping)
        except Exception as err:  # pylint: disable=broad-except
            file_automation_logger.error("plugin register failed: %s: %r", entry.name, err)
            continue
        file_automation_logger.info(
            "plugin registered: %s -> %d commands", entry.name, len(mapping)
        )
        loaded += 1
    return loaded


def _iter_entry_points() -> list[EntryPoint]:
    try:
        return list(entry_points(group=ENTRY_POINT_GROUP))
    except TypeError:
        # importlib.metadata before 3.10 used a different API; the project
        # targets 3.10+, so this branch exists only as defensive padding.
        return list(entry_points().get(ENTRY_POINT_GROUP, []))
