"""The form of one pipeline task: its action, its arguments and how it runs.

:class:`TaskForm` shows the selected task of a
:class:`~automation_file.app.PipelineDraft` and writes the fields back through
the draft's own methods when the user presses Apply. It holds no copy of the
task: after every apply, and whenever the selection changes, it is filled from
the draft again.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from automation_file.app import (
    ActionInfo,
    AppException,
    PipelineDraft,
    PipelineService,
    format_argument_value,
    parse_argument_text,
    parse_json_text,
    split_names,
)

_ARGUMENT_COLUMNS = ("Argument", "Value (JSON or text)", "Default")
_NAME_COLUMN, _VALUE_COLUMN, _DEFAULT_COLUMN = 0, 1, 2
_TABLE_PAGE, _JSON_PAGE = 0, 1
_REQUIRED = "required"
_WHEN_CHOICES = ("on_success", "on_failure", "always")
_MAX_ATTEMPTS = 100
_MAX_SECONDS = 86_400.0
_DEFAULT_BACKOFF_CAP = 60.0
_ERROR_STYLE = "color: #b3261e;"
_OK_STYLE = "color: #2f8f3f;"
_NO_TASK = "Select a task on the canvas to edit it."
_ARGUMENTS = "the arguments"


def _read_only(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _as_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=repr)


class ArgumentsEditor(QWidget):
    """The arguments of an action: one row per parameter, or the JSON itself.

    A keyword mapping is edited in a table whose rows come from the action's
    signature; a value is JSON when it parses as JSON and text otherwise, and a
    row left empty is not passed, so the action's default applies. A positional
    list can only be edited as JSON.
    """

    def __init__(self) -> None:
        super().__init__()
        self._table = QTableWidget(0, len(_ARGUMENT_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_ARGUMENT_COLUMNS))
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._raw = QPlainTextEdit()
        self._raw.setPlaceholderText('{"source": "s3://in/a.csv"}  or  ["s3://in/a.csv", true]')
        self._stack = QStackedWidget()
        self._stack.addWidget(self._table)
        self._stack.addWidget(self._raw)
        self._as_json = QCheckBox("Edit as JSON")
        self._as_json.toggled.connect(self._on_mode_toggled)
        add_row = QPushButton("Add argument")
        add_row.clicked.connect(lambda _checked=False: self.add_row())

        buttons = QHBoxLayout()
        buttons.addWidget(self._as_json)
        buttons.addWidget(add_row)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        layout.addLayout(buttons)

    def is_json_mode(self) -> bool:
        """Return whether the arguments are edited as JSON text."""
        return self._as_json.isChecked()

    def set_json_mode(self, enabled: bool) -> None:
        """Switch between the table and the JSON text, carrying the arguments over."""
        self._as_json.setChecked(enabled)

    def set_arguments(self, arguments: Any, info: ActionInfo | None = None) -> None:
        """Show ``arguments``; ``info`` supplies the parameter rows of the action."""
        positional = isinstance(arguments, list)
        self._fill_table({} if positional or arguments is None else dict(arguments), info)
        self._raw.setPlainText("" if arguments is None else _as_json(arguments))
        self._set_mode(positional)

    def arguments(self) -> dict[str, Any] | list[Any] | None:
        """Return the arguments the editor holds; unreadable JSON raises :class:`AppException`."""
        if not self._as_json.isChecked():
            return self._table_arguments() or None
        parsed = parse_json_text(self._raw.toPlainText(), _ARGUMENTS)
        if parsed is not None and not isinstance(parsed, (dict, list)):
            raise AppException(f"{_ARGUMENTS} must be a JSON object, a JSON array or empty")
        return parsed

    def add_row(self, name: str = "", value: str = "") -> None:
        """Append a row for an argument the signature does not list."""
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, _NAME_COLUMN, QTableWidgetItem(name))
        self._table.setItem(row, _VALUE_COLUMN, QTableWidgetItem(value))
        self._table.setItem(row, _DEFAULT_COLUMN, _read_only(""))

    def set_value(self, name: str, text: str) -> bool:
        """Type ``text`` into the row of the argument ``name``; return whether there is one."""
        for row in range(self._table.rowCount()):
            if self._cell(row, _NAME_COLUMN) == name:
                self._table.setItem(row, _VALUE_COLUMN, QTableWidgetItem(text))
                return True
        return False

    def set_json_text(self, text: str) -> None:
        """Replace the JSON text (the editor must be in JSON mode for it to count)."""
        self._raw.setPlainText(text)

    def row_names(self) -> list[str]:
        """Return the argument names of the table rows, in order."""
        return [self._cell(row, _NAME_COLUMN) for row in range(self._table.rowCount())]

    def _cell(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return "" if item is None else item.text().strip()

    def _set_mode(self, as_json: bool) -> None:
        self._as_json.blockSignals(True)
        self._as_json.setChecked(as_json)
        self._as_json.blockSignals(False)
        self._stack.setCurrentIndex(_JSON_PAGE if as_json else _TABLE_PAGE)

    def _fill_table(self, values: dict[str, Any], info: ActionInfo | None) -> None:
        self._table.setRowCount(0)
        listed: list[str] = []
        for parameter in info.parameters if info is not None else ():
            listed.append(parameter.name)
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, _NAME_COLUMN, _read_only(parameter.name))
            shown = (
                format_argument_value(values[parameter.name]) if parameter.name in values else ""
            )
            self._table.setItem(row, _VALUE_COLUMN, QTableWidgetItem(shown))
            hint = _REQUIRED if parameter.required else parameter.default
            self._table.setItem(row, _DEFAULT_COLUMN, _read_only(hint))
        for name, value in values.items():
            if name not in listed:
                self.add_row(str(name), format_argument_value(value))

    def _table_arguments(self) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for row in range(self._table.rowCount()):
            name, text = self._cell(row, _NAME_COLUMN), self._cell(row, _VALUE_COLUMN)
            if name and text:
                found[name] = parse_argument_text(text)
        return found

    def _on_mode_toggled(self, as_json: bool) -> None:
        if as_json:
            values = self._table_arguments()
            self._raw.setPlainText(_as_json(values) if values else "")
            self._stack.setCurrentIndex(_JSON_PAGE)
            return
        try:
            parsed = parse_json_text(self._raw.toPlainText(), _ARGUMENTS)
        except AppException:
            # Text that is not JSON yet has no rows to become: stay with the text.
            self._set_mode(True)
            return
        if parsed is not None and not isinstance(parsed, dict):
            # A positional list has no argument names: it can only be edited as JSON.
            self._set_mode(True)
            return
        for name, value in (parsed or {}).items():
            if not self.set_value(name, format_argument_value(value)):
                self.add_row(name, format_argument_value(value))
        self._stack.setCurrentIndex(_TABLE_PAGE)


# pylint: disable-next=too-many-instance-attributes  # one input widget per field of a task
class TaskForm(QWidget):
    """Edits the selected task of a draft; nothing changes until Apply is pressed."""

    #: Emitted after the fields were written to the draft, with the task's (possibly new) ID.
    applied = Signal(str)

    def __init__(self, service: PipelineService) -> None:
        super().__init__()
        self._service = service
        self._draft: PipelineDraft | None = None
        self._task: str | None = None
        self._loading = False
        self._applying = False

        self._task_id = QLineEdit()
        self._action = QComboBox()
        self._action.setEditable(True)
        self._action.currentTextChanged.connect(self._on_action_changed)
        self._signature = QLabel("")
        self._signature.setWordWrap(True)
        self._arguments = ArgumentsEditor()
        self._depends = QListWidget()
        self._depends.setMaximumHeight(110)
        self._attempts = QSpinBox()
        self._attempts.setRange(1, _MAX_ATTEMPTS)
        self._backoff = self._seconds_box(0.0)
        self._backoff_cap = self._seconds_box(_DEFAULT_BACKOFF_CAP)
        self._retry_on = QLineEdit()
        self._retry_on.setPlaceholderText(
            "exception names, comma-separated; empty: transient errors"
        )
        self._timeout = QLineEdit()
        self._timeout.setPlaceholderText("seconds for the whole task; empty: no limit")
        self._when = QComboBox()
        self._when.addItems(_WHEN_CHOICES)
        self._key = QLineEdit()
        self._key.setPlaceholderText("e.g. publish-${params.date}; empty: none")
        self._message = QLabel(_NO_TASK)
        self._message.setWordWrap(True)
        self._lines = {
            "task_id": self._task_id,
            "retry_on": self._retry_on,
            "timeout": self._timeout,
            "key": self._key,
        }
        self._build_layout()
        self.setEnabled(False)

    @staticmethod
    def _seconds_box(value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0.0, _MAX_SECONDS)
        box.setDecimals(1)
        box.setSuffix(" s")
        box.setValue(value)
        return box

    def _build_layout(self) -> None:
        form = QFormLayout()
        # Labels above their fields: the form lives in a side panel, where width is scarce.
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow("Task ID", self._task_id)
        form.addRow("Action", self._action)
        form.addRow(self._signature)
        form.addRow("Arguments", self._arguments)
        form.addRow("Depends on", self._depends)
        form.addRow("Attempts", self._attempts)
        form.addRow("Back-off", self._backoff)
        form.addRow("Back-off cap", self._backoff_cap)
        form.addRow("Retry on", self._retry_on)
        form.addRow("Timeout", self._timeout)
        form.addRow("Run when", self._when)
        form.addRow("Idempotency key", self._key)
        apply_button = QPushButton("Apply changes")
        apply_button.clicked.connect(lambda _checked=False: self.apply())
        revert_button = QPushButton("Revert")
        revert_button.clicked.connect(lambda _checked=False: self.revert())
        buttons = QHBoxLayout()
        buttons.addWidget(apply_button)
        buttons.addWidget(revert_button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self._message)

    # ------------------------------------------------------------------ what it edits

    def set_actions(self, names: list[str]) -> None:
        """Offer ``names`` in the action field."""
        self._loading = True
        try:
            current = self._action.currentText()
            self._action.clear()
            self._action.addItems(names)
            self._action.setEditText(current)
        finally:
            self._loading = False

    def set_draft(self, draft: PipelineDraft | None) -> None:
        """Edit tasks of ``draft`` from now on; the form is emptied."""
        self._draft = draft
        self._task = None
        self.show_task(None)

    def current_task(self) -> str | None:
        """Return the ID of the task the form shows."""
        return self._task

    def message(self) -> str:
        """Return what the form last said: the outcome of an apply, or what to do."""
        return self._message.text()

    def arguments_editor(self) -> ArgumentsEditor:
        """Return the editor of the action's arguments."""
        return self._arguments

    def revert(self) -> None:
        """Throw away what was typed and show the task as the draft has it."""
        task_id, self._task = self._task, None
        self.show_task(task_id)

    def show_task(self, task_id: str | None) -> None:
        """Fill the form from the draft's task ``task_id``; ``None`` empties and disables it.

        Showing the task the form already shows keeps what was typed and only
        brings the dependency list up to date: the canvas reports the same
        selection again after every change of the draft, and an arrow drawn
        there must not be undone by the next Apply. :meth:`revert` reloads
        every field.
        """
        if self._applying:
            return
        draft = self._draft
        if draft is None or task_id is None or not draft.has_task(task_id):
            self._task = None
            self.setEnabled(False)
            self._say(_NO_TASK, "")
            return
        if task_id == self._task:
            self._fill_dependencies(draft, task_id)
            return
        self._task = task_id
        self.setEnabled(True)
        self._loading = True
        try:
            self._load(draft, task_id)
        finally:
            self._loading = False
        self._say(f"Editing {task_id}.", "")

    def _load(self, draft: PipelineDraft, task_id: str) -> None:
        task = draft.task(task_id)
        self._task_id.setText(task.task_id)
        self._action.setEditText(task.action)
        info = self._service.describe_action(task.action)
        self._show_signature(info)
        self._arguments.set_arguments(task.arguments, info)
        self._fill_dependencies(draft, task_id)
        retry = task.retry or {}
        self._attempts.setValue(int(retry.get("max_attempts", 1)))
        self._backoff.setValue(float(retry.get("backoff", 0.0)))
        self._backoff_cap.setValue(float(retry.get("backoff_cap", _DEFAULT_BACKOFF_CAP)))
        self._retry_on.setText(", ".join(retry.get("on") or ()))
        self._timeout.setText("" if task.timeout is None else f"{task.timeout:g}")
        self._when.setCurrentText(task.when)
        self._key.setText(task.idempotency_key or "")

    def _fill_dependencies(self, draft: PipelineDraft, task_id: str) -> None:
        self._depends.clear()
        wanted = draft.task(task_id).depends_on
        for other in draft.task_ids():
            if other == task_id:
                continue
            entry = QListWidgetItem(other)
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(
                Qt.CheckState.Checked if other in wanted else Qt.CheckState.Unchecked
            )
            self._depends.addItem(entry)

    def _show_signature(self, info: ActionInfo) -> None:
        if not info.name:
            self._signature.setText("Choose an action.")
        elif not info.known:
            self._signature.setText(f"{info.name} is not a registered action.")
        else:
            self._signature.setText(f"{info.signature or info.name}\n{info.summary}".strip())

    def _on_action_changed(self, name: str) -> None:
        if self._loading or self._task is None:
            return
        info = self._service.describe_action(name.strip())
        self._show_signature(info)
        if self._arguments.is_json_mode():
            return
        self._arguments.set_arguments(self._arguments.arguments(), info)

    # ------------------------------------------------------------------ setters for callers

    def set_field(self, name: str, text: str) -> None:
        """Type ``text`` into a line field: ``task_id``, ``retry_on``, ``timeout`` or ``key``."""
        self._lines[name].setText(text)

    def set_action(self, name: str) -> None:
        """Type ``name`` into the action field."""
        self._action.setEditText(name)

    def set_retry(self, attempts: int, backoff: float = 0.0) -> None:
        """Set the number of attempts and the first back-off."""
        self._attempts.setValue(attempts)
        self._backoff.setValue(backoff)

    def set_condition(self, when: str) -> None:
        """Choose when the task runs."""
        self._when.setCurrentText(when)

    def set_dependency(self, task_id: str, checked: bool) -> bool:
        """Tick or clear the dependency on ``task_id``; return whether it is listed."""
        for row in range(self._depends.count()):
            entry = self._depends.item(row)
            if entry.text() == task_id:
                entry.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                return True
        return False

    def checked_dependencies(self) -> list[str]:
        """Return the task IDs ticked in the dependency list."""
        return [
            self._depends.item(row).text()
            for row in range(self._depends.count())
            if self._depends.item(row).checkState() == Qt.CheckState.Checked
        ]

    # ------------------------------------------------------------------ apply

    def apply(self) -> bool:
        """Write the fields to the draft; return whether everything was accepted.

        The rename comes last, so a field the draft refuses leaves the task
        under the ID the canvas has selected, with what was typed still there.
        """
        draft, task_id = self._draft, self._task
        if draft is None or task_id is None:
            return False
        self._applying = True
        try:
            task_id = self._write(draft, task_id)
        except AppException as error:
            self._say(str(error), _ERROR_STYLE)
            return False
        finally:
            self._applying = False
        self._task = None
        self.show_task(task_id)
        self._say(f"Applied to {task_id}.", _OK_STYLE)
        self.applied.emit(task_id)
        return True

    def _write(self, draft: PipelineDraft, task_id: str) -> str:
        arguments = self._arguments.arguments()
        timeout = self._timeout_value()
        wanted_id = self._task_id.text().strip()
        with draft.batch():
            draft.set_action(task_id, self._action.currentText())
            draft.set_arguments(task_id, arguments)
            draft.set_dependencies(task_id, self.checked_dependencies())
            draft.set_retry(
                task_id,
                self._attempts.value(),
                self._backoff.value(),
                self._backoff_cap.value(),
                split_names(self._retry_on.text()) or None,
            )
            draft.set_timeout(task_id, timeout)
            draft.set_condition(task_id, self._when.currentText())
            draft.set_idempotency_key(task_id, self._key.text().strip() or None)
            if wanted_id != task_id:
                draft.rename_task(task_id, wanted_id)
        return wanted_id

    def _timeout_value(self) -> float | None:
        text = self._timeout.text().strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            raise AppException(f"the timeout must be a number of seconds, got {text!r}") from None

    def _say(self, text: str, style: str) -> None:
        self._message.setStyleSheet(style)
        self._message.setText(text)
