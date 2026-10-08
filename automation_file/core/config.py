"""TOML-based configuration for automation_file.

Callers describe notification sinks and routes, secret-provider roots, and
scheduler defaults in a single ``automation_file.toml`` file.
:class:`AutomationConfig` loads it, resolves ``${env:…}`` / ``${file:…}``
references via the secret provider chain, and exposes helpers to materialise
runtime objects (sinks, routes, etc.) without the caller poking at the raw
dict.

Minimal example::

    [secrets]
    file_root = "/run/secrets"

    [[notify.sinks]]
    type = "slack"
    name = "team-alerts"
    webhook_url = "${env:SLACK_WEBHOOK}"

    [[notify.sinks]]
    type = "email"
    name = "ops-email"
    host = "smtp.example.com"
    port = 587
    sender = "alerts@example.com"
    recipients = ["ops@example.com"]
    username = "${env:SMTP_USER}"
    password = "${file:smtp_password}"

    [[notify.routes]]
    name = "pipeline-failures"
    sinks = ["team-alerts", "ops-email"]
    types = ["pipeline.*", "task.failed"]
    min_severity = "error"
    dedup_seconds = 600
    rate_limit = 10
    rate_period = 60

    [defaults]
    dedup_seconds = 120

Only the sections the caller uses need to appear; everything is optional.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from automation_file.core.secrets import (
    ChainedSecretProvider,
    default_provider,
    resolve_secret_refs,
)
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.notify.manager import NotificationManager
from automation_file.notify.router import CONFIG_ORIGIN, NotificationRouter, Route
from automation_file.notify.sinks import (
    EmailSink,
    NotificationException,
    NotificationSink,
    SlackSink,
    WebhookSink,
)


def _load_tomllib() -> Any:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib
    # pragma: no cover - exercised only on Python 3.10 runners
    import tomli  # pylint: disable=import-error  # declared in *.toml for Python<3.11

    return tomli


class ConfigException(FileAutomationException):
    """Raised when the config file is missing, unparseable, or malformed."""


class AutomationConfig:
    """Parsed, secret-resolved view of an ``automation_file.toml`` document."""

    def __init__(self, data: dict[str, Any], *, source: Path | None = None) -> None:
        self._data = data
        self._source = source

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        provider: ChainedSecretProvider | None = None,
    ) -> AutomationConfig:
        """Parse ``path`` as TOML, resolve secret refs, and return the config."""
        config_path = Path(path)
        if not config_path.is_file():
            raise ConfigException(f"config file not found: {config_path}")
        tomllib = _load_tomllib()
        try:
            raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as err:
            raise ConfigException(f"cannot parse {config_path}: {err}") from err
        secrets_section = raw.get("secrets") or {}
        file_root = secrets_section.get("file_root")
        effective_provider = provider or default_provider(file_root)
        resolved = resolve_secret_refs(raw, effective_provider)
        file_automation_logger.info("config loaded from %s", config_path)
        return cls(resolved, source=config_path)

    @property
    def source(self) -> Path | None:
        return self._source

    @property
    def raw(self) -> dict[str, Any]:
        """Return a shallow copy of the resolved document."""
        return dict(self._data)

    def section(self, name: str) -> dict[str, Any]:
        """Return one top-level section as a dict (empty if absent)."""
        value = self._data.get(name)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ConfigException(f"section {name!r} must be a table, got {type(value).__name__}")
        return value

    def notification_sinks(self) -> list[NotificationSink]:
        """Instantiate every sink declared under ``[[notify.sinks]]``."""
        return [_build_sink(entry) for entry in self._notify_tables("sinks")]

    def notification_routes(self, known_sinks: Iterable[str] = ()) -> list[Route]:
        """Build every route declared under ``[[notify.routes]]``.

        A route may only name a sink declared under ``[[notify.sinks]]`` or
        listed in ``known_sinks`` (the sinks registered in code). An unknown
        sink, an unknown severity, an unknown option or a name used twice
        raises :class:`ConfigException`.
        """
        known = set(known_sinks)
        known.update(_sink_name(entry) for entry in self._notify_tables("sinks"))
        routes: dict[str, Route] = {}
        for entry in self._notify_tables("routes"):
            route = _build_route(entry)
            if route.name in routes:
                raise ConfigException(f"route {route.name!r} is declared twice")
            unknown = [sink for sink in route.sinks if sink not in known]
            if unknown:
                raise ConfigException(
                    f"route {route.name!r} names unknown sink(s) {unknown} (known: {sorted(known)})"
                )
            routes[route.name] = route
        return list(routes.values())

    def apply_to(
        self, manager: NotificationManager, router: NotificationRouter | None = None
    ) -> int:
        """Register every configured sink into ``manager``. Returns the count.

        Existing registrations are preserved; duplicates by name are replaced
        (see :meth:`NotificationManager.register`).

        With a ``router``, the ``[[notify.routes]]`` tables become its
        configured routes: the ones this file declared before and no longer
        does are removed, while routes added in code stay. The router is
        started when the file declares a route, and stopped when removing the
        file's routes leaves it with none, because a router without routes
        would deliver nothing. Sinks and routes are both validated before
        anything is registered.
        """
        sinks = self.notification_sinks()
        routes = self.notification_routes(known_sinks=manager.names())
        for sink in sinks:
            manager.register(sink)
        defaults = self.section("defaults")
        if "dedup_seconds" in defaults:
            try:
                manager.dedup_seconds = float(defaults["dedup_seconds"])
            except (TypeError, ValueError) as err:
                raise ConfigException(
                    f"defaults.dedup_seconds must be a number, got {defaults['dedup_seconds']!r}"
                ) from err
        if router is not None:
            _apply_routes(router, routes)
        elif routes:
            file_automation_logger.warning(
                "config: %d notify route(s) declared, but apply_to was given no router",
                len(routes),
            )
        return len(sinks)

    def _notify_tables(self, key: str) -> list[dict[str, Any]]:
        entries = self.section("notify").get(key) or []
        if not isinstance(entries, list):
            raise ConfigException(f"'notify.{key}' must be an array of tables")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ConfigException(f"each 'notify.{key}' entry must be a table")
        return entries


def _apply_routes(router: NotificationRouter, routes: list[Route]) -> None:
    removed = router.sync_routes(routes, origin=CONFIG_ORIGIN)
    if routes:
        router.start()
    elif removed and not router.routes():
        # The file took the last route away: an active router would now deliver nothing.
        router.stop()


def _sink_name(entry: dict[str, Any]) -> str:
    """Return the name a sink entry registers under: its ``name``, else its ``type``."""
    return str(entry.get("name") or entry.get("type") or "")


def _build_route(entry: dict[str, Any]) -> Route:
    try:
        return Route.from_mapping(entry)
    except (NotificationException, TypeError, ValueError) as err:
        raise ConfigException(
            f"invalid config for route {entry.get('name') or '<unnamed>'!r}: {err}"
        ) from err


def _build_sink(entry: dict[str, Any]) -> NotificationSink:
    sink_type = entry.get("type")
    if not isinstance(sink_type, str):
        raise ConfigException("each sink entry needs a 'type' string")
    builder = _SINK_BUILDERS.get(sink_type)
    if builder is None:
        raise ConfigException(
            f"unknown sink type {sink_type!r} (expected one of {sorted(_SINK_BUILDERS)})"
        )
    try:
        return builder(entry)
    except (TypeError, ValueError) as err:
        raise ConfigException(
            f"invalid config for sink {entry.get('name') or sink_type!r}: {err}"
        ) from err


def _build_webhook(entry: dict[str, Any]) -> WebhookSink:
    return WebhookSink(
        url=entry["url"],
        name=entry.get("name", "webhook"),
        timeout=float(entry.get("timeout", 10.0)),
        extra_headers=entry.get("extra_headers"),
    )


def _build_slack(entry: dict[str, Any]) -> SlackSink:
    return SlackSink(
        webhook_url=entry["webhook_url"],
        name=entry.get("name", "slack"),
        timeout=float(entry.get("timeout", 10.0)),
    )


def _build_email(entry: dict[str, Any]) -> EmailSink:
    return EmailSink(
        host=entry["host"],
        port=int(entry["port"]),
        sender=entry["sender"],
        recipients=list(entry["recipients"]),
        username=entry.get("username"),
        password=entry.get("password"),
        use_tls=bool(entry.get("use_tls", True)),
        name=entry.get("name", "email"),
        timeout=float(entry.get("timeout", 10.0)),
    )


_SINK_BUILDERS = {
    "webhook": _build_webhook,
    "slack": _build_slack,
    "email": _build_email,
}
