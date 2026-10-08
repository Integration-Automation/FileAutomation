"""Pipelines page: the visual editor of a pipeline definition, and its runs.

The page owns one :class:`~automation_file.app.PipelineDraft`. The canvas and
the task form are views over it; every button calls the draft or the Pipelines
service and then shows what they return. Nothing about pipelines is decided
here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from automation_file.app import (
    AppException,
    PipelineDraft,
    PipelineService,
    Problem,
    parse_json_text,
)
from automation_file.exceptions import FileAutomationException
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage
from automation_file.ui.pages.pipeline_canvas import (
    NODE_HEIGHT,
    NODE_WIDTH,
    ActionPalette,
    PipelineCanvas,
)
from automation_file.ui.pages.run_panel import RunPanel
from automation_file.ui.pages.task_form import TaskForm

_FOLLOW_INTERVAL_MS = 500
_HISTORY_LIMIT = 50
_MAX_WORKERS = 64
_FILE_FILTER = "Pipeline definitions (*.yaml *.yml *.json);;All files (*)"
_UNSAVED = "not saved yet"
_CONNECT_HINT = "Connect (select two tasks)"
_RUN_PARAMETERS = "the run parameters"
_DEFAULT_PARAMETERS = "the default parameters"
_PAIR = 2
_FINISHED_OK = "succeeded"
#: Starting widths of the action list, the canvas and the task form.
_EDITOR_WIDTHS = (220, 560, 420)


class PipelinesPage(BasePage):
    """Build a pipeline on a canvas, check it, run it and follow the run."""

    title = "Pipelines"

    def __init__(self, service: PipelineService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._draft = service.new_draft()
        self._path: str | None = None
        self._run_id: str | None = None
        self._following = False
        self._loading = False

        self._canvas = PipelineCanvas()
        self._palette = ActionPalette()
        self._form = TaskForm(service)
        self._panel = RunPanel()
        self._file_label = QLabel(_UNSAVED)
        self._connect_button = QPushButton(_CONNECT_HINT)
        self._connect_button.clicked.connect(lambda _checked=False: self.connect_selected())

        editor = QSplitter(Qt.Orientation.Horizontal)
        editor.addWidget(self._palette_group())
        editor.addWidget(self._canvas_group())
        editor.addWidget(self._form_group())
        editor.setStretchFactor(0, 1)
        editor.setStretchFactor(1, 3)
        editor.setStretchFactor(2, 2)
        editor.setSizes(list(_EDITOR_WIDTHS))
        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.addLayout(self._run_bar())
        lower_layout.addWidget(self._panel, 1)
        body = QSplitter(Qt.Orientation.Vertical)
        body.addWidget(editor)
        body.addWidget(lower)
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addLayout(self._tool_bar())
        root.addLayout(self._header_bar())
        root.addWidget(body, 1)
        root.addWidget(self.status_label())

        self._timer = QTimer(self)
        self._timer.setInterval(_FOLLOW_INTERVAL_MS)
        self._timer.timeout.connect(self.poll)
        self._canvas.selection_changed.connect(self._on_selection)
        self._canvas.action_dropped.connect(self._on_action_dropped)
        self._form.applied.connect(self._on_task_applied)
        self._panel.task_chosen.connect(lambda task_id: self._canvas.select_tasks([task_id]))
        self._panel.run_chosen.connect(self.follow_run)
        self._set_draft(self._draft, None)

    # ------------------------------------------------------------------ layout

    def _tool_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(self.make_button("New", self.new_pipeline))
        row.addWidget(self.make_button("Open…", self.open_pipeline))
        row.addWidget(self.make_button("Save", self.save_pipeline))
        row.addWidget(self.make_button("Save as…", self.save_pipeline_as))
        row.addWidget(self.make_button("Auto layout", self.auto_layout))
        row.addWidget(self._file_label, 1)
        return row

    def _header_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._name = QLineEdit()
        self._description = QLineEdit()
        self._description.setPlaceholderText("description")
        self._max_workers = QSpinBox()
        self._max_workers.setRange(1, _MAX_WORKERS)
        self._defaults = QLineEdit()
        self._defaults.setPlaceholderText('default parameters (JSON), e.g. {"date": "2026-10-08"}')
        self._cron = QLineEdit()
        self._cron.setPlaceholderText("schedule (cron), kept for the scheduler")
        for field in (self._name, self._description, self._defaults, self._cron):
            field.editingFinished.connect(self._apply_header)
        self._max_workers.valueChanged.connect(lambda _value: self._apply_header())
        row.addWidget(QLabel("Name"))
        row.addWidget(self._name, 2)
        row.addWidget(QLabel("Max workers"))
        row.addWidget(self._max_workers)
        row.addWidget(self._description, 3)
        row.addWidget(self._defaults, 3)
        row.addWidget(self._cron, 2)
        return row

    def _palette_group(self) -> QGroupBox:
        box = QGroupBox("Actions")
        layout = QVBoxLayout(box)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("filter, e.g. storage")
        self._filter.textChanged.connect(self._palette.filter_actions)
        self._palette.itemDoubleClicked.connect(lambda item: self.add_task(item.text()))
        layout.addWidget(self._filter)
        layout.addWidget(self._palette, 1)
        layout.addWidget(self.muted_label("Drag an action onto the canvas, or double-click it."))
        layout.addWidget(self.make_button("Add task", self.add_task))
        return box

    def _canvas_group(self) -> QGroupBox:
        box = QGroupBox("Tasks and dependencies")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(self._connect_button)
        row.addWidget(self.make_button("Disconnect", self.disconnect_selected))
        row.addWidget(self.make_button("Remove selected", self.remove_selected))
        row.addStretch()
        layout.addLayout(row)
        layout.addWidget(self._canvas, 1)
        layout.addWidget(
            self.muted_label(
                "Select the upstream task, then Ctrl-click the task that depends on it, and "
                "press Connect. An arrow points from a task to the one that waits for it."
            )
        )
        return box

    def _form_group(self) -> QGroupBox:
        box = QGroupBox("Selected task")
        layout = QVBoxLayout(box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._form)
        layout.addWidget(scroll)
        return box

    def _run_bar(self) -> QVBoxLayout:
        self._run_params = QLineEdit()
        self._run_params.setPlaceholderText('a JSON object, e.g. {"date": "2026-10-09"}')
        params = QHBoxLayout()
        params.addWidget(QLabel("Run parameters"))
        params.addWidget(self._run_params, 1)
        row = QHBoxLayout()
        buttons: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("Validate", self.validate),
            ("Dry run", self.dry_run),
            ("Test task", self.test_task),
            ("Run", self.run),
            ("Resume", self.resume),
            ("Retry", self.retry),
            ("Cancel", self.cancel),
            ("Refresh history", self.refresh_history),
            ("Follow selected run", self.follow_selected),
        )
        for label, handler in buttons:
            row.addWidget(self.make_button(label, handler))
        row.addStretch()
        bar = QVBoxLayout()
        bar.addLayout(params)
        bar.addLayout(row)
        return bar

    # ------------------------------------------------------------------ parts, for callers

    def draft(self) -> PipelineDraft:
        """Return the draft the page edits."""
        return self._draft

    def canvas(self) -> PipelineCanvas:
        return self._canvas

    def form(self) -> TaskForm:
        return self._form

    def panel(self) -> RunPanel:
        return self._panel

    def action_palette(self) -> ActionPalette:
        return self._palette

    def current_run(self) -> str | None:
        """Return the ID of the run the page follows."""
        return self._run_id

    def set_run_params(self, text: str) -> None:
        """Fill in the run parameters field."""
        self._run_params.setText(text)

    # ------------------------------------------------------------------ the draft

    def _set_draft(self, draft: PipelineDraft, path: str | None) -> None:
        self._draft.remove_listener(self._on_draft_changed)
        self._draft, self._path = draft, path
        self._run_id, self._following = None, False
        self._timer.stop()
        draft.add_listener(self._on_draft_changed)
        self._canvas.set_draft(draft)
        self._form.set_draft(draft)
        self._load_header()
        self._panel.show_run(None)
        self._panel.show_events([])
        self._panel.clear_problems()
        self._show_file()

    def _load_header(self) -> None:
        self._loading = True
        try:
            self._name.setText(self._draft.name)
            self._description.setText(self._draft.description)
            self._max_workers.setValue(self._draft.max_workers)
            params = self._draft.params
            self._defaults.setText(_compact_json(params) if params else "")
            self._cron.setText((self._draft.schedule or {}).get("cron", ""))
        finally:
            self._loading = False

    def _apply_header(self) -> None:
        if self._loading:
            return
        try:
            params = parse_json_text(self._defaults.text(), _DEFAULT_PARAMETERS, empty={})
            self._write_header(params)
        except AppException as error:
            self.report_error(str(error))

    def _write_header(self, params: Any) -> None:
        """Write the header fields that differ from the draft, so reading them changes nothing."""
        draft = self._draft
        schedule = draft.schedule or {}
        with draft.batch():
            if self._name.text().strip() != draft.name:
                draft.set_name(self._name.text())
            if self._description.text() != draft.description:
                draft.set_description(self._description.text())
            if self._max_workers.value() != draft.max_workers:
                draft.set_max_workers(self._max_workers.value())
            if params != draft.params:
                draft.set_params(params)
            if self._cron.text().strip() != schedule.get("cron", ""):
                draft.set_schedule(self._cron.text(), schedule.get("timezone"))

    def _on_draft_changed(self, _change: str) -> None:
        self._show_file()

    def _show_file(self) -> None:
        marker = " (modified)" if self._draft.dirty else ""
        self._file_label.setText(f"{self._path or _UNSAVED}{marker}")

    def new_pipeline(self) -> None:
        """Start an empty draft."""
        if self._keep_unsaved():
            return
        self._set_draft(self._service.new_draft(), None)
        self.report("new pipeline")

    def open_pipeline(self, path: str | None = None) -> None:
        """Open a definition file; without ``path`` a file dialog asks for one."""
        if self._keep_unsaved():
            return
        chosen = path or self.pick_open_file("Open pipeline definition", _FILE_FILTER)
        if not chosen:
            return
        self.run_async(
            lambda: self._service.load(chosen),
            f"open {chosen}",
            lambda draft: self._opened(draft, chosen),
        )

    def _opened(self, draft: PipelineDraft, path: str) -> None:
        self._set_draft(draft, path)
        if draft.load_notes:
            # What was wrong with the file as it was read, including what could not be shown.
            task_ids = draft.task_ids()
            self._panel.show_problems([Problem.parse(note, task_ids) for note in draft.load_notes])
            self.report_error(f"opened {path} with {len(draft.load_notes)} problem(s) to fix")
        else:
            self.report(f"opened {path}: {len(draft.tasks)} task(s)")

    def save_pipeline(self) -> None:
        """Save to the file the draft was opened from or last saved to."""
        self.save_pipeline_as(self._path)

    def save_pipeline_as(self, path: str | None = None) -> None:
        """Save the definition and, next to it, the canvas layout."""
        self._apply_header()
        chosen = path or self.pick_save_file("Save pipeline definition", _FILE_FILTER)
        if not chosen:
            return
        try:
            self._path = self._service.save(self._draft, chosen)
        except FileAutomationException as error:
            self.report_error(f"cannot save {chosen}: {error}")
            return
        self._show_file()
        self.report(f"saved {self._path}")

    def _keep_unsaved(self) -> bool:
        """Return whether the user wants to keep the unsaved draft instead of replacing it."""
        return self._draft.dirty and not self.confirm("Discard the changes that are not saved?")

    # ------------------------------------------------------------------ tasks and edges

    def add_task(
        self, action: str | None = None, position: tuple[float, float] | None = None
    ) -> str:
        """Add a task for ``action`` (the palette's selection by default); return its ID."""
        chosen = self._palette.selected_action() if action is None else action
        task = self._draft.add_task(chosen, position=position)
        self._canvas.select_tasks([task.task_id])
        self.report(f"added task {task.task_id}")
        return task.task_id

    def _on_action_dropped(self, action: str, x: float, y: float) -> None:
        self.add_task(action, (x - NODE_WIDTH / 2, y - NODE_HEIGHT / 2))

    def remove_selected(self) -> None:
        """Remove the selected arrows, or else the selected tasks."""
        edges, tasks = self._canvas.selected_edges(), self._canvas.selected_tasks()
        if not edges and not tasks:
            self.report_error("select a task or an arrow to remove")
            return
        with self._draft.batch():
            for upstream, downstream in edges:
                self._draft.disconnect(upstream, downstream)
            for task_id in [] if edges else tasks:
                self._draft.remove_task(task_id)
        removed = f"{len(edges)} arrow(s)" if edges else f"task(s) {', '.join(tasks)}"
        self.report(f"removed {removed}")

    def connect_selected(self) -> None:
        """Make the task selected second depend on the task selected first."""
        selected = self._canvas.selected_tasks()
        if len(selected) != _PAIR:
            self.report_error(
                "select exactly two tasks: first the upstream one, then its dependent"
            )
            return
        upstream, downstream = selected
        try:
            added = self._draft.connect(upstream, downstream)
        except AppException as error:
            self.report_error(str(error))
            return
        self.report(
            f"{downstream} now depends on {upstream}"
            if added
            else f"{downstream} already depends on {upstream}"
        )

    def disconnect_selected(self) -> None:
        """Remove the selected arrows, or the dependency between the two selected tasks."""
        pairs = self._canvas.selected_edges()
        selected = self._canvas.selected_tasks()
        if not pairs and len(selected) == _PAIR:
            pairs = [(selected[0], selected[1]), (selected[1], selected[0])]
        with self._draft.batch():
            removed = [pair for pair in pairs if self._draft.disconnect(*pair)]
        if removed:
            self.report("removed " + ", ".join(f"{up} -> {down}" for up, down in removed))
        else:
            self.report_error("select an arrow, or two connected tasks, to disconnect")

    def auto_layout(self) -> None:
        self._draft.auto_layout()
        self.report("tasks laid out by dependency depth")

    def _on_selection(self, selected: list[str]) -> None:
        self._form.show_task(selected[-1] if selected else None)
        if len(selected) == _PAIR:
            self._connect_button.setText(f"Connect {selected[0]} -> {selected[1]}")
        else:
            self._connect_button.setText(_CONNECT_HINT)

    def _on_task_applied(self, task_id: str) -> None:
        self._canvas.select_tasks([task_id])
        self.report(f"task {task_id} updated")

    # ------------------------------------------------------------------ checks

    def validate(self) -> bool:
        """List every problem of the draft; return whether there is none."""
        problems = self._service.validate(self._draft.to_definition())
        self._panel.show_problems(problems)
        if problems:
            self.report_error(f"{len(problems)} problem(s): see the Problems tab")
        else:
            self.report("the definition is valid")
        return not problems

    def _inputs(self) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
        """Return the definition and the run parameters, or ``None`` when they cannot be used."""
        self._apply_header()
        try:
            params = parse_json_text(self._run_params.text(), _RUN_PARAMETERS)
        except AppException as error:
            self.report_error(str(error))
            return None
        if params is not None and not isinstance(params, dict):
            self.report_error(f"{_RUN_PARAMETERS} must be a JSON object")
            return None
        if not self.validate():
            return None
        return self._draft.to_definition(), params

    def dry_run(self) -> None:
        """Plan a run without executing anything."""
        inputs = self._inputs()
        if inputs is not None:
            definition, params = inputs
            self.run_async(
                lambda: self._service.dry_run(definition, params), "dry run", self._show_plan
            )

    def _show_plan(self, plan: dict[str, Any]) -> None:
        self._show_run(plan, "dry run")
        self._panel.show_tasks_tab()
        if plan.get("status") == _FINISHED_OK:
            self.report(f"dry run: {len(plan.get('tasks') or {})} task(s) would run as planned")
        else:
            notes = [str(state["error"]) for state in plan["tasks"].values() if state.get("error")]
            self.report_error(f"dry run: {'; '.join(notes) or plan.get('error')}")

    def test_task(self) -> None:
        """Execute the selected task alone; its upstream tasks are stand-ins that return nothing."""
        task_id = self._form.current_task()
        if task_id is None:
            self.report_error("select the task to test")
            return
        inputs = self._inputs()
        if inputs is not None:
            definition, params = inputs
            self.run_async(
                lambda: self._service.test_task(definition, task_id, params),
                f"test task {task_id}",
                lambda outcome: self._show_test(task_id, outcome),
            )

    def _show_test(self, task_id: str, outcome: dict[str, Any]) -> None:
        run = outcome["run"]
        self._show_run(run, f"test of {task_id}")
        self._panel.show_tasks_tab()
        self._panel.show_events(outcome["events"])
        state = run["tasks"][task_id]
        if state.get("status") == _FINISHED_OK:
            self.report(f"test of {task_id} succeeded in {state.get('attempts')} attempt(s)")
        else:
            self.report_error(f"test of {task_id}: {state.get('status')}: {state.get('error')}")

    def _show_run(self, run: dict[str, Any], headline: str = "") -> None:
        """Show a run in the task table and on the canvas, leaving the visible tab alone."""
        self._panel.show_run(run, headline)
        self._canvas.set_statuses(
            {task_id: str(state.get("status")) for task_id, state in run["tasks"].items()}
        )

    # ------------------------------------------------------------------ runs

    def run(self) -> None:
        """Start a run in the background and follow it."""
        inputs = self._inputs()
        if inputs is not None:
            definition, params = inputs
            self.run_async(
                lambda: self._service.start(definition, params), "start run", self._on_started
            )

    def resume(self) -> None:
        """Continue the followed run: keep what succeeded, run the rest."""
        self._again("resume", self._service.resume)

    def retry(self) -> None:
        """Start a new run with the parameters of the followed run."""
        self._again("retry", self._service.retry)

    def _again(self, verb: str, call: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        run_id = self._run_id or self._panel.selected_run()
        if run_id is None:
            self.report_error(f"there is no run to {verb}: run the pipeline or pick one in History")
            return
        if not self.validate():
            return
        definition = self._draft.to_definition()
        self.run_async(lambda: call(run_id, definition), f"{verb} run {run_id}", self._on_started)

    def cancel(self) -> None:
        """Ask the followed run to stop."""
        if self._run_id is None:
            self.report_error("there is no run to cancel")
        elif self._service.cancel(self._run_id):
            self.report(f"cancel requested for run {self._run_id}")
        else:
            self.report_error(f"run {self._run_id} is not running in this process")

    def _on_started(self, run: dict[str, Any]) -> None:
        self._run_id, self._following = run["run_id"], True
        self._show_run(run)
        self._panel.show_tasks_tab()
        self._panel.show_events([])
        self.report(f"run {run['run_id']} is {run.get('status')}")
        self._timer.start()
        self.poll()

    def follow_selected(self) -> None:
        run_id = self._panel.selected_run()
        if run_id is None:
            self.report_error("select a run in the History tab first")
        else:
            self.follow_run(run_id)

    def follow_run(self, run_id: str) -> None:
        """Show the run ``run_id`` and keep following it until it has ended."""
        self._run_id, self._following = run_id, True
        self._panel.show_tasks_tab()
        self._timer.start()
        self.poll()

    def _stop_following(self) -> None:
        """Stop asking about a run that cannot be read; the failure is already on the status line."""
        self._following = False
        self._timer.stop()

    def poll(self) -> None:
        """Read the followed run once; the timer calls this until the run has ended."""
        run_id = self._run_id
        if run_id is None:
            self._timer.stop()
            return
        self.run_async(
            lambda: self._service.follow(run_id),
            "follow run",
            self._show_followed,
            key="follow",
            quiet=True,
            on_error=self._stop_following,
        )

    def _show_followed(self, data: dict[str, Any]) -> None:
        run = data["run"]
        if run.get("run_id") != self._run_id:
            return
        self._show_run(run)
        self._panel.show_events(data["events"])
        if run.get("active") or not self._following:
            return
        self._following = False
        self._timer.stop()
        if run.get("status") == _FINISHED_OK:
            self.report(f"run {run['run_id']} succeeded")
        else:
            self.report_error(f"run {run['run_id']} ended {run.get('status')}: {run.get('error')}")
        self.refresh_history()

    def refresh_history(self) -> None:
        self.run_async(
            lambda: self._service.history(None, _HISTORY_LIMIT),
            "read history",
            self._panel.show_history,
            key="history",
            quiet=True,
        )

    # ------------------------------------------------------------------ lifecycle

    def refresh(self) -> None:
        self.run_async(
            self._service.action_names,
            "read actions",
            self._show_actions,
            key="actions",
            quiet=True,
        )
        self.refresh_history()

    def _show_actions(self, names: list[str]) -> None:
        self._palette.set_actions(names)
        self._palette.filter_actions(self._filter.text())
        self._form.set_actions(names)

    def shutdown(self) -> None:
        self._timer.stop()
        self._draft.remove_listener(self._on_draft_changed)
        self._canvas.set_draft(None)
        super().shutdown()


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=repr)
