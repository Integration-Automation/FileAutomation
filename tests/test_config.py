"""Tests for automation_file.core.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.core.config import AutomationConfig, ConfigException
from automation_file.notify.manager import NotificationManager
from automation_file.notify.sinks import EmailSink, SlackSink, WebhookSink


def _write_toml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigException, match="not found"):
        AutomationConfig.load(tmp_path / "missing.toml")


def test_load_rejects_malformed_toml(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    _write_toml(path, "this is = not [[valid\n")
    with pytest.raises(ConfigException, match="cannot parse"):
        AutomationConfig.load(path)


def test_load_resolves_env_references(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_HOOK", "https://example.com/alerts")
    path = tmp_path / "c.toml"
    _write_toml(
        path,
        """
        [[notify.sinks]]
        type = "webhook"
        name = "team"
        url = "${env:MY_HOOK}"
        """,
    )
    config = AutomationConfig.load(path)
    sinks = config.notification_sinks()
    assert len(sinks) == 1
    assert isinstance(sinks[0], WebhookSink)
    assert sinks[0].name == "team"
    assert sinks[0].url == "https://example.com/alerts"


def test_load_builds_slack_and_email(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_URL", "https://hooks.slack.com/services/T/B/X")
    monkeypatch.setenv("SMTP_PW", "pw")
    path = tmp_path / "c.toml"
    _write_toml(
        path,
        """
        [[notify.sinks]]
        type = "slack"
        webhook_url = "${env:SLACK_URL}"

        [[notify.sinks]]
        type = "email"
        name = "ops"
        host = "smtp.example.com"
        port = 587
        sender = "bot@example.com"
        recipients = ["ops@example.com"]
        password = "${env:SMTP_PW}"
        """,
    )
    config = AutomationConfig.load(path)
    sinks = config.notification_sinks()
    assert len(sinks) == 2
    assert isinstance(sinks[0], SlackSink)
    email_sink = sinks[1]
    assert isinstance(email_sink, EmailSink)
    assert email_sink.host == "smtp.example.com"
    assert email_sink.recipients == ["ops@example.com"]


def test_apply_to_registers_and_sets_dedup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_URL", "https://hooks.slack.com/services/T/B/X")
    path = tmp_path / "c.toml"
    _write_toml(
        path,
        """
        [defaults]
        dedup_seconds = 120.5

        [[notify.sinks]]
        type = "slack"
        name = "team"
        webhook_url = "${env:SLACK_URL}"
        """,
    )
    config = AutomationConfig.load(path)
    manager = NotificationManager(dedup_seconds=0.0)
    count = config.apply_to(manager)
    assert count == 1
    assert manager.dedup_seconds == pytest.approx(120.5)
    descriptions = manager.list()
    assert descriptions[0]["name"] == "team"


def test_rejects_unknown_sink_type(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    _write_toml(
        path,
        """
        [[notify.sinks]]
        type = "pigeon"
        name = "carrier"
        """,
    )
    config = AutomationConfig.load(path)
    with pytest.raises(ConfigException, match="unknown sink type"):
        config.notification_sinks()


def test_rejects_sink_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    _write_toml(
        path,
        """
        [[notify.sinks]]
        type = "webhook"
        name = "missing-url"
        """,
    )
    config = AutomationConfig.load(path)
    with pytest.raises((ConfigException, KeyError)):
        config.notification_sinks()


def test_rejects_bad_dedup_value(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    _write_toml(
        path,
        """
        [defaults]
        dedup_seconds = "not-a-number"
        """,
    )
    config = AutomationConfig.load(path)
    manager = NotificationManager(dedup_seconds=0.0)
    with pytest.raises(ConfigException, match="dedup_seconds"):
        config.apply_to(manager)


def test_empty_config_yields_no_sinks(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    _write_toml(path, "# nothing configured\n")
    config = AutomationConfig.load(path)
    assert not config.notification_sinks()


def test_file_secret_provider_resolved_from_config(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "hook").write_text("https://example.com/alerts\n", encoding="utf-8")
    path = tmp_path / "c.toml"
    _write_toml(
        path,
        f"""
        [secrets]
        file_root = "{secrets_dir.as_posix()}"

        [[notify.sinks]]
        type = "webhook"
        name = "ops"
        url = "${{file:hook}}"
        """,
    )
    config = AutomationConfig.load(path)
    sinks = config.notification_sinks()
    assert sinks[0].url == "https://example.com/alerts"
