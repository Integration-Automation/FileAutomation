"""TOML-based configuration for automation_file.

Callers describe notification sinks, secret-provider roots, and scheduler
defaults in a single ``automation_file.toml`` file. :class:`AutomationConfig`
loads it, resolves ``${env:…}`` / ``${file:…}`` references via the secret
provider chain, and exposes helpers to materialise runtime objects (sinks,
etc.) without the caller poking at the raw dict.

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

    [defaults]
    dedup_seconds = 120

Only the sections the caller uses need to appear; everything is optional.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10 runners
    import tomli as tomllib

from automation_file.core.secrets import (
    ChainedSecretProvider,
    default_provider,
    resolve_secret_refs,
)
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.notify.manager import NotificationManager
from automation_file.notify.sinks import (
    EmailSink,
    NotificationException,
    NotificationSink,
    SlackSink,
    WebhookSink,
)


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
        notify_section = self.section("notify")
        entries = notify_section.get("sinks") or []
        if not isinstance(entries, list):
            raise ConfigException("'notify.sinks' must be an array of tables")
        sinks: list[NotificationSink] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ConfigException("each 'notify.sinks' entry must be a table")
            sinks.append(_build_sink(entry))
        return sinks

    def apply_to(self, manager: NotificationManager) -> int:
        """Register every configured sink into ``manager``. Returns the count.

        Existing registrations are preserved; duplicates by name are replaced
        (see :meth:`NotificationManager.register`).
        """
        count = 0
        for sink in self.notification_sinks():
            manager.register(sink)
            count += 1
        defaults = self.section("defaults")
        if "dedup_seconds" in defaults:
            try:
                manager.dedup_seconds = float(defaults["dedup_seconds"])
            except (TypeError, ValueError) as err:
                raise ConfigException(
                    f"defaults.dedup_seconds must be a number, got {defaults['dedup_seconds']!r}"
                ) from err
        return count


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
    except NotificationException:
        raise
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
