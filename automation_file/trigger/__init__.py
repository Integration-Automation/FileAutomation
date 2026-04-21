"""Event-driven triggers — watch local paths and run action lists on change.

Each :class:`FileWatcher` wraps one ``watchdog.Observer`` plus the JSON action
list to dispatch when a matching event fires. The module-level
:data:`trigger_manager` owns a registry of named watchers so callers can
start / stop them from JSON actions or the GUI.
"""

from __future__ import annotations

from automation_file.trigger.manager import (
    FileWatcher,
    TriggerManager,
    register_trigger_ops,
    trigger_manager,
    watch_list,
    watch_start,
    watch_stop,
    watch_stop_all,
)

__all__ = [
    "FileWatcher",
    "TriggerManager",
    "register_trigger_ops",
    "trigger_manager",
    "watch_list",
    "watch_start",
    "watch_stop",
    "watch_stop_all",
]
