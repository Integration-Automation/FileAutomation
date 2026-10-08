"""The pages of the main window, fed by their services through a pool that runs at once."""

# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted
# pylint: disable=wrong-import-position  # imports follow pytest.importorskip

from __future__ import annotations

import ast
import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automation_file.app import (
    MASK,
    AppServices,
    ServiceOptions,
    build_services,
)
from automation_file.audit import AuditTrail, MemoryAuditStore
from automation_file.core.action_registry import ActionRegistry
from automation_file.events import EventBus, PipelineFailed, SystemErrorEvent
from automation_file.integrity import actions as integrity_actions
from automation_file.notify import (
    NotificationException,
    NotificationManager,
    NotificationRouter,
    NotificationSink,
)
from automation_file.pipeline import MemoryRunStore
from automation_file.scheduler import schedule_list, schedule_remove_all
from automation_file.storage import (
    File,
    MemoryStorage,
    StorageResolver,
    clear_memory_stores,
)
from tests.ui_stand_in import HeldPool, SyncPool

ROOT = "memory://pages"
TREE = "memory://pages-tree/data"
BASELINE = "memory://pages-state/data.json"
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


@pytest.fixture(name="qt_app", scope="module")
def _qt_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _clean_global_state() -> Iterator[None]:
    clear_memory_stores()
    yield
    integrity_actions.stop_all_monitors()
    schedule_remove_all()
    clear_memory_stores()


@pytest.fixture(name="bus")
def _bus() -> EventBus:
    return EventBus()


@pytest.fixture(name="manager")
def _manager() -> NotificationManager:
    return NotificationManager()


@pytest.fixture(name="resolver")
def _resolver() -> StorageResolver:
    resolver = StorageResolver(defaults=False)
    resolver.mount(ROOT, MemoryStorage())
    return resolver


@pytest.fixture(name="services")
def _services(
    bus: EventBus, manager: NotificationManager, resolver: StorageResolver
) -> Iterator[AppServices]:
    router = NotificationRouter(manager, bus)
    trail = AuditTrail(bus=bus)
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


@pytest.fixture(name="log")
def _log(qt_app) -> Iterator[Any]:
    from automation_file.ui.log_widget import LogPanel

    assert qt_app is not None
    panel = LogPanel()
    yield panel
    panel.deleteLater()


def _fail() -> None:
    raise ValueError("it broke")


def _page(page_class: str, service: Any, log: Any, pool: Any = None) -> Any:
    from automation_file.ui import pages

    return getattr(pages, page_class)(service, log, SyncPool() if pool is None else pool)


def _column(table: Any, column: int) -> list[str]:
    return [table.item(row, column).text() for row in range(table.rowCount())]


def _select(table: Any, text: str, column: int = 0) -> None:
    table.selectRow(_column(table, column).index(text))


# ---------------------------------------------------------------------- the base page


def test_a_call_with_a_key_is_skipped_while_the_earlier_one_runs(
    services: AppServices, log: Any
) -> None:
    pool = HeldPool()
    page = _page("StoragePage", services.storage, log, pool)
    seen: list[Any] = []
    assert page.run_async(lambda: 1, "first", seen.append, key="k") is True
    assert page.run_async(lambda: 2, "second", seen.append, key="k") is False
    assert page.run_async(lambda: 3, "other key", seen.append, key="other") is True
    assert page.run_async(lambda: 4, "no key", seen.append) is True
    assert pool.release() == 3
    assert seen == [1, 3, 4]
    assert page.run_async(lambda: 5, "again", seen.append, key="k") is True
    pool.release()
    assert seen[-1] == 5


def test_a_failure_is_shown_masked_on_the_status_line_and_in_the_log(
    services: AppServices, log: Any
) -> None:
    page = _page("StoragePage", services.storage, log)

    def fails() -> None:
        raise ValueError("cannot reach https://user:hunter2@example.com/x")

    done: list[Any] = []
    page.run_async(fails, "read", done.append, key="k")
    assert done == []
    assert page.status_text().startswith("read failed:")
    assert "hunter2" not in page.status_text()
    assert "hunter2" not in log.toPlainText()
    assert "Storage: read failed" in log.toPlainText()
    assert page.run_async(lambda: 1, "after", done.append, key="k") is True
    assert done == [1]


def test_a_quiet_call_leaves_no_line_and_a_normal_one_announces_itself(
    services: AppServices, log: Any
) -> None:
    page = _page("StoragePage", services.storage, log)
    page.run_async(lambda: 1, "quiet work", quiet=True)
    assert log.toPlainText() == ""
    page.run_async(lambda: 1, "loud work")
    assert "Storage: loud work" in log.toPlainText()


def test_results_that_arrive_after_shutdown_are_dropped(services: AppServices, log: Any) -> None:
    pool = HeldPool()
    page = _page("StoragePage", services.storage, log, pool)
    seen: list[Any] = []
    page.run_async(lambda: 1, "late", seen.append)
    page.run_async(_fail, "late failure")
    page.shutdown()
    pool.release()
    assert seen == []
    assert page.status_text() == ""


def test_with_a_real_thread_pool_the_work_leaves_the_ui_thread_and_the_result_returns_to_it(
    qt_app, services: AppServices, log: Any
) -> None:
    from PySide6.QtCore import QThreadPool

    pool = QThreadPool()
    page = _page("StoragePage", services.storage, log, pool)
    main = threading.main_thread()
    seen: list[tuple[str, bool]] = []

    def work() -> int:
        seen.append(("work", threading.current_thread() is main))
        return 42

    def done(result: int) -> None:
        seen.append((f"done {result}", threading.current_thread() is main))

    page.run_async(work, "probe", done)
    page.run_async(_fail, "broken probe")
    assert pool.waitForDone(int(WAIT * 1000))
    assert seen == [("work", False)]
    assert page.status_text() == ""
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline and (len(seen) < 2 or not page.status_text()):
        qt_app.processEvents()
    assert seen == [("work", False), ("done 42", True)]
    assert page.status_text() == "broken probe failed: it broke"
    page.shutdown()


def test_a_refilled_table_keeps_the_selected_entry_not_the_selected_row(qt_app) -> None:
    from automation_file.ui.pages.base import fill_table, make_table, selected_cell

    assert qt_app is not None
    table = make_table(("Name", "Value"))
    fill_table(table, [["a", 1], ["b", 2], ["c", 3]])
    assert selected_cell(table) is None
    table.selectRow(1)
    assert (selected_cell(table), selected_cell(table, 1)) == ("b", "2")
    fill_table(table, [["new", 0], ["a", 1], ["b", 2]])
    assert (table.currentRow(), selected_cell(table)) == (2, "b")
    fill_table(table, [["new", 0], ["a", 1]])
    assert (table.currentRow(), selected_cell(table)) == (-1, None)
    table.selectRow(0)
    fill_table(table, [["new", 0]], keep_selection=False)
    assert selected_cell(table) is None
    table.deleteLater()


_PAGE_MODULES = sorted(
    path
    for path in (Path(__file__).resolve().parents[1] / "automation_file" / "ui" / "pages").glob(
        "*.py"
    )
    if path.name != "advanced_page.py"
)
_ALLOWED_FIRST_PARTY = (
    "automation_file.app",
    "automation_file.exceptions",
    "automation_file.logging_config",
    "automation_file.ui.log_widget",
    "automation_file.ui.worker",
    "automation_file.ui.pages",
)


@pytest.mark.parametrize("path", _PAGE_MODULES, ids=lambda path: path.name)
def test_a_workflow_page_imports_nothing_below_the_application_layer(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("automation_file")
    ]
    imported.extend(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.startswith("automation_file")
    )
    assert len(_PAGE_MODULES) >= 14
    outside = [
        name
        for name in imported
        if not any(
            name == allowed or name.startswith(f"{allowed}.") for allowed in _ALLOWED_FIRST_PARTY
        )
    ]
    assert outside == []


def test_cell_text_of_the_values_a_table_shows() -> None:
    from automation_file.ui.pages.base import cell_text

    assert cell_text(None) == "—"
    assert cell_text("") == "—"
    assert cell_text(True) == "yes"
    assert cell_text(False) == "no"
    assert cell_text(["a", "b"]) == "a, b"
    assert cell_text([]) == "—"
    assert cell_text(0) == "0"


# ---------------------------------------------------------------------- dashboard


def test_the_dashboard_renders_the_summary_of_its_service(
    services: AppServices, log: Any, bus: EventBus
) -> None:
    page = _page("DashboardPage", services.dashboard, log)
    assert page.summary() is None
    page.refresh()
    summary = page.summary()
    assert summary is not None
    assert summary.status == "ok"
    assert page._headline.text() == "All clear"
    assert page._health_labels["registry_size"].text() == "2"
    assert page._health_labels["audit"].text() == "not configured"
    assert _column(page._storage_table, 0) == [ROOT, "box"]
    assert page._events_table.rowCount() == 0

    draft = services.pipelines.new_draft("dash")
    draft.add_task("T_fail", "only")
    run_id = services.pipelines.start(draft)["run_id"]
    assert services.pipelines.wait(run_id, WAIT)
    bus.publish(SystemErrorEvent(source="test", subject="disk full", payload={"token": "abc"}))  # nosec B105  # a made-up value for a stand-in, not a credential
    page.refresh()
    assert page._headline.text() == "Needs attention"
    assert "1 of the last 1 pipeline runs failed" in page._reasons.text()
    assert _column(page._recent_table, 2) == ["failed"]
    assert _column(page._recent_table, 0) == [run_id[:8]]
    assert "disk full" in _column(page._events_table, 4)
    assert page._run_counts.text() == "0 running, 0 succeeded, 1 failed, 0 cancelled"
    page.shutdown()


def test_the_dashboard_timer_refreshes_only_a_visible_page_with_auto_refresh_on(
    services: AppServices, log: Any
) -> None:
    pool = SyncPool()
    page = _page("DashboardPage", services.dashboard, log, pool)
    page._on_tick()
    assert pool.started == 0
    page.show()
    page._on_tick()
    assert pool.started == 1
    page._auto.setChecked(False)
    page._on_tick()
    assert pool.started == 1
    page.hide()
    page.shutdown()
    assert page._timer.isActive() is False


# ---------------------------------------------------------------------- files


def test_the_files_page_lists_previews_and_navigates(
    services: AppServices, log: Any, resolver: StorageResolver
) -> None:
    File(f"{ROOT}/dir/a.txt", resolver=resolver).write("alpha")
    File(f"{ROOT}/b.txt", resolver=resolver).write("bravo")
    page = _page("FilesPage", services.files, log)
    page.open_location(ROOT)
    assert page.location() == ROOT
    assert [entry.name for entry in page.entries()] == ["dir", "b.txt"]
    assert _column(page._table, 1) == ["directory", "file"]
    assert page.status_text() == f"2 entries in {ROOT}"

    assert page.select_entry("b.txt") is True
    page.preview_selected()
    assert page.preview_text() == "bravo"
    assert "5 of 5 bytes" in page.status_text()

    assert page.select_entry("dir") is True
    page.preview_selected()
    assert "is a directory" in page.status_text()
    page.open_selected()
    assert page.location() == f"{ROOT}/dir"
    assert [entry.name for entry in page.entries()] == ["a.txt"]
    page.select_entry("a.txt")
    page.open_selected()
    assert page.preview_text() == "alpha"
    page.go_up()
    assert page.location() == ROOT
    assert page.select_entry("missing") is False


def test_the_files_page_copies_moves_creates_and_deletes(
    services: AppServices, log: Any, resolver: StorageResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    File(f"{ROOT}/a.txt", resolver=resolver).write("alpha")
    page = _page("FilesPage", services.files, log)
    page.open_location(ROOT)

    page._folder.setText("inbox")
    page.create_directory()
    assert page.status_text() == f"created {ROOT}/inbox"
    assert [entry.name for entry in page.entries()] == ["inbox", "a.txt"]

    page.select_entry("a.txt")
    page._target.setText(f"{ROOT}/inbox")
    page.copy_selected()
    assert page.status_text() == f"copy: {ROOT}/a.txt -> {ROOT}/inbox/a.txt"
    page.select_entry("a.txt")
    page._target.setText(f"{ROOT}/renamed.txt")
    page.move_selected()
    assert [entry.name for entry in page.entries()] == ["inbox", "renamed.txt"]

    answers = iter([False, True, True])
    monkeypatch.setattr(page, "confirm", lambda _question: next(answers))
    page.select_entry("renamed.txt")
    page.delete_selected()
    assert [entry.name for entry in page.entries()] == ["inbox", "renamed.txt"]
    page.delete_selected()
    assert [entry.name for entry in page.entries()] == ["inbox"]
    page.select_entry("inbox")
    page.delete_selected()
    assert "delete" in page.status_text() and "failed" in page.status_text()
    page._recursive.setChecked(True)
    monkeypatch.setattr(page, "confirm", lambda _question: True)
    page.select_entry("inbox")
    page.delete_selected()
    assert page.entries() == []


def test_the_files_page_says_what_is_missing(services: AppServices, log: Any) -> None:
    page = _page("FilesPage", services.files, log)
    page.open_location()
    assert "enter a storage URI" in page.status_text()
    page.copy_selected()
    assert "select an entry" in page.status_text()
    page.create_directory()
    assert "open a location" in page.status_text()
    page.delete_selected()
    assert "select an entry to delete" in page.status_text()
    page.preview_selected()
    assert "select a file to preview" in page.status_text()
    page.refresh()
    page.go_up()
    page.open_location("memory://pages/../escape")
    assert "failed" in page.status_text()
    assert page.location() == ""


# ---------------------------------------------------------------------- storage


def test_the_storage_page_shows_backends_and_mounts_a_directory(
    services: AppServices, log: Any, tmp_path: Path
) -> None:
    page = _page("StoragePage", services.storage, log)
    page.refresh()
    assert [status.name for status in page.backends()] == [ROOT, "box"]
    _select(page._table, ROOT)
    assert "directories: yes" in page._capabilities.text()
    _select(page._table, "box")
    assert "depends on" in page._capabilities.text()

    page.mount_local()
    assert "enter the URI" in page.status_text()
    page._mount_uri.setText("sandbox://jobs")
    page._mount_root.setText(str(tmp_path))
    page.mount_local()
    assert page.status_text() == f"mounted sandbox://jobs on {tmp_path}"
    assert "sandbox://jobs" in _column(page._table, 0)

    page.unmount_selected()
    assert "select a mount" in page.status_text()
    _select(page._table, "sandbox://jobs")
    page.unmount_selected()
    assert page.status_text() == "unmounted sandbox://jobs"
    assert "sandbox://jobs" not in _column(page._table, 0)

    page._mount_root.setText(str(tmp_path / "missing"))
    page.mount_local()
    assert "not a directory" in page.status_text()


def test_the_storage_page_lists_the_default_backends_with_their_detail(log: Any) -> None:
    page = _page("StoragePage", build_services().storage, log)
    page.refresh()
    names = _column(page._table, 0)
    assert {"local", "memory", "s3", "box"} <= set(names)
    assert _column(page._table, 5)[names.index("local")] == "yes"
    _select(page._table, "local")
    assert page._capabilities.text().startswith("local provides")


# ---------------------------------------------------------------------- scheduler


def test_the_scheduler_page_adds_lists_and_removes_jobs(services: AppServices, log: Any) -> None:
    page = _page("SchedulerPage", services.scheduler, log)
    page.add_job()
    assert "add job" in page.status_text() and "failed" in page.status_text()
    page._name.setText("nightly")
    page._cron.setText(NEVER)
    page._actions.setPlainText('[["FA_storage_schemes"]]')
    page.add_job()
    assert page.status_text() == f"added job nightly ({NEVER})"
    assert [job["name"] for job in page.jobs()] == ["nightly"]
    assert _column(page._table, 1) == [NEVER]

    page._name.setText("second")
    page._actions.setPlainText("[[oops")
    page.add_job()
    assert "not valid JSON" in page.status_text()
    page._actions.setPlainText('[["FA_storage_schemes"]]')
    page.add_job()
    page.remove_selected()
    assert "select a job" in page.status_text()
    _select(page._table, "nightly")
    page.remove_selected()
    assert page.status_text() == "removed job nightly"
    assert _column(page._table, 0) == ["second"]
    page.remove_all()
    assert page.status_text() == "removed 1 job(s)"
    assert page.jobs() == []


def test_closing_the_scheduler_page_removes_the_jobs(services: AppServices, log: Any) -> None:
    page = _page("SchedulerPage", services.scheduler, log)
    services.scheduler.add("left-over", NEVER, [["FA_storage_schemes"]])
    page.shutdown()
    assert schedule_list() == []


# ---------------------------------------------------------------------- integrity


def test_the_integrity_page_baselines_verifies_and_accepts(
    services: AppServices, log: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    File(f"{TREE}/a.txt").write(b"alpha")
    page = _page("IntegrityPage", services.integrity, log)
    page.verify()
    assert "the target is required" in page.status_text()
    page.set_location(TREE, BASELINE)
    page.create_baseline()
    assert page.status_text() == f"baseline of 1 file(s) stored at {BASELINE}"
    page.verify()
    assert "no drift" in page.status_text()
    assert page.last_report()["ok"] is True

    File(f"{TREE}/a.txt").write(b"changed")
    File(f"{TREE}/new.txt").write(b"new")
    page.verify()
    assert "drift: 1 created, 1 modified" in page.status_text()
    assert sorted(_column(page._changes, 0)) == ["created", "modified"]
    assert sorted(_column(page._changes, 1)) == ["a.txt", "new.txt"]

    monkeypatch.setattr(page, "confirm", lambda _question: False)
    page.accept()
    page.verify()
    assert page.last_report()["ok"] is False
    monkeypatch.setattr(page, "confirm", lambda _question: True)
    page.accept()
    assert page.status_text() == f"accepted 2 file(s) as the baseline at {BASELINE}"
    page.verify()
    assert page.last_report()["ok"] is True


def test_the_integrity_page_starts_and_stops_a_monitor(services: AppServices, log: Any) -> None:
    File(f"{TREE}/a.txt").write(b"alpha")
    page = _page("IntegrityPage", services.integrity, log)
    page.set_location(TREE, BASELINE)
    page._name.setText("watch")
    page._interval.setValue(3600)
    page.start_monitor()
    assert "no baseline" in page.status_text()
    page.create_baseline()
    page.start_monitor()
    assert page.status_text() == f"monitor watch verifies {TREE} every 3600 s"
    assert [monitor.name for monitor in page.monitors()] == ["watch"]
    assert _column(page._monitor_table, 4) == ["not verified yet"]
    page.stop_selected()
    assert "select a monitor" in page.status_text()
    _select(page._monitor_table, "watch")
    page.stop_selected()
    assert page.status_text() == "monitor watch stopped"
    assert page.monitors() == []

    page.start_monitor()
    page.shutdown()
    assert services.integrity.status() == []
    assert "stopped monitor(s) watch" in log.toPlainText()


# ---------------------------------------------------------------------- audit


def test_the_audit_page_configures_searches_and_shows_a_record(
    services: AppServices, log: Any, bus: EventBus, tmp_path: Path
) -> None:
    page = _page("AuditPage", services.audit, log)
    page.refresh()
    assert page._state.text().startswith("Not configured")
    page.search()
    assert "not configured" in page.status_text()
    page.configure()
    assert "enter the path" in page.status_text()

    database = tmp_path / "audit.sqlite"
    page._db_path.setText(str(database))
    page.configure()
    assert page._state.text() == f"recording into {database}"
    bus.publish(
        PipelineFailed(
            source="pipeline",
            subject="nightly failed",
            payload={"pipeline": "nightly", "status": "failed", "password": "hunter2"},  # nosec B105  # a made-up value for a stand-in, not a credential
        )
    )
    bus.publish(SystemErrorEvent(source="system", subject="disk full"))
    page.search()
    assert page.status_text() == "2 record(s) shown"
    assert _column(page._table, 3) == ["system.error", "pipeline.failed"]

    page.set_filter("pipeline", "nightly")
    assert page.filters() == {"pipeline": "nightly"}
    page.search()
    assert _column(page._table, 3) == ["pipeline.failed"]
    page._table.selectRow(0)
    detail = json.loads(page.detail_text())
    assert detail["metadata"]["password"] == MASK
    assert "hunter2" not in page.detail_text()
    page.count()
    assert page.status_text() == "1 record(s) match"
    page.clear_filters()
    assert page.filters() == {}
    page.set_filter("since", "yesterday")
    page.search()
    assert "search failed" in page.status_text()
    assert [record["action"] for record in page.records()] == ["pipeline.failed"]


def test_the_audit_page_shows_a_store_that_was_configured_in_code(
    services: AppServices, log: Any
) -> None:
    services.audit.configure(MemoryAuditStore())
    page = _page("AuditPage", services.audit, log)
    page.refresh()
    assert page._state.text() == "recording into MemoryAuditStore"


# ---------------------------------------------------------------------- notifications


def test_the_notifications_page_shows_sinks_and_edits_routes(
    services: AppServices, log: Any, manager: NotificationManager, bus: EventBus
) -> None:
    recorder = _Recorder("team")
    manager.register(recorder)
    page = _page("NotificationsPage", services.notifications, log)
    page.refresh()
    assert [sink["name"] for sink in page.sinks()] == ["team"]
    assert _column(page._sink_table, 1) == ["_Recorder"]
    assert "not running" in page._router_state.text()
    assert [page._test_sink.itemText(i) for i in range(page._test_sink.count())] == [
        "All sinks",
        "team",
    ]

    page.add_route()
    assert "add route" in page.status_text() and "failed" in page.status_text()
    page._name.setText("failures")
    page._route_sinks.setText("team")
    page._types.setText("pipeline.failed, task.failed")
    page._severity.setCurrentText("error")
    page._dedup.setText("0")
    assert page.route_options()["types"] == "pipeline.failed, task.failed"
    page.add_route()
    assert page.status_text() == "route failures added"
    assert [route["name"] for route in page.routes()] == ["failures"]
    assert _column(page._route_table, 2) == ["pipeline.failed, task.failed"]
    assert _column(page._route_table, 6) == ["unlimited"]
    assert "delivering" in page._router_state.text()
    bus.publish(PipelineFailed(source="pipeline", subject="nightly failed"))
    assert len(recorder.sent) == 1

    page._route_sinks.setText("tema")
    page.add_route()
    assert "unknown sink" in page.status_text()
    page.remove_selected()
    assert "select a route" in page.status_text()
    _select(page._route_table, "failures")
    page.remove_selected()
    assert page.status_text() == "route failures removed"
    assert page.routes() == []


def test_the_notifications_page_sends_a_test_message(
    services: AppServices, log: Any, manager: NotificationManager
) -> None:
    page = _page("NotificationsPage", services.notifications, log)
    page.refresh()
    page.send_test()
    assert "nothing to test" in page.status_text()
    recorder = _Recorder("team")
    manager.register(recorder)
    manager.register(_Broken())
    page.refresh()
    page._test_sink.setCurrentText("team")
    page._test_subject.setText("hello")
    page.send_test()
    assert page.status_text() == "test message: team: sent"
    assert recorder.sent[0][0] == "hello"
    page._test_sink.setCurrentText("All sinks")
    page._test_subject.clear()
    page.send_test()
    assert "team: sent" in page.status_text()
    assert "broken: NotificationException" in page.status_text()
    assert "s3cr3t" not in page.status_text()
    assert "s3cr3t" not in log.toPlainText()
    assert recorder.sent[1][0] == "automation_file: test notification"


# ---------------------------------------------------------------------- settings


def test_the_settings_page_previews_and_applies_a_configuration(
    services: AppServices,
    log: Any,
    manager: NotificationManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FA_PAGES_TEST_SMTP", "hunter2")
    config = tmp_path / "automation_file.toml"
    config.write_text(
        '[[notify.sinks]]\ntype = "email"\nname = "ops-mail"\nhost = "smtp.example.com"\n'
        'port = 587\nsender = "bot@example.com"\nrecipients = ["ops@example.com"]\n'
        'password = "${env:FA_PAGES_TEST_SMTP}"\n',
        encoding="utf-8",
    )
    page = _page("SettingsPage", services.settings, log)
    page.preview()
    assert "enter the path" in page.status_text()
    page.set_path(str(config))
    page.preview()
    assert "declares 1 sink(s) and 0 route(s); nothing was changed" in page.status_text()
    assert page.summary()["applied"] is False
    assert MASK in page.document_text()
    assert "hunter2" not in page.document_text()
    assert manager.names() == ()

    page.apply()
    assert page.status_text() == f"applied {config}: 1 sink(s), 0 route(s)"
    assert manager.names() == ("ops-mail",)
    assert page._environment_labels["applied_config"].text() == str(config)
    assert "hunter2" not in page.document_text()

    page.set_path(str(tmp_path / "missing.toml"))
    page.apply()
    assert "not found" in page.status_text()


def test_the_settings_page_lists_the_extras_and_the_environment(
    services: AppServices, log: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from automation_file.app import settings_service
    from automation_file.core.optional import EXTRAS, install_hint

    monkeypatch.setattr(settings_service, "is_installed", lambda module: module != "boto3")
    page = _page("SettingsPage", services.settings, log)
    page.refresh()
    assert [extra.name for extra in page.extras()] == list(EXTRAS)
    assert _column(page._extras_table, 0) == list(EXTRAS)
    row = list(EXTRAS).index("s3")
    assert _column(page._extras_table, 2)[row] == "no (boto3 missing)"
    assert _column(page._extras_table, 3)[row] == install_hint("s3")
    assert _column(page._extras_table, 2)[list(EXTRAS).index("ftp")] == "yes"
    assert page._environment_labels["python"].text().count(".") == 2
    assert page._environment_labels["applied_config"].text() == "none"
