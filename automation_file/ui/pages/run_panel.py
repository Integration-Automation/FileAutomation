"""What a pipeline editor shows about checks and runs: problems, task statuses, log, history."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from automation_file.app import Problem
from automation_file.ui.pages.base import fill_table, make_table, selected_cell

_TASK_COLUMNS = ("Task", "Status", "Level", "Attempts", "Duration (ms)", "Error / reason", "Result")
_HISTORY_COLUMNS = ("Run", "Pipeline", "Status", "Active", "Started", "Finished", "Error")
_NO_PROBLEMS = "No problems found."
_NOT_VALIDATED = "Not validated yet: press Validate."
_TIME_START, _TIME_END = 11, 19
_MAX_RESULT = 120
_PROBLEMS_TAB, _TASKS_TAB, _HISTORY_TAB = 0, 1, 3


def _short(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= _MAX_RESULT else f"{text[: _MAX_RESULT - 1]}…"


def event_line(event: dict[str, Any]) -> str:
    """Return one log line for an event: time, severity, type, subject and error."""
    stamp = str(event.get("timestamp") or "")[_TIME_START:_TIME_END]
    line = f"{stamp} [{event.get('severity')}] {event.get('type')}: {event.get('subject')}"
    error = (event.get("payload") or {}).get("error")
    return f"{line} -- {error}" if error else line


class RunPanel(QTabWidget):
    """Four tabs under the canvas: Problems, Tasks, Log and History."""

    #: A task ID the user picked in the problem list or in the task table.
    task_chosen = Signal(str)
    #: A run ID the user picked in the history.
    run_chosen = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._problems: list[Problem] = []
        self._problem_list = QListWidget()
        self._problem_list.itemClicked.connect(self._on_problem_clicked)
        self._run_label = QLabel("No run yet.")
        self._run_label.setWordWrap(True)
        self._task_table = make_table(_TASK_COLUMNS)
        self._task_table.cellClicked.connect(lambda _row, _column: self._on_task_clicked())
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("The events of the run appear here.")
        self._history = make_table(_HISTORY_COLUMNS)
        self._history.cellDoubleClicked.connect(lambda _row, _column: self._on_history_chosen())
        self._history_ids: list[str] = []

        tasks = QWidget()
        layout = QVBoxLayout(tasks)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._run_label)
        layout.addWidget(self._task_table)
        self.addTab(self._problem_list, "Problems")
        self.addTab(tasks, "Tasks")
        self.addTab(self._log, "Log")
        self.addTab(self._history, "History")

    # ------------------------------------------------------------------ problems

    def show_problems(self, problems: list[Problem]) -> None:
        """List ``problems``, each with its path, and bring the tab forward."""
        self._problems = list(problems)
        self._problem_list.clear()
        for problem in problems:
            self._problem_list.addItem(QListWidgetItem(str(problem)))
        if not problems:
            self._problem_list.addItem(QListWidgetItem(_NO_PROBLEMS))
        self.setTabText(_PROBLEMS_TAB, f"Problems ({len(problems)})")
        self.setCurrentIndex(_PROBLEMS_TAB)

    def clear_problems(self) -> None:
        """Forget the listed problems: the definition has not been checked."""
        self._problems = []
        self._problem_list.clear()
        self._problem_list.addItem(QListWidgetItem(_NOT_VALIDATED))
        self.setTabText(_PROBLEMS_TAB, "Problems")

    def problem_texts(self) -> list[str]:
        """Return the listed problems as text."""
        return [str(problem) for problem in self._problems]

    def _on_problem_clicked(self, item: QListWidgetItem) -> None:
        row = self._problem_list.row(item)
        if 0 <= row < len(self._problems) and self._problems[row].task:
            self.task_chosen.emit(str(self._problems[row].task))

    # ------------------------------------------------------------------ the run

    def show_run(self, run: dict[str, Any] | None, headline: str = "") -> None:
        """Show the state of ``run`` and of its tasks; ``None`` clears the table."""
        if run is None:
            self._run_label.setText("No run yet.")
            fill_table(self._task_table, [])
            return
        kind = "dry run" if run.get("dry_run") else "run"
        described = headline or f"{kind} {run.get('run_id')}"
        error = f" -- {run.get('error')}" if run.get("error") else ""
        self._run_label.setText(f"{described}: {run.get('status')}{error}")
        fill_table(
            self._task_table,
            [
                [
                    task_id,
                    state.get("status"),
                    state.get("level"),
                    state.get("attempts"),
                    state.get("duration_ms"),
                    state.get("error") or state.get("reason"),
                    _short(state.get("result")),
                ]
                for task_id, state in (run.get("tasks") or {}).items()
            ],
        )

    def task_rows(self) -> list[tuple[str, str]]:
        """Return ``(task, status)`` for every row of the task table."""
        rows: list[tuple[str, str]] = []
        for row in range(self._task_table.rowCount()):
            task, status = self._task_table.item(row, 0), self._task_table.item(row, 1)
            if task is not None and status is not None:
                rows.append((task.text(), status.text()))
        return rows

    def run_text(self) -> str:
        """Return the line above the task table."""
        return self._run_label.text()

    def show_tasks_tab(self) -> None:
        self.setCurrentIndex(_TASKS_TAB)

    def _on_task_clicked(self) -> None:
        task_id = selected_cell(self._task_table)
        if task_id:
            self.task_chosen.emit(task_id)

    # ------------------------------------------------------------------ the log

    def show_events(self, events: list[dict[str, Any]]) -> None:
        """Replace the log with one line per event, oldest first."""
        self._log.setPlainText("\n".join(event_line(event) for event in events))
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    def log_text(self) -> str:
        """Return what the log shows."""
        return self._log.toPlainText()

    # ------------------------------------------------------------------ history

    def show_history(self, runs: list[dict[str, Any]]) -> None:
        """List ``runs``, newest first."""
        self._history_ids = [str(run.get("run_id")) for run in runs]
        fill_table(
            self._history,
            [
                [
                    run.get("run_id"),
                    run.get("pipeline"),
                    run.get("status"),
                    bool(run.get("active")),
                    run.get("started_at"),
                    run.get("finished_at"),
                    run.get("error"),
                ]
                for run in runs
            ],
        )

    def history_ids(self) -> list[str]:
        """Return the run IDs of the history, in the order shown."""
        return list(self._history_ids)

    def selected_run(self) -> str | None:
        """Return the run ID selected in the history, or ``None``."""
        row = self._history.currentRow()
        return self._history_ids[row] if 0 <= row < len(self._history_ids) else None

    def select_run(self, run_id: str) -> bool:
        """Select ``run_id`` in the history; return whether it is listed."""
        if run_id not in self._history_ids:
            return False
        self._history.selectRow(self._history_ids.index(run_id))
        return True

    def show_history_tab(self) -> None:
        self.setCurrentIndex(_HISTORY_TAB)

    def _on_history_chosen(self) -> None:
        run_id = self.selected_run()
        if run_id is not None:
            self.run_chosen.emit(run_id)
