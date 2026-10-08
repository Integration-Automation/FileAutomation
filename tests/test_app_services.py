"""The scheduler, integrity, audit, notification, settings and dashboard services."""

# pylint: disable=no-member  # the member exists on the object the fixture builds
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import ast
import json
import subprocess  # nosec B404  # the test starts this interpreter with a fixed argument list
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from automation_file.app import (
    MASK,
    NAVIGATION,
    AppException,
    AppServices,
    AuditService,
    IntegrityService,
    NotificationService,
    SchedulerService,
    ServiceOptions,
    SettingsService,
    app_services,
    brief_run,
    build_services,
    reset_app_services,
)
from automation_file.app import settings_service as settings_module
from automation_file.app.settings_service import EXTRA_MODULES
from automation_file.audit import AuditException, AuditTrail, MemoryAuditStore
from automation_file.core.action_registry import ActionRegistry
from automation_file.core.config import ConfigException
from automation_file.core.optional import EXTRAS, install_hint
from automation_file.events import Event, EventBus, PipelineFailed, Severity, SystemErrorEvent
from automation_file.exceptions import FileAutomationException
from automation_file.integrity import IntegrityException
from automation_file.integrity import actions as integrity_actions
from automation_file.notify import (
    NotificationException,
    NotificationManager,
    NotificationRouter,
    NotificationSink,
)
from automation_file.pipeline import MemoryRunStore
from automation_file.scheduler import schedule_list, schedule_remove_all
from automation_file.storage import File, clear_memory_stores

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PACKAGE = REPO_ROOT / "automation_file" / "app"
TREE = "memory://app-tree/data"
BASELINE = "memory://app-state/data.json"
NEVER = "0 0 29 2 *"
WAIT = 10.0


class _Recorder(NotificationSink):
    def __init__(self, name: str) -> None:
        self.name = name
        self.sent: list[tuple[str, str, str]] = []

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self.sent.append((subject, body, level))


class _Broken(NotificationSink):
    name = "broken"

    def send(self, subject: str, body: str, level: str = "info") -> None:
        raise NotificationException("POST https://hooks.example.com/services/s3cr3t failed")


@pytest.fixture(autouse=True)
def _clean_global_state() -> Iterator[None]:
    clear_memory_stores()
    yield
    integrity_actions.stop_all_monitors()
    schedule_remove_all()
    clear_memory_stores()
    reset_app_services()


@pytest.fixture(name="bus")
def _bus() -> EventBus:
    return EventBus()


@pytest.fixture(name="manager")
def _manager() -> NotificationManager:
    return NotificationManager()


@pytest.fixture(name="router")
def _router(manager: NotificationManager, bus: EventBus) -> Iterator[NotificationRouter]:
    router = NotificationRouter(manager, bus)
    yield router
    router.stop()


@pytest.fixture(name="trail")
def _trail(bus: EventBus) -> Iterator[AuditTrail]:
    trail = AuditTrail(bus=bus)
    yield trail
    trail.close()


# ---------------------------------------------------------------------- scheduler


def test_jobs_are_added_listed_and_removed() -> None:
    scheduler = SchedulerService()
    added = scheduler.add("app-job", NEVER, [["FA_storage_schemes"]])
    assert (added["name"], added["cron"]) == ("app-job", NEVER)
    assert [job["name"] for job in scheduler.jobs()] == ["app-job"]
    scheduler.add(" second ", NEVER, '[["FA_storage_schemes"]]', allow_overlap=True)
    assert [job["name"] for job in schedule_list()] == ["app-job", "second"]
    assert scheduler.remove("app-job")["name"] == "app-job"
    assert [job["name"] for job in scheduler.remove_all()] == ["second"]
    assert scheduler.jobs() == []


def test_a_job_needs_a_name_a_cron_expression_and_an_action_list() -> None:
    scheduler = SchedulerService()
    with pytest.raises(AppException, match="a name and a cron expression"):
        scheduler.add("", NEVER, [["FA_storage_schemes"]])
    with pytest.raises(AppException, match="a name and a cron expression"):
        scheduler.add("job", "  ", [["FA_storage_schemes"]])
    with pytest.raises(AppException, match="not valid JSON"):
        scheduler.add("job", NEVER, "[[oops")
    for wrong in ("{}", "[]", ""):
        with pytest.raises(AppException, match="non-empty JSON array"):
            scheduler.add("job", NEVER, wrong)
    with pytest.raises(FileAutomationException):
        scheduler.add("job", "not a cron", [["FA_storage_schemes"]])
    with pytest.raises(FileAutomationException):
        scheduler.remove("missing")
    assert scheduler.jobs() == []


# ---------------------------------------------------------------------- integrity


def _tree() -> None:
    File(f"{TREE}/a.txt").write(b"alpha")
    File(f"{TREE}/sub/b.txt").write(b"bravo")


def test_baseline_verify_and_accept() -> None:
    _tree()
    integrity = IntegrityService()
    stored = integrity.baseline(TREE, BASELINE)
    assert (stored["entries"], stored["algorithm"]) == (2, "sha256")
    assert integrity.verify(TREE, BASELINE)["ok"] is True
    File(f"{TREE}/a.txt").write(b"changed")
    File(f"{TREE}/new.txt").write(b"new")
    report = integrity.verify(f"  {TREE} ", BASELINE, deep=True)
    assert report["ok"] is False
    assert (report["counts"]["modified"], report["counts"]["created"]) == (1, 1)
    assert integrity.accept(TREE, BASELINE)["entries"] == 3
    assert integrity.verify(TREE, BASELINE)["ok"] is True


def test_the_algorithms_offered_start_with_the_default() -> None:
    assert IntegrityService().algorithms() == ["sha256", "blake2b", "sha512"]


def test_a_target_and_a_baseline_are_required() -> None:
    integrity = IntegrityService()
    with pytest.raises(AppException, match="the target is required"):
        integrity.verify("", BASELINE)
    with pytest.raises(AppException, match="the baseline is required"):
        integrity.baseline(TREE, "  ")
    with pytest.raises(AppException, match="the monitor name is required"):
        integrity.start_monitor(" ", TREE, BASELINE)
    with pytest.raises(AppException, match="more than 0 seconds"):
        integrity.start_monitor("m", TREE, BASELINE, interval=0)


def test_a_monitor_is_started_reported_and_stopped() -> None:
    _tree()
    integrity = IntegrityService()
    integrity.baseline(TREE, BASELINE)
    started = integrity.start_monitor("app-monitor", TREE, BASELINE, interval=3600)
    assert (started["name"], started["running"]) == ("app-monitor", True)
    assert [status["name"] for status in integrity.status()] == ["app-monitor"]
    assert integrity.status("app-monitor")[0]["target"] == TREE
    drift = integrity.drift()[0]
    assert (drift.name, drift.running, drift.ok, drift.needs_attention) == (
        "app-monitor",
        True,
        None,
        False,
    )
    with pytest.raises(IntegrityException, match="already running"):
        integrity.start_monitor("app-monitor", TREE, BASELINE)
    assert integrity.stop_monitor("app-monitor")["running"] is False
    assert integrity.status() == []
    with pytest.raises(IntegrityException):
        integrity.stop_monitor("app-monitor")


def test_a_monitor_needs_a_stored_baseline() -> None:
    _tree()
    with pytest.raises(IntegrityException, match="no baseline"):
        IntegrityService().start_monitor("app-monitor", TREE, BASELINE)


def test_only_the_monitors_this_service_started_are_stopped_with_it() -> None:
    _tree()
    integrity = IntegrityService()
    integrity.baseline(TREE, BASELINE)
    integrity.start_monitor("mine", TREE, BASELINE, interval=3600)
    integrity.start_monitor("gone", TREE, BASELINE, interval=3600)
    integrity_actions.integrity_watch_start("theirs", TREE, BASELINE, 3600)
    integrity_actions.integrity_watch_stop("gone")
    assert integrity.stop_started() == ["mine"]
    assert [status["name"] for status in integrity.status()] == ["theirs"]
    assert integrity.stop_started() == []


def test_drift_summarises_the_last_report_of_each_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = [
        {
            "name": "drifted",
            "target": "memory://t/a",
            "baseline": "memory://s/a.json",
            "running": True,
            "last_run": "2026-10-08T00:00:00+00:00",
            "last_error": None,
            "last_report": {
                "ok": False,
                "changes": [{"kind": "modified"}, {"kind": "deleted"}],
                "counts": {"modified": 1, "deleted": 1, "created": 0},
            },
        },
        {"name": "failing", "target": "memory://t/b", "running": True, "last_error": "boom"},
        {"name": "clean", "target": "memory://t/c", "last_report": {"ok": True, "changes": []}},
    ]
    monkeypatch.setattr(
        "automation_file.app.integrity_service.integrity_status", lambda name=None: statuses
    )
    drifted, failing, clean = IntegrityService().drift()
    assert (drifted.ok, drifted.changes, drifted.needs_attention) == (False, 2, True)
    assert drifted.counts == {"modified": 1, "deleted": 1, "created": 0}
    assert (failing.ok, failing.last_error, failing.needs_attention) == (None, "boom", True)
    assert (clean.ok, clean.running, clean.needs_attention) == (True, False, False)
    assert drifted.to_dict()["needs_attention"] is True


# ---------------------------------------------------------------------- audit


def test_audit_is_not_configured_until_it_has_a_store(trail: AuditTrail) -> None:
    audit = AuditService(trail)
    assert audit.is_configured() is False
    assert audit.status() == {
        "configured": False,
        "active": False,
        "store": None,
        "db_path": None,
        "schema_version": None,
    }
    assert audit.recent() == []
    with pytest.raises(AuditException, match="not configured"):
        audit.search()
    with pytest.raises(AuditException, match="not configured"):
        audit.count()


def test_audit_records_are_searched_counted_and_masked(trail: AuditTrail, bus: EventBus) -> None:
    audit = AuditService(trail)
    status = audit.configure(MemoryAuditStore())
    assert (status["configured"], status["active"], status["store"]) == (
        True,
        True,
        "MemoryAuditStore",
    )
    bus.publish(
        PipelineFailed(
            source="pipeline",
            subject="nightly failed",
            payload={"pipeline": "nightly", "status": "failed", "password": "hunter2"},  # nosec B105  # a made-up value for a stand-in, not a credential
        )
    )
    trail.record("manual.note", resource="s3://reports/a.csv", status="ok", actor="ops")
    assert audit.count() == 2
    assert audit.count(status="failed") == 1
    assert audit.count(status="", actor=None, pipeline="   ") == 2
    found = audit.search(pipeline="nightly")
    assert [record["action"] for record in found] == ["pipeline.failed"]
    assert found[0]["metadata"]["password"] == MASK
    assert "hunter2" not in json.dumps(audit.search())
    assert [record["action"] for record in audit.search(resource_prefix="s3://reports/")] == [
        "manual.note"
    ]
    assert [record["action"] for record in audit.recent(limit=1)] == ["manual.note"]
    with pytest.raises(AuditException, match="unknown audit filter"):
        audit.search(colour="red")
    assert "since" in audit.filter_names()
    assert "limit" in audit.filter_names()


def test_audit_is_configured_with_a_sqlite_path(trail: AuditTrail, tmp_path: Path) -> None:
    audit = AuditService(trail)
    path = tmp_path / "audit.sqlite"
    status = audit.configure(path)
    assert status["store"] == "SQLiteAuditStore"
    assert status["db_path"] == str(path)
    assert status["schema_version"] == 2
    assert audit.search() == []


# ---------------------------------------------------------------------- notifications


def test_sinks_are_described_without_their_secrets(
    manager: NotificationManager, router: NotificationRouter
) -> None:
    from automation_file.notify import EmailSink

    manager.register(_Recorder("team"))
    manager.register(
        EmailSink(
            host="smtp.example.com",
            port=587,
            sender="bot@example.com",
            recipients=["ops@example.com"],
            username="bot",
            password="hunter2",
            name="mail",
        )
    )
    notifications = NotificationService(manager, router)
    sinks = notifications.sinks()
    assert [sink["name"] for sink in sinks] == ["team", "mail"]
    assert sinks[1]["type"] == "EmailSink"
    assert "hunter2" not in json.dumps(sinks)
    assert notifications.sink_names() == ["team", "mail"]
    assert notifications.severities() == ["info", "warning", "error", "critical"]


def test_routes_are_added_from_form_text_listed_and_removed(
    manager: NotificationManager, router: NotificationRouter, bus: EventBus
) -> None:
    recorder = _Recorder("team")
    manager.register(recorder)
    notifications = NotificationService(manager, router)
    assert notifications.router_active() is False
    route = notifications.add_route(
        {
            "name": "failures",
            "sinks": "team",
            "types": "pipeline.failed, task.failed",
            "sources": "",
            "min_severity": "error",
            "dedup_seconds": "0",
            "rate_limit": "5",
            "rate_period": None,
        }
    )
    assert route == {
        "name": "failures",
        "sinks": ["team"],
        "types": ["pipeline.failed", "task.failed"],
        "sources": [],
        "min_severity": "error",
        "dedup_seconds": 0.0,
        "rate_limit": 5,
        "rate_period": 60.0,
    }
    assert notifications.router_active() is True
    assert notifications.routes() == [route]
    bus.publish(PipelineFailed(source="pipeline", subject="nightly failed"))
    assert len(recorder.sent) == 1
    assert notifications.remove_route("failures") is True
    assert notifications.remove_route("failures") is False
    assert (notifications.routes(), notifications.router_active()) == ([], False)


def test_a_route_to_an_unknown_sink_or_with_a_wrong_option_is_refused(
    manager: NotificationManager, router: NotificationRouter
) -> None:
    manager.register(_Recorder("team"))
    notifications = NotificationService(manager, router)
    with pytest.raises(AppException, match=r"unknown sink\(s\) \['tema'\]"):
        notifications.add_route({"name": "typo", "sinks": ["tema"]})
    with pytest.raises(NotificationException, match="needs a 'name'"):
        notifications.add_route({"sinks": "team"})
    with pytest.raises(NotificationException, match="min_severity"):
        notifications.add_route({"name": "x", "min_severity": "loud"})
    with pytest.raises(NotificationException, match="rate_limit"):
        notifications.add_route({"name": "x", "rate_limit": "many"})
    with pytest.raises(NotificationException, match="unknown route option"):
        notifications.add_route({"name": "x", "colour": "red"})
    assert notifications.routes() == []


def test_a_test_message_goes_to_one_sink_or_to_all(
    manager: NotificationManager, router: NotificationRouter
) -> None:
    first, second = _Recorder("first"), _Recorder("second")
    notifications = NotificationService(manager, router)
    with pytest.raises(AppException, match="nothing to test"):
        notifications.send_test()
    manager.register(first)
    manager.register(second)
    manager.register(_Broken())
    assert notifications.send_test("first") == {"first": "sent"}
    assert notifications.send_test("first", subject="again") == {"first": "sent"}
    assert [message[0] for message in first.sent] == [
        "automation_file: test notification",
        "again",
    ]
    outcomes = notifications.send_test()
    assert (outcomes["first"], outcomes["second"]) == ("sent", "sent")
    assert outcomes["broken"].startswith("NotificationException:")
    assert "s3cr3t" not in outcomes["broken"]
    assert len(second.sent) == 1
    with pytest.raises(NotificationException, match="no notification sink"):
        notifications.send_test("missing")


# ---------------------------------------------------------------------- settings

_CONFIG = """
[[notify.sinks]]
type = "email"
name = "ops-mail"
host = "smtp.example.com"
port = 587
sender = "bot@example.com"
recipients = ["ops@example.com"]
username = "bot"
password = "${env:FA_APP_TEST_SMTP}"

[[notify.routes]]
name = "failures"
sinks = ["ops-mail"]
types = ["pipeline.failed"]
min_severity = "error"

[defaults]
dedup_seconds = 120
"""


@pytest.fixture(name="config_path")
def _config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FA_APP_TEST_SMTP", "hunter2")
    path = tmp_path / "automation_file.toml"
    path.write_text(_CONFIG, encoding="utf-8")
    return path


def test_loading_a_configuration_shows_it_masked_and_changes_nothing(
    manager: NotificationManager, router: NotificationRouter, config_path: Path
) -> None:
    settings = SettingsService(manager, router)
    summary = settings.load(config_path)
    assert summary["source"] == str(config_path)
    assert summary["applied"] is False
    assert summary["sections"] == ["defaults", "notify"]
    assert summary["sinks"] == [{"name": "ops-mail", "type": "email"}]
    assert [route["name"] for route in summary["routes"]] == ["failures"]
    assert summary["defaults"] == {"dedup_seconds": 120}
    assert summary["document"]["notify"]["sinks"][0]["password"] == MASK
    assert "hunter2" not in json.dumps(summary)
    assert manager.names() == ()
    assert router.routes() == []
    assert settings.applied() is None
    assert settings.environment()["applied_config"] is None


def test_a_webhook_url_in_a_configuration_keeps_only_its_host(
    manager: NotificationManager, router: NotificationRouter, tmp_path: Path
) -> None:
    path = tmp_path / "hooks.toml"
    path.write_text(
        '[[notify.sinks]]\ntype = "slack"\nname = "team"\n'
        'webhook_url = "https://hooks.example.com/services/T0/B0/s3cr3t"\n',
        encoding="utf-8",
    )
    summary = SettingsService(manager, router).load(path)
    assert summary["document"]["notify"]["sinks"][0]["webhook_url"] == (
        f"https://hooks.example.com/{MASK}"
    )
    assert "s3cr3t" not in json.dumps(summary)


def test_applying_a_configuration_registers_its_sinks_and_routes(
    manager: NotificationManager, router: NotificationRouter, config_path: Path
) -> None:
    settings = SettingsService(manager, router)
    summary = settings.apply(config_path)
    assert (summary["applied"], summary["registered_sinks"]) == (True, 1)
    assert manager.names() == ("ops-mail",)
    assert manager.dedup_seconds == 120.0
    assert [route.name for route in router.routes()] == ["failures"]
    assert router.active is True
    assert settings.applied() == summary
    assert settings.environment()["applied_config"] == str(config_path)
    assert "hunter2" not in json.dumps(settings.applied())


def test_a_configuration_that_cannot_be_used_raises(
    manager: NotificationManager, router: NotificationRouter, tmp_path: Path
) -> None:
    settings = SettingsService(manager, router)
    with pytest.raises(ConfigException, match="not found"):
        settings.load(tmp_path / "missing.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text('[[notify.routes]]\nname = "r"\nsinks = ["ghost"]\n', encoding="utf-8")
    with pytest.raises(ConfigException, match="unknown sink"):
        settings.load(bad)
    with pytest.raises(ConfigException, match="unknown sink"):
        settings.apply(bad)
    assert manager.names() == ()


def test_every_extra_the_package_names_has_a_status() -> None:
    assert set(EXTRA_MODULES) == set(EXTRAS)
    extras = SettingsService().extras()
    assert [extra.name for extra in extras] == list(EXTRAS)
    by_name = {extra.name: extra for extra in extras}
    assert (by_name["ftp"].installed, by_name["ftp"].install_hint) == (True, None)
    assert by_name["webdav"].installed is True
    assert by_name["s3"].feature == EXTRAS["s3"]
    assert by_name["s3"].to_dict()["modules"] == ["boto3"]


def test_a_missing_extra_carries_its_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module, "is_installed", lambda module: module != "msal")
    monkeypatch.setitem(EXTRAS, "future", "a feature this table does not know")
    by_name = {extra.name: extra for extra in SettingsService().extras()}
    assert by_name["onedrive"].installed is False
    assert by_name["onedrive"].missing == ("msal",)
    assert by_name["onedrive"].install_hint == install_hint("onedrive")
    assert (by_name["s3"].installed, by_name["s3"].install_hint) == (True, None)
    assert by_name["future"].installed is None


def test_the_environment_names_the_versions_and_the_log_file() -> None:
    environment = SettingsService().environment()
    assert environment["python"].count(".") == 2
    assert environment["log_file"].endswith(".log")
    assert set(environment) == {"version", "python", "platform", "log_file", "applied_config"}


# ---------------------------------------------------------------------- dashboard


def _echo(value: Any = None) -> Any:
    return value


def _fail() -> None:
    raise ValueError("it broke")


@pytest.fixture(name="services")
def _services(
    bus: EventBus, manager: NotificationManager, router: NotificationRouter, trail: AuditTrail
) -> AppServices:
    return build_services(
        ServiceOptions(
            run_store=MemoryRunStore(),
            registry=ActionRegistry({"T_echo": _echo, "T_fail": _fail}),
            bus=bus,
            audit_trail=trail,
            notification_manager=manager,
            notification_router=router,
        )
    )


def _run(services: AppServices, action: str) -> dict[str, Any]:
    draft = services.pipelines.new_draft("dash")
    draft.add_task(action, "only")
    started = services.pipelines.start(draft)
    assert services.pipelines.wait(started["run_id"], WAIT)
    return services.pipelines.status(started["run_id"])


def test_a_quiet_installation_is_ok(services: AppServices) -> None:
    summary = services.dashboard.summary()
    assert (summary.status, summary.reasons) == ("ok", ())
    assert summary.run_counts == {"running": 0, "succeeded": 0, "failed": 0, "cancelled": 0}
    assert (summary.running_runs, summary.recent_runs, summary.integrity, summary.events) == (
        [],
        [],
        [],
        [],
    )
    health = summary.health
    assert (health["process"], health["registry_size"], health["scheduler_jobs"]) == ("alive", 2, 0)
    assert health["audit"]["configured"] is False
    assert health["notification_router_active"] is False
    assert {"local", "memory"} <= {backend["name"] for backend in summary.storage}
    assert json.loads(json.dumps(summary.to_dict()))["status"] == "ok"


def test_the_dashboard_counts_runs_and_asks_for_attention_after_a_failure(
    services: AppServices,
) -> None:
    good = _run(services, "T_echo")
    assert services.dashboard.summary().status == "ok"
    bad = _run(services, "T_fail")
    summary = services.dashboard.summary()
    assert summary.status == "attention"
    assert summary.run_counts == {"running": 0, "succeeded": 1, "failed": 1, "cancelled": 0}
    assert [run["run_id"] for run in summary.recent_runs] == [bad["run_id"], good["run_id"]]
    assert summary.recent_runs[0]["task_statuses"] == {"failed": 1}
    assert "1 of the last 2 pipeline runs failed" in summary.reasons
    assert any("severity error or worse" in reason for reason in summary.reasons)
    assert summary.events[0]["type"] == "pipeline.failed"
    assert services.dashboard.runs(limit=1)["recent"][0]["run_id"] == bad["run_id"]


def test_recent_events_are_newest_first_filtered_and_masked(
    services: AppServices, bus: EventBus
) -> None:
    bus.publish(Event(source="test", subject="first", payload={"token": "abc"}))  # nosec B105  # a made-up value for a stand-in, not a credential
    bus.publish(SystemErrorEvent(source="test", subject="second"))
    events = services.dashboard.recent_events()
    assert [event["subject"] for event in events] == ["second", "first"]
    assert events[1]["payload"] == {"token": MASK}
    serious = services.dashboard.recent_events(min_severity=Severity.ERROR.value)
    assert [event["subject"] for event in serious] == ["second"]
    assert len(services.dashboard.recent_events(limit=1)) == 1


def test_integrity_drift_reaches_the_dashboard(services: AppServices) -> None:
    _tree()
    services.integrity.baseline(TREE, BASELINE)
    services.integrity.start_monitor("dash-monitor", TREE, BASELINE, interval=3600)
    summary = services.dashboard.summary()
    assert [monitor["name"] for monitor in summary.integrity] == ["dash-monitor"]
    assert summary.health["integrity_monitors"] == 1
    assert summary.status == "ok"


def test_a_monitor_that_found_drift_asks_for_attention(
    services: AppServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    statuses = [
        {"name": "a", "target": "memory://t/a", "last_report": {"ok": False, "changes": [{}]}},
        {"name": "b", "target": "memory://t/b", "last_error": "boom"},
    ]
    monkeypatch.setattr(
        "automation_file.app.integrity_service.integrity_status", lambda name=None: statuses
    )
    summary = services.dashboard.summary()
    assert summary.status == "attention"
    assert summary.reasons == (
        "integrity monitor 'a' found 1 change(s)",
        "integrity monitor 'b' could not verify",
    )


def test_a_part_that_cannot_be_read_is_reported_not_raised(
    services: AppServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> list[Any]:
        raise IntegrityException("the store is gone")

    monkeypatch.setattr(services.integrity, "drift", broken)
    summary = services.dashboard.summary()
    assert summary.status == "attention"
    assert summary.reasons == ("integrity cannot be read: IntegrityException",)
    assert summary.integrity == []
    assert summary.health["process"] == "alive"


def test_a_brief_run_drops_the_task_details() -> None:
    brief = brief_run(
        {
            "run_id": "r1",
            "pipeline": "p",
            "status": "failed",
            "active": False,
            "started_at": "t0",
            "finished_at": "t1",
            "error": "bad",
            "params": {"a": 1},
            "tasks": {"a": {"status": "succeeded"}, "b": {"status": "failed"}},
        }
    )
    assert brief == {
        "run_id": "r1",
        "pipeline": "p",
        "status": "failed",
        "active": False,
        "started_at": "t0",
        "finished_at": "t1",
        "error": "bad",
        "tasks": 2,
        "task_statuses": {"succeeded": 1, "failed": 1},
    }


# ---------------------------------------------------------------------- the set of services


def test_the_navigation_names_one_service_each_in_order() -> None:
    assert NAVIGATION == (
        "Dashboard",
        "Files",
        "Storage",
        "Pipelines",
        "Scheduler",
        "Integrity",
        "Audit",
        "Notifications",
        "Settings",
    )
    services = build_services()
    assert [name.lower() for name in NAVIGATION] == list(AppServices.__dataclass_fields__)
    for name in NAVIGATION:
        assert getattr(services, name.lower()) is not None


def test_the_shared_set_is_built_once_and_can_be_forgotten() -> None:
    first = app_services()
    assert app_services() is first
    reset_app_services()
    assert app_services() is not first


def _module_level_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: relative import"
            names.append(node.module or "")
    return names


_FORBIDDEN_ROOTS = (
    "PySide6",
    "boto3",
    "botocore",
    "azure",
    "dropbox",
    "paramiko",
    "googleapiclient",
    "msal",
    "box_sdk_gen",
    "pyarrow",
    "fsspec",
    "smbclient",
)


@pytest.mark.parametrize("path", sorted(APP_PACKAGE.glob("*.py")), ids=lambda path: path.name)
def test_no_module_of_the_layer_imports_a_gui_toolkit_or_an_sdk(path: Path) -> None:
    imported = _module_level_imports(path)
    assert [name for name in imported if name.partition(".")[0] in _FORBIDDEN_ROOTS] == []
    assert [name for name in imported if name.startswith("automation_file.ui")] == []
    assert [name for name in imported if name == "automation_file"] == []


def test_importing_and_using_the_layer_loads_no_gui_toolkit() -> None:
    probe = (
        "import sys\n"
        "import automation_file.app as app\n"
        "services = app.app_services()\n"
        "services.dashboard.summary()\n"
        "services.settings.extras()\n"
        "print('PySide6' in sys.modules)\n"
    )
    result = subprocess.run(  # nosec B603 - fixed argv: this interpreter and the script above
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().splitlines()[-1] == "False"
