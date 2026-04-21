"""Watchdog-backed trigger manager.

A :class:`FileWatcher` owns one ``watchdog.observers.Observer`` plus the
action list to run when a matching filesystem event fires. The module-level
:data:`trigger_manager` keeps a name -> watcher mapping so the JSON facade
(``FA_watch_start`` / ``FA_watch_stop`` / ``FA_watch_list``) and the GUI share
the same lifecycle.

Events are dispatched through the shared :class:`ActionExecutor`, so the
same JSON action-list shape is used everywhere. Dispatch always happens on
watchdog's dispatcher thread — the executor's per-action ``try/except``
prevents a bad action from killing the observer.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

_SUPPORTED_EVENTS = frozenset({"created", "modified", "deleted", "moved"})


class TriggerException(FileAutomationException):
    """Raised by the trigger manager on duplicate / missing / invalid watchers."""


def _parse_events(events: Iterable[str] | str | None) -> frozenset[str]:
    if events is None:
        return frozenset({"created", "modified"})
    if isinstance(events, str):
        events = [events]
    chosen = {item.strip().lower() for item in events if item and item.strip()}
    unknown = chosen - _SUPPORTED_EVENTS
    if unknown:
        raise TriggerException(f"unsupported event types: {sorted(unknown)}")
    return frozenset(chosen or {"created", "modified"})


class _DispatchingHandler(FileSystemEventHandler):
    """Route watchdog events into an action list on the shared executor."""

    def __init__(
        self,
        name: str,
        events: frozenset[str],
        action_list: list[list[Any]],
    ) -> None:
        super().__init__()
        self._name = name
        self._events = events
        self._action_list = action_list

    def on_any_event(self, event: FileSystemEvent) -> None:
        kind = event.event_type
        if kind not in self._events:
            return
        file_automation_logger.info("trigger[%s]: %s %s", self._name, kind, event.src_path)
        from automation_file.core.action_executor import executor

        try:
            executor.execute_action(self._action_list)
        except FileAutomationException as error:
            file_automation_logger.warning(
                "trigger[%s]: action dispatch failed: %r", self._name, error
            )


class FileWatcher:
    """One named watchdog observer tied to an action list."""

    def __init__(
        self,
        name: str,
        path: str,
        action_list: list[list[Any]],
        *,
        events: Iterable[str] | str | None = None,
        recursive: bool = True,
    ) -> None:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            raise TriggerException(f"watch path does not exist: {resolved}")
        self.name = name
        self.path = resolved
        self.recursive = bool(recursive)
        self.events = _parse_events(events)
        self.action_list: list[list[Any]] = list(action_list)
        self._observer: BaseObserver | None = None

    @property
    def is_running(self) -> bool:
        observer = self._observer
        return observer is not None and observer.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        handler = _DispatchingHandler(self.name, self.events, self.action_list)
        observer = Observer()
        observer.schedule(handler, str(self.path), recursive=self.recursive)
        observer.daemon = True
        observer.start()
        self._observer = observer
        file_automation_logger.info(
            "trigger[%s]: watching %s (events=%s, recursive=%s)",
            self.name,
            self.path,
            sorted(self.events),
            self.recursive,
        )

    def stop(self, timeout: float = 5.0) -> None:
        observer = self._observer
        if observer is None:
            return
        self._observer = None
        observer.stop()
        observer.join(timeout=timeout)
        file_automation_logger.info("trigger[%s]: stopped", self.name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "events": sorted(self.events),
            "recursive": self.recursive,
            "running": self.is_running,
            "actions": len(self.action_list),
        }


class TriggerManager:
    """Process-wide registry of :class:`FileWatcher` instances."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._watchers: dict[str, FileWatcher] = {}

    def start(
        self,
        name: str,
        path: str,
        action_list: list[list[Any]],
        *,
        events: Iterable[str] | str | None = None,
        recursive: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if name in self._watchers:
                raise TriggerException(f"watcher already registered: {name}")
            watcher = FileWatcher(
                name=name,
                path=path,
                action_list=action_list,
                events=events,
                recursive=recursive,
            )
            watcher.start()
            self._watchers[name] = watcher
            return watcher.as_dict()

    def stop(self, name: str) -> dict[str, Any]:
        with self._lock:
            watcher = self._watchers.pop(name, None)
        if watcher is None:
            raise TriggerException(f"no such watcher: {name}")
        watcher.stop()
        return watcher.as_dict()

    def stop_all(self) -> list[dict[str, Any]]:
        with self._lock:
            watchers = list(self._watchers.values())
            self._watchers.clear()
        snapshots: list[dict[str, Any]] = []
        for watcher in watchers:
            watcher.stop()
            snapshots.append(watcher.as_dict())
        return snapshots

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [watcher.as_dict() for watcher in self._watchers.values()]

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._watchers


trigger_manager: TriggerManager = TriggerManager()


def watch_start(
    name: str,
    path: str,
    action_list: list[list[Any]],
    events: Iterable[str] | str | None = None,
    recursive: bool = True,
) -> dict[str, Any]:
    """Start a named watcher on ``path`` that dispatches ``action_list``."""
    return trigger_manager.start(name, path, action_list, events=events, recursive=recursive)


def watch_stop(name: str) -> dict[str, Any]:
    """Stop and remove the named watcher."""
    return trigger_manager.stop(name)


def watch_stop_all() -> list[dict[str, Any]]:
    """Stop and remove every active watcher."""
    return trigger_manager.stop_all()


def watch_list() -> list[dict[str, Any]]:
    """Return a snapshot of every registered watcher."""
    return trigger_manager.list()


def register_trigger_ops(registry: ActionRegistry) -> None:
    """Wire ``FA_watch_*`` actions into a registry."""
    registry.register_many(
        {
            "FA_watch_start": watch_start,
            "FA_watch_stop": watch_stop,
            "FA_watch_stop_all": watch_stop_all,
            "FA_watch_list": watch_list,
        }
    )
