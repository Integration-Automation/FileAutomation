"""The Settings service: the configuration file, the extras, the environment.

.. code-block:: python

    from automation_file.app import app_services

    settings = app_services().settings
    settings.load("automation_file.toml")      # a summary, secrets masked; nothing changes
    settings.apply("automation_file.toml")     # registers its sinks and routes
    for extra in settings.extras():
        print(extra.name, extra.installed, extra.install_hint)

``load`` shows what a file would do; ``apply`` does it. Both resolve the
``${env:...}`` and ``${file:...}`` references of the file, and neither returns a
resolved secret: the summary is masked before it leaves the service.
"""

from __future__ import annotations

import importlib.metadata
import os
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from automation_file.app.masking import mask_secrets
from automation_file.app.storage_service import is_installed
from automation_file.core.config import AutomationConfig
from automation_file.core.optional import EXTRAS, install_hint
from automation_file.logging_config import default_log_file
from automation_file.notify import (
    NotificationManager,
    NotificationRouter,
    notification_manager,
    notification_router,
)

#: Extra name -> the modules it installs; an extra that needs nothing has none.
EXTRA_MODULES: dict[str, tuple[str, ...]] = {
    "s3": ("boto3",),
    "azure": ("azure.storage.blob",),
    "gdrive": ("googleapiclient", "google_auth_oauthlib", "google_auth_httplib2"),
    "dropbox": ("dropbox",),
    "sftp": ("paramiko",),
    "ftp": (),
    "webdav": (),
    "smb": ("smbclient",),
    "fsspec": ("fsspec",),
    "onedrive": ("msal",),
    "box": ("box_sdk_gen",),
    "parquet": ("pyarrow",),
    "gui": ("PySide6",),
}
_DISTRIBUTIONS = ("automation_file", "automation_file_dev")
_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExtraStatus:
    """Whether one optional extra is installed.

    ``installed`` is ``None`` for an extra this table does not know the modules
    of. ``install_hint`` is the ``pip install`` command, set when it is missing.
    """

    name: str
    feature: str
    installed: bool | None
    modules: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    install_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the status."""
        described = asdict(self)
        described["modules"] = list(self.modules)
        described["missing"] = list(self.missing)
        return described


def _extra_status(name: str, feature: str) -> ExtraStatus:
    modules = EXTRA_MODULES.get(name)
    if modules is None:
        return ExtraStatus(name=name, feature=feature, installed=None)
    missing = tuple(module for module in modules if not is_installed(module))
    return ExtraStatus(
        name=name,
        feature=feature,
        installed=not missing,
        modules=modules,
        missing=missing,
        install_hint=install_hint(name) if missing else None,
    )


def _package_version() -> str:
    for distribution in _DISTRIBUTIONS:
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return _UNKNOWN


def _sink_tables(config: AutomationConfig) -> list[dict[str, Any]]:
    entries = config.section("notify").get("sinks") or []
    tables = (
        [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    )
    return [
        {"name": str(entry.get("name") or entry.get("type") or ""), "type": entry.get("type")}
        for entry in tables
    ]


class SettingsService:
    """Load and apply ``automation_file.toml``; report the extras and the environment."""

    def __init__(
        self,
        manager: NotificationManager | None = None,
        router: NotificationRouter | None = None,
    ) -> None:
        self._manager = notification_manager if manager is None else manager
        self._router = notification_router if router is None else router
        self._applied: dict[str, Any] | None = None

    def extras(self) -> list[ExtraStatus]:
        """Return the status of every optional extra, in the order the package lists them."""
        return [_extra_status(name, feature) for name, feature in EXTRAS.items()]

    def environment(self) -> dict[str, Any]:
        """Return the versions and locations a user needs when reporting a problem."""
        return {
            "version": _package_version(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "log_file": str(default_log_file()),
            "applied_config": None if self._applied is None else self._applied["source"],
        }

    def load(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        """Read a configuration file and return its summary. Nothing is registered.

        The summary names the file, its sections, the sinks and the routes it
        declares, and holds the document with every secret masked. A file that
        is missing, malformed or names an unknown sink raises ``ConfigException``.
        """
        return self._summary(AutomationConfig.load(Path(path)), applied=False)

    def apply(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        """Read a configuration file and register its sinks and its routes.

        Sinks already registered stay; one with the same name is replaced. The
        routes the file declared before and no longer does are removed. Returns
        the summary of :meth:`load` with ``applied`` set and the number of
        sinks registered.
        """
        config = AutomationConfig.load(Path(path))
        registered = config.apply_to(self._manager, self._router)
        summary = self._summary(config, applied=True)
        summary["registered_sinks"] = registered
        self._applied = summary
        return summary

    def applied(self) -> dict[str, Any] | None:
        """Return the summary of the configuration applied last, or ``None``."""
        return None if self._applied is None else dict(self._applied)

    def _summary(self, config: AutomationConfig, *, applied: bool) -> dict[str, Any]:
        document = config.raw
        routes = config.notification_routes(known_sinks=self._manager.names())
        return {
            "source": None if config.source is None else str(config.source),
            "applied": applied,
            "sections": sorted(document),
            "sinks": _sink_tables(config),
            "routes": [route.to_dict() for route in routes],
            "defaults": mask_secrets(config.section("defaults")),
            "document": mask_secrets(document),
        }
