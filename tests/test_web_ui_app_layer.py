"""The Web UI renders its fragments from the application layer, escaped and masked."""
# pylint: disable=cyclic-import

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from automation_file.app import MASK, NAVIGATION, AppServices, ServiceOptions, build_services
from automation_file.audit import AuditTrail, MemoryAuditStore
from automation_file.core.action_registry import ActionRegistry
from automation_file.events import Event, EventBus, PipelineFailed
from automation_file.integrity import IntegrityException
from automation_file.integrity import actions as integrity_actions
from automation_file.notify import NotificationManager, NotificationRouter
from automation_file.pipeline import MemoryRunStore
from automation_file.server.web_ui import WebUIServer, start_web_ui
from automation_file.storage import File, MemoryStorage, StorageResolver, clear_memory_stores
from tests._insecure_fixtures import insecure_url

TREE = "memory://webui-tree/data"
BASELINE = "memory://webui-state/data.json"
SCRIPT = "<script>alert('x')</script>"
WAIT = 10.0


def _fail() -> None:
    raise ValueError(f"it broke {SCRIPT}")


@pytest.fixture(autouse=True)
def _clean_global_state() -> Iterator[None]:
    clear_memory_stores()
    yield
    integrity_actions.stop_all_monitors()
    clear_memory_stores()


@pytest.fixture(name="bus")
def _bus() -> EventBus:
    return EventBus()


@pytest.fixture(name="services")
def _services(bus: EventBus) -> Iterator[AppServices]:
    manager = NotificationManager()
    router = NotificationRouter(manager, bus)
    trail = AuditTrail(bus=bus)
    resolver = StorageResolver(defaults=False)
    resolver.mount("memory://webui", MemoryStorage())
    yield build_services(
        ServiceOptions(
            resolver=resolver,
            run_store=MemoryRunStore(),
            registry=ActionRegistry({"T_echo": lambda value=None: value, "T_fail": _fail}),
            bus=bus,
            audit_trail=trail,
            notification_manager=manager,
            notification_router=router,
        )
    )
    router.stop()
    trail.close()


@pytest.fixture(name="server")
def _server(services: AppServices) -> Iterator[WebUIServer]:
    server = start_web_ui(host="127.0.0.1", port=0, services=services)
    yield server
    server.shutdown()
    server.server_close()


def _get(server: WebUIServer, path: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    host, port = server.server_address[:2]
    url = insecure_url("http", f"{host}:{port}{path}")
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:  # nosec B310
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def _run(services: AppServices, action: str, name: str = "web") -> str:
    draft = services.pipelines.new_draft(name)
    draft.add_task(action, "only")
    run_id = services.pipelines.start(draft)["run_id"]
    assert services.pipelines.wait(run_id, WAIT)
    return run_id


def test_the_index_polls_every_fragment_and_names_the_navigation(server: WebUIServer) -> None:
    status, body = _get(server, "/")
    assert status == 200
    for fragment in (
        "health",
        "runs",
        "integrity",
        "events",
        "storage",
        "audit",
        "progress",
        "registry",
    ):
        assert f'hx-get="/ui/{fragment}"' in body
    for name in NAVIGATION:
        assert f"<span>{name}</span>" in body
    assert _get(server, "/index.html")[0] == 200


def test_the_server_uses_the_services_it_was_given(
    server: WebUIServer, services: AppServices
) -> None:
    assert server.services is services
    status, body = _get(server, "/ui/registry")
    assert status == 200
    assert "<li><code>T_echo</code></li>" in body
    assert "FA_storage_copy" not in body


def test_the_default_services_are_the_process_wide_ones() -> None:
    from automation_file.app import app_services

    server = WebUIServer(("127.0.0.1", 0))
    try:
        assert server.services is app_services()
    finally:
        server.server_close()


def test_health_comes_from_the_dashboard_and_says_why_it_needs_attention(
    server: WebUIServer, services: AppServices
) -> None:
    status, body = _get(server, "/ui/health")
    assert status == 200
    assert "<p class='ok'>status: ok</p>" in body
    assert "<th>registry size</th><td>2</td>" in body
    assert "<th>process</th><td>alive</td>" in body
    assert "<th>audit</th><td>not configured</td>" in body
    _run(services, "T_fail")
    body = _get(server, "/ui/health")[1]
    assert "<p class='attention'>status: attention</p>" in body
    assert "<li>1 of the last 1 pipeline runs failed</li>" in body


def test_runs_are_listed_newest_first_with_their_counts(
    server: WebUIServer, services: AppServices
) -> None:
    assert "no pipeline runs recorded" in _get(server, "/ui/runs")[1]
    good = _run(services, "T_echo")
    bad = _run(services, "T_fail")
    body = _get(server, "/ui/runs")[1]
    assert "0 running, 1 succeeded, 1 failed, 0 cancelled" in body
    assert body.index(bad[:8]) < body.index(good[:8])
    assert "<td>1 failed</td>" in body
    assert "<td>web</td>" in body


def test_everything_rendered_is_escaped(
    server: WebUIServer, services: AppServices, bus: EventBus
) -> None:
    _run(services, "T_fail", name=SCRIPT)
    bus.publish(Event(source=SCRIPT, subject=SCRIPT, payload={"error": SCRIPT}))
    services.audit.configure(MemoryAuditStore())
    bus.publish(Event(source="test", subject="after", payload={"resource": SCRIPT}))
    for path in ("/ui/health", "/ui/runs", "/ui/events", "/ui/audit", "/ui/storage"):
        status, body = _get(server, path)
        assert status == 200
        assert "<script" not in body, path
    assert "&lt;script&gt;" in _get(server, "/ui/events")[1]
    assert "&lt;script&gt;" in _get(server, "/ui/runs")[1]
    assert "&lt;script&gt;" in _get(server, "/ui/audit")[1]


def test_secrets_are_masked_before_they_are_rendered(
    server: WebUIServer, services: AppServices, bus: EventBus
) -> None:
    services.audit.configure(MemoryAuditStore())
    bus.publish(
        PipelineFailed(
            source="pipeline",
            subject="fetch https://user:hunter2@example.com/x failed",
            payload={"error": "Bearer abc.def-123 was refused", "token": "t0ps3cret"},
        )
    )
    for path in ("/ui/events", "/ui/audit", "/ui/health"):
        body = _get(server, path)[1]
        assert "hunter2" not in body, path
        assert "abc.def-123" not in body, path
        assert "t0ps3cret" not in body, path
    assert MASK in _get(server, "/ui/events")[1]


def test_integrity_monitors_are_listed(server: WebUIServer, services: AppServices) -> None:
    assert "no integrity monitor is running" in _get(server, "/ui/integrity")[1]
    File(f"{TREE}/a.txt").write(b"alpha")
    services.integrity.baseline(TREE, BASELINE)
    services.integrity.start_monitor("webui-monitor", TREE, BASELINE, interval=3600)
    body = _get(server, "/ui/integrity")[1]
    assert "<td>webui-monitor</td>" in body
    assert f"<td>{TREE}</td>" in body
    assert "<td>not verified yet</td>" in body


def test_storage_status_lists_the_backends(server: WebUIServer) -> None:
    body = _get(server, "/ui/storage")[1]
    assert "<td>memory://webui</td><td>mount</td><td>yes</td><td>mounted</td>" in body
    assert "<td>box</td><td>client</td>" in body


def test_audit_entries_appear_once_audit_is_configured(
    server: WebUIServer, services: AppServices, bus: EventBus
) -> None:
    assert "audit is not configured" in _get(server, "/ui/audit")[1]
    services.audit.configure(MemoryAuditStore())
    assert "no audit records yet" in _get(server, "/ui/audit")[1]
    bus.publish(PipelineFailed(source="pipeline", subject="nightly failed"))
    body = _get(server, "/ui/audit")[1]
    assert "<td>pipeline.failed</td>" in body
    assert "<td>error</td>" in body


def test_a_fragment_whose_service_fails_says_so_instead_of_breaking(
    server: WebUIServer, services: AppServices, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> list[Any]:
        raise IntegrityException(f"the store is gone {SCRIPT}")

    monkeypatch.setattr(services.dashboard, "integrity", broken)
    status, body = _get(server, "/ui/integrity")
    assert status == 200
    assert body == "<p class='muted'>unavailable: IntegrityException</p>"
    assert "attention" in _get(server, "/ui/health")[1]


def test_the_fragments_stay_read_only_and_behind_the_secret(services: AppServices) -> None:
    server = start_web_ui(host="127.0.0.1", port=0, shared_secret="s3cr3t", services=services)
    try:
        for path in ("/ui/runs", "/ui/events", "/ui/audit", "/ui/integrity", "/ui/storage"):
            assert _get(server, path)[0] == 401
            assert _get(server, path, {"Authorization": "Bearer wrong"})[0] == 401
            assert _get(server, path, {"Authorization": "Bearer s3cr3t"})[0] == 200
        host, port = server.server_address[:2]
        request = urllib.request.Request(
            insecure_url("http", f"{host}:{port}/ui/runs"),
            data=b"{}",
            headers={"Authorization": "Bearer s3cr3t"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)  # nosec B310
        assert caught.value.code == 501
    finally:
        server.shutdown()
        server.server_close()
