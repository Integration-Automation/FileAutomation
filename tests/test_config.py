"""Tests for automation_file.core.config."""

# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from automation_file.core.config import AutomationConfig, ConfigException
from automation_file.core.config_watcher import ConfigWatcher
from automation_file.events import EventBus, PipelineFailed, Severity, TaskFailed
from automation_file.notify.manager import NotificationManager
from automation_file.notify.router import NotificationRouter, Route
from automation_file.notify.sinks import EmailSink, NotificationSink, SlackSink, WebhookSink


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


# ---------------------------------------------------------------------- notify routes

_ROUTED = """
[[notify.sinks]]
type = "webhook"
name = "team-alerts"
url = "https://example.com/alerts"

[[notify.sinks]]
type = "webhook"
url = "https://example.com/everything"

[[notify.routes]]
name = "pipeline-failures"
sinks = ["team-alerts"]
types = ["pipeline.*", "task.failed"]
sources = ["pipeline"]
min_severity = "error"
dedup_seconds = 600
rate_limit = 10
rate_period = 30

[[notify.routes]]
name = "everything"
sinks = ["webhook"]
"""


class _Recorder(NotificationSink):
    def __init__(self, name: str) -> None:
        self.name = name
        self.subjects: list[str] = []

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self.subjects.append(subject)


def _config(tmp_path: Path, body: str) -> AutomationConfig:
    path = tmp_path / "automation_file.toml"
    _write_toml(path, body)
    return AutomationConfig.load(path)


def _private_router() -> NotificationRouter:
    return NotificationRouter(NotificationManager(dedup_seconds=0.0), EventBus())


def test_routes_are_built_from_toml(tmp_path: Path) -> None:
    routes = _config(tmp_path, _ROUTED).notification_routes()
    assert routes == [
        Route(
            "pipeline-failures",
            sinks=("team-alerts",),
            types=("pipeline.*", "task.failed"),
            sources=("pipeline",),
            min_severity=Severity.ERROR,
            dedup_seconds=600.0,
            rate_limit=10,
            rate_period=30.0,
        ),
        Route("everything", sinks=("webhook",)),
    ]
    assert routes[1].min_severity is Severity.WARNING
    assert routes[1].dedup_seconds == pytest.approx(300.0)


def test_apply_to_loads_the_routes_and_starts_the_router(tmp_path: Path) -> None:
    router = _private_router()
    config = _config(tmp_path, _ROUTED)
    assert config.apply_to(router.manager, router) == 2
    assert router.manager.names() == ("team-alerts", "webhook")
    assert [route.name for route in router.routes()] == ["pipeline-failures", "everything"]
    assert router.active is True
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value.status_code = 200
        router.bus.publish(TaskFailed(source="pipeline", subject="load failed"))
    assert post.call_count == 2
    assert {call.args[0] for call in post.call_args_list} == {
        "https://example.com/alerts",
        "https://example.com/everything",
    }


def test_apply_to_without_a_router_leaves_routing_alone(tmp_path: Path) -> None:
    manager = NotificationManager(dedup_seconds=0.0)
    assert _config(tmp_path, _ROUTED).apply_to(manager) == 2
    assert manager.names() == ("team-alerts", "webhook")


def test_a_route_may_name_a_sink_registered_in_code(tmp_path: Path) -> None:
    body = """
    [[notify.routes]]
    name = "to-code-sink"
    sinks = ["pager"]
    """
    config = _config(tmp_path, body)
    with pytest.raises(ConfigException, match="unknown sink"):
        config.notification_routes()
    assert config.notification_routes(known_sinks=["pager"]) == [
        Route("to-code-sink", sinks=("pager",))
    ]
    router = _private_router()
    pager = _Recorder("pager")
    router.manager.register(pager)
    assert config.apply_to(router.manager, router) == 0
    router.bus.publish(PipelineFailed(source="pipeline", subject="daily failed"))
    assert pager.subjects == ["[ERROR] pipeline.failed: daily failed"]


@pytest.mark.parametrize(
    "route,message",
    [
        ('name = "r"\nsinks = ["nobody"]', "unknown sink"),
        ('name = "r"\nmin_severity = "fatal"', "min_severity"),
        ('name = "r"\nmin_severity = 3', "min_severity"),
        ('name = "r"\ncolour = "red"', "colour"),
        ('sinks = ["team-alerts"]', "name"),
        ('name = ""', "name"),
        ('name = "r"\nrate_limit = -1', "rate_limit"),
        ('name = "r"\nrate_period = 0', "rate_period"),
        ('name = "r"\ndedup_seconds = "long"', "dedup_seconds"),
        ('name = "r"\ntypes = [5]', "route type"),
        ('name = "r"\nsinks = "team-alerts"\n\n[[notify.routes]]\nname = "r"', "declared twice"),
    ],
)
def test_a_bad_route_is_rejected(tmp_path: Path, route: str, message: str) -> None:
    body = f"""
[[notify.sinks]]
type = "email"
name = "team-alerts"
host = "smtp.example.com"
port = 587
sender = "alerts@example.com"
recipients = ["ops@example.com"]

[[notify.routes]]
{route}
"""
    config = _config(tmp_path, body)
    with pytest.raises(ConfigException, match=message):
        config.notification_routes()
    router = _private_router()
    router.add_route(Route("by-hand"))
    with pytest.raises(ConfigException, match=message):
        config.apply_to(router.manager, router)
    assert router.manager.names() == ()
    assert router.routes() == [Route("by-hand")]
    assert router.active is False


@pytest.mark.parametrize(
    "body,message",
    [
        ('[notify]\nroutes = "all"', "array of tables"),
        ('[notify]\nroutes = ["all"]', "must be a table"),
        ('[notify]\nsinks = "all"', "array of tables"),
        ("[notify]\nsinks = [3]", "must be a table"),
    ],
)
def test_notify_tables_must_be_arrays_of_tables(tmp_path: Path, body: str, message: str) -> None:
    config = _config(tmp_path, body)
    with pytest.raises(ConfigException, match=message):
        config.apply_to(NotificationManager())


def test_applying_again_follows_the_file(tmp_path: Path) -> None:
    router = _private_router()
    router.manager.register(_Recorder("chat"))
    router.add_route(Route("by-hand", sinks=("chat",)))
    first = """
    [[notify.routes]]
    name = "a"
    sinks = ["chat"]

    [[notify.routes]]
    name = "b"
    sinks = ["chat"]
    """
    second = """
    [[notify.routes]]
    name = "b"
    sinks = ["chat"]
    min_severity = "critical"

    [[notify.routes]]
    name = "c"
    """
    _config(tmp_path, first).apply_to(router.manager, router)
    assert [route.name for route in router.routes()] == ["by-hand", "a", "b"]
    _config(tmp_path, second).apply_to(router.manager, router)
    assert [route.name for route in router.routes()] == ["by-hand", "b", "c"]
    assert router.routes()[1].min_severity is Severity.CRITICAL
    _config(tmp_path, "# no routes any more\n").apply_to(router.manager, router)
    assert router.routes() == [Route("by-hand", sinks=("chat",))]
    assert router.active is True


def test_the_router_stops_when_the_file_leaves_it_without_routes(tmp_path: Path) -> None:
    router = _private_router()
    router.manager.register(_Recorder("chat"))
    _config(tmp_path, '[[notify.routes]]\nname = "a"\n').apply_to(router.manager, router)
    assert router.active is True
    _config(tmp_path, "# no routes any more\n").apply_to(router.manager, router)
    assert router.routes() == []
    assert router.active is False


def test_a_file_without_routes_does_not_stop_a_router_it_never_configured(tmp_path: Path) -> None:
    router = _private_router()
    router.start()
    _config(tmp_path, "# no routes at all\n").apply_to(router.manager, router)
    assert router.active is True
    router.stop()


def test_routes_are_hot_reloaded_with_the_file(tmp_path: Path) -> None:
    router = _private_router()
    chat = _Recorder("chat")
    router.manager.register(chat)
    path = tmp_path / "automation_file.toml"
    _write_toml(path, '[[notify.routes]]\nname = "errors"\nmin_severity = "error"\n')

    def apply(config: AutomationConfig) -> None:
        config.apply_to(router.manager, router)

    watcher = ConfigWatcher(path, apply, interval=60.0)
    try:
        apply(watcher.start())
        router.bus.publish(TaskFailed(source="pipeline", subject="before reload"))
        time.sleep(0.01)
        _write_toml(path, '[[notify.routes]]\nname = "critical-only"\nmin_severity = "critical"\n')
        assert watcher.check_once() is True
        assert [route.name for route in router.routes()] == ["critical-only"]
        router.bus.publish(TaskFailed(source="pipeline", subject="after reload"))
        time.sleep(0.01)
        _write_toml(path, '[[notify.routes]]\nname = "broken"\nmin_severity = "fatal"\n')
        assert watcher.check_once() is True
        assert [route.name for route in router.routes()] == ["critical-only"]
    finally:
        watcher.stop()
    assert chat.subjects == ["[ERROR] task.failed: before reload"]
