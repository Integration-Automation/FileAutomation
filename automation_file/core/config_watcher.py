"""Polling hot-reload for ``automation_file.toml``.

``ConfigWatcher`` runs a small background thread that checks the config file's
mtime + size every ``interval`` seconds. When either changes it reloads via
:meth:`AutomationConfig.load` and fires the user-supplied ``on_change``
callback with the fresh config. Errors during reload are logged but do not
terminate the watcher — the next successful reload picks up where we left
off.

We use polling rather than watchdog here: it's one file, cross-platform, and
the reload cadence is inherently human-scale (seconds, not milliseconds).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from automation_file.core.config import AutomationConfig, ConfigException
from automation_file.core.secrets import ChainedSecretProvider
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

OnChange = Callable[[AutomationConfig], None]


class ConfigWatcher:
    """Polls ``path`` and invokes ``on_change`` whenever the file changes."""

    def __init__(
        self,
        path: str | Path,
        on_change: OnChange,
        *,
        interval: float = 2.0,
        provider: ChainedSecretProvider | None = None,
    ) -> None:
        if interval <= 0:
            raise ConfigException("interval must be positive")
        self._path = Path(path)
        self._on_change = on_change
        self._interval = interval
        self._provider = provider
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_fingerprint: tuple[float, int] | None = None

    def start(self) -> AutomationConfig:
        """Load the config once, arm the watcher, and return the initial load."""
        config = AutomationConfig.load(self._path, provider=self._provider)
        self._last_fingerprint = self._fingerprint()
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="fa-config-watcher", daemon=True)
        thread.start()
        self._thread = thread
        file_automation_logger.info(
            "config_watcher: watching %s (interval=%.2fs)", self._path, self._interval
        )
        return config

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def check_once(self) -> bool:
        """Reload if the file changed since the last call. Returns True on reload."""
        fingerprint = self._fingerprint()
        if fingerprint == self._last_fingerprint:
            return False
        self._last_fingerprint = fingerprint
        try:
            config = AutomationConfig.load(self._path, provider=self._provider)
        except FileAutomationException as err:
            file_automation_logger.error("config_watcher: reload failed: %r", err)
            return False
        try:
            self._on_change(config)
        except FileAutomationException as err:
            file_automation_logger.error("config_watcher: on_change raised: %r", err)
        return True

    def _fingerprint(self) -> tuple[float, int]:
        try:
            stat = self._path.stat()
        except OSError:
            return (0.0, 0)
        return (stat.st_mtime, stat.st_size)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.check_once()
            self._stop.wait(self._interval)
