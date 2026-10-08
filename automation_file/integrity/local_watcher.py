"""Watcher for a local directory: filesystem events, debounced into batches of paths.

Imported only when a local target is watched, so the rest of the integrity
package does not load watchdog.

An observer reports what the operating system tells it, and an overflowing
event queue drops events without saying so. Watching narrows the time to
detection; a periodic full verification is still what proves the tree.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.watcher import Debouncer, WatchHandle
from automation_file.logging_config import file_automation_logger

_CHANGE_EVENTS = frozenset({"created", "modified", "deleted", "moved"})
_DIRECTORY_NOISE = "modified"
_DEFAULT_JOIN_TIMEOUT = 5.0


class PathCollector(FileSystemEventHandler):
    """Turns watchdog events into paths relative to the watched directory.

    Only ``created``, ``modified``, ``deleted`` and ``moved`` count; a move
    reports both of its paths. A path outside ``root`` is ignored.
    """

    def __init__(self, root: Path, report: Callable[[str], None]) -> None:
        super().__init__()
        self._root = root
        self._report = report

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type not in _CHANGE_EVENTS:
            return
        # A directory is "modified" whenever an entry in it changes; that entry reports itself.
        if event.is_directory and event.event_type == _DIRECTORY_NOISE:
            return
        # Before watchdog 5 only a move carries a destination.
        for raw in (event.src_path, getattr(event, "dest_path", "")):
            relative = self._relative(raw)
            if relative is not None:
                self._report(relative)

    def _relative(self, raw: bytes | str) -> str | None:
        if not raw:
            return None
        try:
            relative = Path(os.fsdecode(raw)).relative_to(self._root).as_posix()
        except ValueError:
            return None
        return "" if relative == "." else relative


class LocalWatcher(WatchHandle):
    """Watches ``root`` recursively and calls ``on_paths`` with each batch of changed paths."""

    kind = "events"

    def __init__(
        self,
        root: Path,
        on_paths: Callable[[frozenset[str]], object],
        *,
        debounce: float = 0.5,
        ignore: Callable[[str], bool] | None = None,
    ) -> None:
        if not root.is_dir():
            raise IntegrityException(f"cannot watch {root}: it is not a directory")
        self._root = root
        self._ignore = ignore
        self._debouncer = Debouncer(on_paths, debounce)
        self._observer: BaseObserver | None = None

    @property
    def is_running(self) -> bool:
        observer = self._observer
        return observer is not None and observer.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._debouncer.start()
        observer = Observer()
        observer.schedule(PathCollector(self._root, self.feed), str(self._root), recursive=True)
        observer.daemon = True
        observer.start()
        self._observer = observer
        file_automation_logger.info("integrity: watching %s for changes", self._root)

    def feed(self, path: str) -> None:
        """Report that ``path``, relative to the root, changed. The observer calls this."""
        if self._ignore is not None and self._ignore(path):
            return
        self._debouncer.add(path)

    def stop(self, timeout: float = _DEFAULT_JOIN_TIMEOUT) -> None:
        observer, self._observer = self._observer, None
        if observer is not None:
            observer.stop()
            observer.join(timeout=timeout)
        self._debouncer.stop(timeout)
        file_automation_logger.info("integrity: stopped watching %s", self._root)
