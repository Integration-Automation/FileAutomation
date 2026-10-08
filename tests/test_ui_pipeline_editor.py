"""The pipeline editor: canvas, task form and page, as thin views over a draft."""

from __future__ import annotations

import itertools
import json
import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from automation_file.app import (
    PipelineDraft,
    PipelineService,
    layout_path,
)
from automation_file.core.action_registry import ActionRegistry
from automation_file.events import EventBus
from automation_file.pipeline import MemoryRunStore, Pipeline
from tests.ui_stand_in import SyncPool

WAIT = 10.0


class _Workshop:
    """The actions the pipelines of these tests call."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.entered = threading.Event()
        self.broken = True
        self.calls: list[str] = []

    def echo(self, value: Any = None, times: int = 1) -> Any:
        self.calls.append(f"echo:{value!r}")
        return value

    def fail(self) -> None:
        raise ValueError("it broke")

    def flaky(self) -> str:
        if self.broken:
            raise ConnectionError("not yet")
        return "repaired"

    def hold(self) -> str:
        self.entered.set()
        self.gate.wait(WAIT)
        return "released"

    def positional(self, *values: Any) -> list[Any]:
        return list(values)

    def registry(self) -> ActionRegistry:
        return ActionRegistry(
            {
                "T_echo": self.echo,
                "T_fail": self.fail,
                "T_flaky": self.flaky,
                "T_hold": self.hold,
                "T_positional": self.positional,
            }
        )


@pytest.fixture(name="qt_app", scope="module")
def _qt_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(name="workshop")
def _workshop() -> Iterator[_Workshop]:
    workshop = _Workshop()
    yield workshop
    workshop.gate.set()


@pytest.fixture(name="service")
def _service(workshop: _Workshop) -> PipelineService:
    return PipelineService(MemoryRunStore(), registry=workshop.registry(), bus=EventBus())


@pytest.fixture(name="page")
def _page(
    qt_app, service: PipelineService, workshop: _Workshop, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Any]:
    from automation_file.ui.log_widget import LogPanel
    from automation_file.ui.pages import PipelinesPage

    assert qt_app is not None
    log = LogPanel()
    page = PipelinesPage(service, log, SyncPool())
    monkeypatch.setattr(page, "confirm", lambda _question: True)
    page.refresh()
    yield page
    # Let a run that is still held finish before the test ends, so its thread logs nothing later.
    workshop.gate.set()
    if page.current_run() is not None:
        service.wait(page.current_run(), WAIT)
    page.shutdown()
    page.deleteLater()
    log.deleteLater()


def _chain(page: Any, *actions: str) -> list[str]:
    """Add one task per action and connect each to the one before it."""
    ids = [page.add_task(action) for action in actions]
    for upstream, downstream in itertools.pairwise(ids):
        page.canvas().select_tasks([upstream, downstream])
        page.connect_selected()
    return ids


def _finish(page: Any, service: PipelineService) -> None:
    assert service.wait(page.current_run(), WAIT) is True
    page.poll()


# ---------------------------------------------------------------------- canvas


def test_the_canvas_shows_the_tasks_and_edges_of_the_draft(qt_app) -> None:
    from automation_file.ui.pages import EdgeItem, PipelineCanvas, TaskNode

    assert qt_app is not None
    draft = PipelineDraft("p")
    draft.add_task("T_echo", "a", position=(10, 20))
    draft.add_task("T_echo", "b", position=(300, 40))
    draft.connect("a", "b")
    canvas = PipelineCanvas()
    canvas.set_draft(draft)
    assert canvas.node_ids() == ["a", "b"]
    assert canvas.edge_pairs() == [("a", "b")]
    node = canvas.node("a")
    assert isinstance(node, TaskNode)
    assert (node.pos().x(), node.pos().y(), node.action) == (10.0, 20.0, "T_echo")
    kinds = [type(item) for item in canvas.scene().items()]
    assert kinds.count(TaskNode) == 2
    assert kinds.count(EdgeItem) == 1

    draft.add_task("T_fail", "c")
    draft.connect("b", "c")
    assert canvas.node_ids() == ["a", "b", "c"]
    assert canvas.edge_pairs() == [("a", "b"), ("b", "c")]
    draft.rename_task("c", "last")
    draft.remove_task("a")
    assert canvas.node_ids() == ["b", "last"]
    assert canvas.edge_pairs() == [("b", "last")]
    canvas.set_draft(None)
    assert canvas.node_ids() == []
    draft.add_task("T_echo", "ignored")
    assert canvas.node_ids() == []


def test_dragging_a_node_writes_its_position_to_the_draft_and_moves_its_arrows(qt_app) -> None:
    from automation_file.ui.pages import PipelineCanvas

    assert qt_app is not None
    draft = PipelineDraft("p")
    draft.add_task("T_echo", "a", position=(0, 0))
    draft.add_task("T_echo", "b", position=(300, 0))
    draft.connect("a", "b")
    canvas = PipelineCanvas()
    canvas.set_draft(draft)
    edge = next(item for item in canvas.scene().items() if hasattr(item, "upstream_id"))
    before = edge.path().boundingRect()
    revision = draft.revision
    canvas.node("b").setPos(420.0, 180.0)
    assert draft.positions()["b"] == (420.0, 180.0)
    assert draft.revision == revision + 1
    assert canvas.node_ids() == ["a", "b"]
    assert edge.path().boundingRect() != before
    assert "420" not in json.dumps(draft.to_definition())


def test_a_real_mouse_drag_moves_the_node(qt_app) -> None:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from automation_file.ui.pages import PipelineCanvas

    draft = PipelineDraft("p")
    draft.add_task("T_echo", "a", position=(50, 50))
    canvas = PipelineCanvas()
    canvas.resize(600, 400)
    canvas.set_draft(draft)
    canvas.show()
    qt_app.processEvents()
    start = canvas.mapFromScene(QPointF(60.0, 60.0))
    end = start + QPoint(120, 70)
    viewport = canvas.viewport()

    def send(kind: QEvent.Type, point: QPoint, button: Any, buttons: Any) -> None:
        event = QMouseEvent(
            kind,
            QPointF(point),
            QPointF(viewport.mapToGlobal(point)),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        qt_app.sendEvent(viewport, event)

    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    send(QEvent.Type.MouseButtonPress, start, left, left)
    send(QEvent.Type.MouseMove, start + QPoint(60, 35), none, left)
    send(QEvent.Type.MouseMove, end, none, left)
    send(QEvent.Type.MouseButtonRelease, end, left, none)
    canvas.hide()
    x, y = draft.positions()["a"]
    assert (round(x), round(y)) == (170, 120)
    assert canvas.selected_tasks() == ["a"]


def test_positions_set_on_the_draft_move_the_nodes(qt_app) -> None:
    from automation_file.ui.pages import PipelineCanvas

    assert qt_app is not None
    draft = PipelineDraft("p")
    draft.add_task("T_echo", "a", position=(500, 500))
    draft.add_task("T_echo", "b", position=(700, 700))
    draft.connect("a", "b")
    canvas = PipelineCanvas()
    canvas.set_draft(draft)
    node_a, node_b = canvas.node("a"), canvas.node("b")
    draft.auto_layout()
    assert canvas.node("a") is node_a
    assert (node_a.pos().x(), node_a.pos().y()) == (40.0, 40.0)
    assert (node_b.pos().x(), node_b.pos().y()) == (280.0, 40.0)
    draft.set_position("a", 5, 6)
    assert (node_a.pos().x(), node_a.pos().y()) == (5.0, 6.0)


def test_the_selection_keeps_the_order_in_which_tasks_were_selected(qt_app) -> None:
    from automation_file.ui.pages import PipelineCanvas

    assert qt_app is not None
    draft = PipelineDraft("p")
    for task_id in ("a", "b", "c"):
        draft.add_task("T_echo", task_id)
    canvas = PipelineCanvas()
    canvas.set_draft(draft)
    heard: list[list[str]] = []
    canvas.selection_changed.connect(heard.append)
    canvas.node("c").setSelected(True)
    canvas.node("a").setSelected(True)
    assert canvas.selected_tasks() == ["c", "a"]
    assert heard[-1] == ["c", "a"]
    canvas.node("c").setSelected(False)
    canvas.node("b").setSelected(True)
    assert canvas.selected_tasks() == ["a", "b"]
    canvas.select_tasks(["b", "c", "missing"])
    assert canvas.selected_tasks() == ["b", "c"]
    draft.set_action("a", "T_fail")
    assert canvas.selected_tasks() == ["b", "c"]
    assert canvas.node("b").isSelected() is True
    draft.remove_task("b")
    assert canvas.selected_tasks() == ["c"]


def test_an_arrow_can_be_selected(qt_app) -> None:
    from automation_file.ui.pages import PipelineCanvas

    assert qt_app is not None
    draft = PipelineDraft("p")
    draft.add_task("T_echo", "a")
    draft.add_task("T_echo", "b", position=(300, 0))
    draft.connect("a", "b")
    canvas = PipelineCanvas()
    canvas.set_draft(draft)
    assert canvas.selected_edges() == []
    assert canvas.select_edge("a", "b") is True
    assert canvas.selected_edges() == [("a", "b")]
    assert canvas.selected_tasks() == []
    assert canvas.select_edge("b", "a") is False


def test_statuses_colour_the_nodes_and_the_scene_paints(qt_app) -> None:
    from PySide6.QtGui import QColor, QImage, QPainter

    from automation_file.ui.pages import PipelineCanvas
    from automation_file.ui.pages.pipeline_canvas import STATUS_COLOURS

    assert qt_app is not None
    draft = PipelineDraft("p")
    draft.add_task("T_echo", "a", position=(0, 0))
    draft.add_task("", "b", position=(300, 0))
    draft.connect("a", "b")
    canvas = PipelineCanvas()
    canvas.set_draft(draft)
    canvas.set_statuses({"a": "succeeded", "b": "failed"})
    assert (canvas.node("a").status, canvas.node("b").status) == ("succeeded", "failed")
    canvas.node("a").setSelected(True)
    canvas.select_edge("a", "b")
    image = QImage(600, 200, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    canvas.scene().render(painter)
    painter.end()
    colours = {image.pixelColor(x, y).name() for x in range(0, 600, 4) for y in range(0, 200, 4)}
    assert STATUS_COLOURS["succeeded"] in colours
    assert STATUS_COLOURS["failed"] in colours
    draft.add_task("T_echo", "c")
    assert canvas.node("a").status == "succeeded"
    canvas.set_statuses({})
    assert canvas.node("a").status == ""


def test_the_palette_filters_and_offers_an_action_for_dragging(qt_app) -> None:
    from automation_file.ui.pages import ACTION_MIME, ActionPalette

    assert qt_app is not None
    palette = ActionPalette()
    palette.set_actions(["FA_storage_copy", "FA_storage_delete", "FA_zip_dir"])
    palette.filter_actions("STORAGE")
    assert [palette.item(row).isHidden() for row in range(3)] == [False, False, True]
    palette.setCurrentRow(1)
    assert palette.selected_action() == "FA_storage_delete"
    palette.filter_actions("zip")
    assert palette.selected_action() == ""
    palette.filter_actions("")
    data = palette.mimeData([palette.item(2)])
    assert bytes(data.data(ACTION_MIME).data()).decode("utf-8") == "FA_zip_dir"
    assert data.text() == "FA_zip_dir"
    assert palette.mimeData([]).hasFormat(ACTION_MIME) is False


def test_dropping_an_action_on_the_canvas_adds_a_task_where_it_was_dropped(page: Any) -> None:
    from PySide6.QtCore import QMimeData, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    from automation_file.ui.pages import ACTION_MIME
    from automation_file.ui.pages.pipeline_canvas import NODE_HEIGHT, NODE_WIDTH

    canvas = page.canvas()
    canvas.resize(600, 400)
    data = QMimeData()
    data.setData(ACTION_MIME, b"T_echo")
    point = QPointF(200.0, 150.0)
    event = QDropEvent(
        point,
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.dropEvent(event)
    assert page.draft().task_ids() == ("T_echo",)
    scene_point = canvas.mapToScene(point.toPoint())
    x, y = page.draft().positions()["T_echo"]
    assert (x, y) == (scene_point.x() - NODE_WIDTH / 2, scene_point.y() - NODE_HEIGHT / 2)
    assert canvas.selected_tasks() == ["T_echo"]

    other = QMimeData()
    other.setText("not an action")
    canvas.dropEvent(
        QDropEvent(
            point,
            Qt.DropAction.CopyAction,
            other,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert page.draft().task_ids() == ("T_echo",)


# ---------------------------------------------------------------------- tasks and edges on the page


def test_the_palette_lists_the_registered_actions(page: Any) -> None:
    palette = page.action_palette()
    assert [palette.item(row).text() for row in range(palette.count())] == [
        "T_echo",
        "T_fail",
        "T_flaky",
        "T_hold",
        "T_positional",
    ]
    page._filter.setText("fl")
    assert [palette.item(row).isHidden() for row in range(palette.count())] == [
        True,
        True,
        False,
        True,
        True,
    ]


def test_adding_a_task_uses_the_selected_action_and_selects_the_new_node(page: Any) -> None:
    page.action_palette().setCurrentRow(1)
    first = page.add_task()
    assert first == "T_fail"
    assert page.draft().task("T_fail").action == "T_fail"
    assert page.canvas().selected_tasks() == ["T_fail"]
    assert page.form().current_task() == "T_fail"
    page.action_palette().itemDoubleClicked.emit(page.action_palette().item(0))
    assert page.draft().task_ids() == ("T_fail", "T_echo")
    assert page.status_text() == "added task T_echo"


def test_two_selected_tasks_are_connected_in_the_order_they_were_selected(page: Any) -> None:
    first, second = page.add_task("T_echo"), page.add_task("T_echo")
    assert page._connect_button.text() == "Connect (select two tasks)"
    page.connect_selected()
    assert "select exactly two tasks" in page.status_text()
    page.canvas().select_tasks([second, first])
    assert page._connect_button.text() == f"Connect {second} -> {first}"
    page.connect_selected()
    assert page.draft().edges() == [(second, first)]
    assert page.canvas().edge_pairs() == [(second, first)]
    assert page.status_text() == f"{first} now depends on {second}"
    page.connect_selected()
    assert page.status_text() == f"{first} already depends on {second}"
    page.canvas().select_tasks([first, second])
    page.connect_selected()
    assert "dependency cycle" in page.status_text()
    assert page.draft().edges() == [(second, first)]


def test_disconnecting_by_arrow_and_by_two_tasks(page: Any) -> None:
    a, b, c = _chain(page, "T_echo", "T_echo", "T_echo")
    assert page.draft().edges() == [(a, b), (b, c)]
    page.canvas().select_tasks([])
    page.disconnect_selected()
    assert "select an arrow" in page.status_text()
    page.canvas().select_edge(a, b)
    page.disconnect_selected()
    assert page.draft().edges() == [(b, c)]
    assert page.status_text() == f"removed {a} -> {b}"
    page.canvas().select_tasks([c, b])
    page.disconnect_selected()
    assert page.draft().edges() == []


def test_remove_takes_the_selected_arrows_first_and_tasks_otherwise(page: Any) -> None:
    a, b, c = _chain(page, "T_echo", "T_echo", "T_echo")
    page.canvas().select_tasks([])
    page.remove_selected()
    assert "select a task or an arrow" in page.status_text()
    page.canvas().select_edge(b, c)
    page.remove_selected()
    assert page.draft().task_ids() == (a, b, c)
    assert page.draft().edges() == [(a, b)]
    page.canvas().select_tasks([a, c])
    page.remove_selected()
    assert page.draft().task_ids() == (b,)
    assert page.canvas().node_ids() == [b]
    assert page.form().current_task() is None


def test_auto_layout_arranges_the_nodes_by_dependency_depth(page: Any) -> None:
    a, b = _chain(page, "T_echo", "T_echo")
    page.canvas().node(b).setPos(900.0, 900.0)
    page.auto_layout()
    assert page.draft().positions() == {a: (40.0, 40.0), b: (280.0, 40.0)}
    assert page.canvas().node(b).pos().x() == 280.0


# ---------------------------------------------------------------------- the task form


def test_the_form_shows_the_selected_task_and_its_parameters(page: Any) -> None:
    form = page.form()
    assert form.isEnabled() is False
    task_id = page.add_task("T_echo")
    assert form.isEnabled() is True
    assert form._task_id.text() == task_id
    assert form._action.currentText() == "T_echo"
    assert form._signature.text().startswith("T_echo(value=None, times=1)")
    editor = form.arguments_editor()
    assert editor.row_names() == ["value", "times"]
    assert editor._table.item(0, 2).text() == "null"
    assert editor._table.item(1, 2).text() == "1"
    page.canvas().select_tasks([])
    assert form.isEnabled() is False
    assert form.current_task() is None
    assert "Select a task" in form.message()


def test_applying_the_form_writes_every_field_through_the_draft(page: Any) -> None:
    first, second = page.add_task("T_echo"), page.add_task("T_echo")
    form = page.form()
    assert form.current_task() == second
    editor = form.arguments_editor()
    editor.set_value("value", "${tasks." + first + ".result}")
    editor.set_value("times", "3")
    editor.add_row("extra", '{"deep": [1, 2]}')
    assert form.set_dependency(first, True) is True
    assert form.set_dependency("missing", True) is False
    form.set_retry(4, 1.5)
    form.set_field("retry_on", "ConnectionError, TimeoutError")
    form.set_field("timeout", "30")
    form.set_condition("always")
    form.set_field("key", "copy-${params.date}")
    assert form.apply() is True
    assert page.draft().task(second).to_spec() == {
        "action": [
            "T_echo",
            {"value": "${tasks." + first + ".result}", "times": 3, "extra": {"deep": [1, 2]}},
        ],
        "depends_on": [first],
        "retry": {"max_attempts": 4, "backoff": 1.5, "on": ["ConnectionError", "TimeoutError"]},
        "timeout": 30.0,
        "when": "always",
        "idempotency_key": "copy-${params.date}",
    }
    assert page.canvas().edge_pairs() == [(first, second)]
    assert form.checked_dependencies() == [first]
    assert page.status_text() == f"task {second} updated"
    assert editor.row_names() == ["value", "times", "extra"]


def test_renaming_through_the_form_keeps_the_task_selected(page: Any) -> None:
    first, second = _chain(page, "T_echo", "T_echo")
    page.canvas().select_tasks([first])
    form = page.form()
    form.set_field("task_id", "download")
    assert form.apply() is True
    assert page.draft().task_ids() == ("download", second)
    assert page.draft().edges() == [("download", second)]
    assert page.canvas().selected_tasks() == ["download"]
    assert form.current_task() == "download"
    form.set_field("task_id", second)
    assert form.apply() is False
    assert "already has a task" in form.message()
    assert form.current_task() == "download"
    assert form._task_id.text() == second
    form.revert()
    assert form._task_id.text() == "download"


def test_what_was_typed_survives_an_arrow_drawn_on_the_canvas(page: Any) -> None:
    first, second = page.add_task("T_echo"), page.add_task("T_echo")
    page.canvas().select_tasks([first, second])
    form = page.form()
    assert form.current_task() == second
    form.arguments_editor().set_value("value", "typed")
    form.set_field("timeout", "12")
    assert form.checked_dependencies() == []
    page.connect_selected()
    assert form.current_task() == second
    assert form._timeout.text() == "12"
    assert form.arguments_editor().arguments() == {"value": "typed"}
    assert form.checked_dependencies() == [first]
    assert form.apply() is True
    assert page.draft().edges() == [(first, second)]
    assert page.draft().task(second).timeout == 12.0
    assert page.draft().task(second).arguments == {"value": "typed"}


def test_a_field_the_draft_refuses_is_reported_and_what_was_typed_stays(page: Any) -> None:
    first, second = _chain(page, "T_echo", "T_echo")
    page.canvas().select_tasks([first])
    form = page.form()
    form.set_field("timeout", "soon")
    assert form.apply() is False
    assert "timeout must be a number" in form.message()
    assert form._timeout.text() == "soon"
    form.set_field("timeout", "")
    form.set_dependency(second, True)
    assert form.apply() is False
    assert "dependency cycle" in form.message()
    assert page.draft().edges() == [(first, second)]
    assert page.canvas().selected_tasks() == [first]


def test_changing_the_action_rebuilds_the_argument_rows_and_keeps_typed_values(page: Any) -> None:
    page.add_task("T_echo")
    form, editor = page.form(), page.form().arguments_editor()
    editor.set_value("value", "kept")
    form.set_action("T_missing")
    assert "not a registered action" in form._signature.text()
    assert editor.row_names() == ["value"]
    assert editor.arguments() == {"value": "kept"}
    form.set_action("T_echo")
    assert editor.row_names() == ["value", "times"]
    assert editor.arguments() == {"value": "kept"}
    form.set_action("")
    assert form._signature.text() == "Choose an action."


def test_positional_arguments_are_edited_as_json(page: Any) -> None:
    task_id = page.add_task("T_positional")
    form, editor = page.form(), page.form().arguments_editor()
    page.draft().set_arguments(task_id, ["a", 2])
    assert editor.is_json_mode() is False
    form.revert()
    assert editor.is_json_mode() is True
    assert json.loads(editor._raw.toPlainText()) == ["a", 2]
    editor.set_json_mode(False)
    assert editor.is_json_mode() is True
    editor.set_json_text('["b", 3, true]')
    assert form.apply() is True
    assert page.draft().task(task_id).arguments == ["b", 3, True]
    editor.set_json_text("[oops")
    assert form.apply() is False
    assert "not valid JSON" in form.message()
    editor.set_json_mode(False)
    assert editor.is_json_mode() is True
    editor.set_json_text('"just text"')
    assert form.apply() is False
    assert "JSON object, a JSON array or empty" in form.message()
    editor.set_json_text("")
    assert form.apply() is True
    assert page.draft().task(task_id).arguments is None


def test_keyword_arguments_move_between_the_table_and_json(page: Any) -> None:
    page.add_task("T_echo")
    editor = page.form().arguments_editor()
    editor.set_value("value", "hello")
    editor.set_json_mode(True)
    assert json.loads(editor._raw.toPlainText()) == {"value": "hello"}
    editor.set_json_text('{"value": "changed", "added": 5}')
    editor.set_json_mode(False)
    assert editor.is_json_mode() is False
    assert editor.row_names() == ["value", "times", "added"]
    assert editor.arguments() == {"value": "changed", "added": 5}


# ---------------------------------------------------------------------- header and files


def test_the_header_fields_are_written_to_the_draft_only_when_they_change(page: Any) -> None:
    draft = page.draft()
    page._name.editingFinished.emit()
    assert draft.dirty is False
    page._name.setText("nightly")
    page._name.editingFinished.emit()
    page._description.setText("Fetch and publish")
    page._description.editingFinished.emit()
    page._max_workers.setValue(2)
    page._defaults.setText('{"date": "2026-10-08"}')
    page._defaults.editingFinished.emit()
    page._cron.setText("0 2 * * *")
    page._cron.editingFinished.emit()
    assert draft.to_definition() == {
        "schema_version": 1,
        "name": "nightly",
        "description": "Fetch and publish",
        "max_workers": 2,
        "schedule": {"cron": "0 2 * * *"},
        "params": {"date": "2026-10-08"},
        "tasks": {},
    }
    assert page._file_label.text() == "not saved yet (modified)"
    page._defaults.setText("{oops")
    page._defaults.editingFinished.emit()
    assert "default parameters is not valid JSON" in page.status_text()
    assert draft.params == {"date": "2026-10-08"}


def test_a_pipeline_is_saved_and_opened_with_its_layout(page: Any, tmp_path: Path) -> None:
    first, second = _chain(page, "T_echo", "T_fail")
    page.canvas().node(second).setPos(432.0, 234.0)
    page._name.setText("saved")
    path = tmp_path / "saved.yaml"
    page.save_pipeline_as(str(path))
    assert page.status_text() == f"saved {path}"
    assert page._file_label.text() == str(path)
    assert Pipeline.from_file(path).name == "saved"
    assert json.loads(layout_path(path).read_text(encoding="utf-8"))["positions"][second] == [
        432.0,
        234.0,
    ]

    page.new_pipeline()
    assert page.draft().tasks == ()
    assert page.canvas().node_ids() == []
    assert page._file_label.text() == "not saved yet"
    page.open_pipeline(str(path))
    assert page.status_text() == f"opened {path}: 2 task(s)"
    assert page.draft().task_ids() == (first, second)
    assert page.canvas().edge_pairs() == [(first, second)]
    assert page.canvas().node(second).pos().x() == 432.0
    assert page._name.text() == "saved"

    page.canvas().node(first).setPos(1.0, 2.0)
    assert page._file_label.text() == f"{path} (modified)"
    page.save_pipeline()
    assert page._file_label.text() == str(path)
    assert json.loads(layout_path(path).read_text(encoding="utf-8"))["positions"][first] == [
        1.0,
        2.0,
    ]
    page.save_pipeline_as(str(tmp_path / "saved.txt"))
    assert "cannot save" in page.status_text()


def test_unsaved_changes_are_kept_when_the_user_says_so(
    page: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page.add_task("T_echo")
    monkeypatch.setattr(page, "confirm", lambda _question: False)
    page.new_pipeline()
    page.open_pipeline(str(tmp_path / "missing.yaml"))
    assert page.draft().task_ids() == ("T_echo",)
    monkeypatch.setattr(page, "confirm", lambda _question: True)
    page.open_pipeline(str(tmp_path / "missing.yaml"))
    assert "open" in page.status_text() and "failed" in page.status_text()
    assert page.draft().task_ids() == ("T_echo",)


def test_a_definition_with_problems_opens_and_lists_them(page: Any, tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "broken",
                "tasks": {"a": {"action": ["T_echo"], "depends_on": ["ghost"]}},
            }
        ),
        encoding="utf-8",
    )
    page.open_pipeline(str(path))
    assert "1 problem(s) to fix" in page.status_text()
    assert page.panel().problem_texts() == ["tasks.a.depends_on[0]: unknown task 'ghost'"]
    assert page.canvas().node_ids() == ["a"]


# ---------------------------------------------------------------------- validate, dry run, test


def test_validate_lists_every_problem_and_a_problem_leads_to_its_task(page: Any) -> None:
    panel = page.panel()
    assert panel.problem_texts() == []
    assert panel.tabText(0) == "Problems"
    assert page.validate() is False
    assert panel.problem_texts() == ["tasks: at least one task is required"]
    good, bad = page.add_task("T_echo"), page.add_task("T_missing")
    page.draft().set_timeout(good, -1)
    assert page.validate() is False
    assert panel.problem_texts() == [
        f"tasks.{good}.timeout: expected a number of seconds > 0, got -1",
        f"tasks.{bad}.action[0]: unknown action 'T_missing'",
    ]
    assert panel.tabText(0) == "Problems (2)"
    assert page.status_text() == "2 problem(s): see the Problems tab"
    page.canvas().select_tasks([])
    panel._problem_list.itemClicked.emit(panel._problem_list.item(1))
    assert page.canvas().selected_tasks() == [bad]
    page.draft().set_timeout(good, None)
    page.draft().set_action(bad, "T_echo")
    assert page.validate() is True
    assert page.status_text() == "the definition is valid"


def test_a_dry_run_shows_the_plan_on_the_canvas_and_in_the_table(
    page: Any, workshop: _Workshop
) -> None:
    first, second = _chain(page, "T_echo", "T_echo")
    page.draft().set_arguments(first, {"value": "${params.word}"})
    page.dry_run()
    assert "unknown parameter 'word'" in page.status_text()
    page.set_run_params('{"word": "hi"}')
    page.dry_run()
    assert page.status_text() == "dry run: 2 task(s) would run as planned"
    assert page.panel().task_rows() == [(first, "planned"), (second, "planned")]
    assert page.panel().run_text() == "dry run: succeeded"
    assert page.canvas().node(first).status == "planned"
    assert workshop.calls == []
    assert page.current_run() is None


def test_the_run_parameters_must_be_a_json_object(page: Any, workshop: _Workshop) -> None:
    page.add_task("T_echo")
    page.set_run_params("{oops")
    page.run()
    assert "run parameters is not valid JSON" in page.status_text()
    page.set_run_params("[1, 2]")
    page.dry_run()
    assert "must be a JSON object" in page.status_text()
    assert workshop.calls == []


def test_nothing_runs_while_the_definition_has_problems(page: Any, workshop: _Workshop) -> None:
    page.add_task("T_missing")
    for attempt in (page.dry_run, page.run, page.test_task):
        attempt()
        assert page.status_text() == "1 problem(s): see the Problems tab"
    assert page.current_run() is None
    assert workshop.calls == []


def test_one_task_is_tested_alone(page: Any, workshop: _Workshop, service: Any) -> None:
    first, second = _chain(page, "T_fail", "T_echo")
    page.canvas().select_tasks([])
    page.test_task()
    assert page.status_text() == "select the task to test"
    page.canvas().select_tasks([second])
    page.draft().set_arguments(second, {"value": "probe"})
    page.test_task()
    assert page.status_text() == f"test of {second} succeeded in 1 attempt(s)"
    assert page.panel().task_rows() == [(second, "succeeded")]
    assert "task.completed" in page.panel().log_text()
    assert workshop.calls == ["echo:'probe'"]
    assert service.history() == []
    page.canvas().select_tasks([first])
    page.test_task()
    assert page.status_text() == f"test of {first}: failed: ValueError: it broke"


# ---------------------------------------------------------------------- runs


def test_a_run_is_followed_until_it_ends(page: Any, workshop: _Workshop, service: Any) -> None:
    first, second = _chain(page, "T_hold", "T_echo")
    page.run()
    run_id = page.current_run()
    assert run_id is not None
    assert page._timer.isActive() is True
    assert workshop.entered.wait(WAIT)
    page.poll()
    assert page.panel().task_rows() == [(first, "running"), (second, "pending")]
    assert page.canvas().node(first).status == "running"
    assert "task.started" in page.panel().log_text()
    workshop.gate.set()
    _finish(page, service)
    assert page.status_text() == f"run {run_id} succeeded"
    assert page.panel().task_rows() == [(first, "succeeded"), (second, "succeeded")]
    assert page.canvas().node(second).status == "succeeded"
    assert "pipeline.completed" in page.panel().log_text()
    assert page._timer.isActive() is False
    assert page.panel().history_ids() == [run_id]


def test_a_failed_run_is_resumed_and_retried(page: Any, workshop: _Workshop, service: Any) -> None:
    first, second = _chain(page, "T_echo", "T_flaky")
    page.resume()
    assert "there is no run to resume" in page.status_text()
    page.run()
    failed = page.current_run()
    _finish(page, service)
    assert page.status_text().startswith(f"run {failed} ended failed")
    assert page.panel().task_rows() == [(first, "succeeded"), (second, "failed")]
    assert page.canvas().node(second).status == "failed"

    workshop.broken = False
    page.resume()
    assert page.current_run() == failed
    _finish(page, service)
    assert page.status_text() == f"run {failed} succeeded"
    assert workshop.calls.count("echo:None") == 1

    page.retry()
    again = page.current_run()
    assert again != failed
    _finish(page, service)
    assert page.status_text() == f"run {again} succeeded"
    assert workshop.calls.count("echo:None") == 2
    assert page.panel().history_ids() == [again, failed]


def test_a_running_run_is_cancelled(page: Any, workshop: _Workshop, service: Any) -> None:
    page.cancel()
    assert page.status_text() == "there is no run to cancel"
    first, second = _chain(page, "T_hold", "T_echo")
    page.run()
    run_id = page.current_run()
    assert workshop.entered.wait(WAIT)
    page.cancel()
    assert page.status_text() == f"cancel requested for run {run_id}"
    workshop.gate.set()
    _finish(page, service)
    assert page.status_text().startswith(f"run {run_id} ended cancelled")
    assert page.panel().task_rows() == [(first, "succeeded"), (second, "cancelled")]
    page.cancel()
    assert "is not running in this process" in page.status_text()


def test_a_run_of_the_history_can_be_followed_again(page: Any, service: Any) -> None:
    _chain(page, "T_echo")
    page.run()
    first_run = page.current_run()
    _finish(page, service)
    page.run()
    second_run = page.current_run()
    _finish(page, service)
    assert page.panel().history_ids() == [second_run, first_run]
    page.follow_selected()
    assert "select a run" in page.status_text()
    assert page.panel().select_run(first_run) is True
    assert page.panel().select_run("unknown") is False
    page.follow_selected()
    assert page.current_run() == first_run
    assert page.panel().run_text() == f"run {first_run}: succeeded"
    page.panel().run_chosen.emit(second_run)
    assert page.current_run() == second_run


def test_following_leaves_the_visible_tab_alone_and_stops_when_the_run_cannot_be_read(
    page: Any, workshop: _Workshop, service: Any
) -> None:
    page.add_task("T_hold")
    page.run()
    panel = page.panel()
    assert panel.tabText(panel.currentIndex()) == "Tasks"
    panel.setCurrentIndex(2)
    assert workshop.entered.wait(WAIT)
    page.poll()
    assert panel.tabText(panel.currentIndex()) == "Log"
    workshop.gate.set()
    _finish(page, service)
    assert panel.tabText(panel.currentIndex()) == "Log"

    page.follow_run("no-such-run")
    assert page.status_text() == "follow run failed: unknown run 'no-such-run'"
    assert page._timer.isActive() is False
    page.poll()
    assert page._timer.isActive() is False


def test_a_new_draft_forgets_the_followed_run(page: Any, service: Any) -> None:
    task_id = page.add_task("T_echo")
    page.run()
    _finish(page, service)
    assert page.canvas().node(task_id).status == "succeeded"
    page.new_pipeline()
    assert page.current_run() is None
    assert page.panel().task_rows() == []
    assert page.panel().log_text() == ""
    page.poll()
    assert page._timer.isActive() is False


def test_shutdown_stops_following_and_lets_go_of_the_draft(
    page: Any, workshop: _Workshop, service: Any
) -> None:
    page.add_task("T_hold")
    page.run()
    assert page._timer.isActive() is True
    draft = page.draft()
    page.shutdown()
    assert page._timer.isActive() is False
    draft.add_task("T_echo", "later")
    assert page.canvas().node_ids() == []
    workshop.gate.set()
    assert service.wait(page.current_run(), WAIT) is True
