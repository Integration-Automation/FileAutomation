"""Visual JSON action editor.

Action lists are edited through a list on the left (one row per action)
and a signature-driven form on the right (auto-generated from the
registered callable). The raw JSON is still available via the "Raw
JSON" toggle — the tree and the textarea stay in sync.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from automation_file.core.action_executor import (
    execute_action,
    execute_action_parallel,
    executor,
    validate_action,
)
from automation_file.ui.tabs.base import BaseTab

_PATH_HINT_SUBSTRINGS = ("path", "_dir", "_file", "directory", "filename", "target")
_SECRET_HINT_SUBSTRINGS = ("password", "secret", "token", "credential")
_SETTINGS_ORG = "automation_file"
_SETTINGS_APP = "ui"
_LAST_JSON_DIR_KEY = "json_editor/last_dir"


def _is_path_like(name: str) -> bool:
    lower = name.lower()
    return any(hint in lower for hint in _PATH_HINT_SUBSTRINGS)


def _is_secret_like(name: str) -> bool:
    lower = name.lower()
    return any(hint in lower for hint in _SECRET_HINT_SUBSTRINGS)


def _parse_maybe_json(raw: str) -> Any:
    stripped = raw.strip()
    if not stripped:
        return ""
    if stripped[0] in "[{" or stripped in ("true", "false", "null"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return raw
    if stripped.lstrip("-").isdigit():
        try:
            return int(stripped)
        except ValueError:
            return raw
    return raw


class _FieldWidget:
    """Bundle the visible widget plus getter/setter for one parameter."""

    def __init__(
        self,
        widget: QWidget,
        get_value: Callable[[], Any],
        set_value: Callable[[Any], None],
    ) -> None:
        self.widget = widget
        self.get_value = get_value
        self.set_value = set_value


def _build_line_edit(default: Any, secret: bool) -> _FieldWidget:
    edit = QLineEdit()
    if secret:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
    if default not in (None, inspect.Parameter.empty):
        edit.setText(str(default))
    return _FieldWidget(
        edit,
        lambda: _parse_maybe_json(edit.text()),
        lambda v: edit.setText("" if v is None else str(v)),
    )


def _build_path_picker(default: Any, secret: bool) -> _FieldWidget:
    field = _build_line_edit(default, secret)
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(field.widget)
    pick = QPushButton("Browse…")

    def _on_click() -> None:
        path, _ = QFileDialog.getOpenFileName(box, "Select file")
        if path:
            field.set_value(path)

    pick.clicked.connect(_on_click)
    row.addWidget(pick)
    return _FieldWidget(box, field.get_value, field.set_value)


def _build_checkbox(default: Any) -> _FieldWidget:
    cb = QCheckBox()
    cb.setChecked(bool(default) if default not in (None, inspect.Parameter.empty) else False)
    return _FieldWidget(cb, cb.isChecked, lambda v: cb.setChecked(bool(v)))


def _build_spinbox(default: Any) -> _FieldWidget:
    sb = QSpinBox()
    sb.setRange(-1_000_000, 1_000_000)
    if isinstance(default, int):
        sb.setValue(default)
    return _FieldWidget(sb, sb.value, lambda v: sb.setValue(int(v) if v is not None else 0))


def _build_double_spinbox(default: Any) -> _FieldWidget:
    sb = QDoubleSpinBox()
    sb.setRange(-1_000_000.0, 1_000_000.0)
    sb.setDecimals(3)
    if isinstance(default, (int, float)):
        sb.setValue(float(default))
    return _FieldWidget(sb, sb.value, lambda v: sb.setValue(float(v) if v is not None else 0.0))


def _build_field(parameter: inspect.Parameter) -> _FieldWidget:
    """Return a ``_FieldWidget`` matched to ``parameter``'s annotation / name."""
    annotation = parameter.annotation
    default = parameter.default
    if annotation is bool:
        return _build_checkbox(default)
    if annotation is int:
        return _build_spinbox(default)
    if annotation is float:
        return _build_double_spinbox(default)
    secret = _is_secret_like(parameter.name)
    if _is_path_like(parameter.name):
        return _build_path_picker(default, secret)
    return _build_line_edit(default, secret)


class _ActionForm(QWidget):
    """Auto-generated form for one action's kwargs."""

    def __init__(self, name: str, callable_: Callable[..., Any]) -> None:
        super().__init__()
        self._name = name
        self._callable = callable_
        self._getters: dict[str, Callable[[], Any]] = {}
        self._setters: dict[str, Callable[[Any], None]] = {}
        self._required: set[str] = set()
        self._raw: QPlainTextEdit | None = None

        layout = QFormLayout(self)
        try:
            signature = inspect.signature(callable_)
        except (TypeError, ValueError):
            layout.addRow(QLabel(f"Cannot introspect {name} — edit kwargs as raw JSON below."))
            raw = QPlainTextEdit()
            raw.setPlaceholderText('{"key": "value"}')
            layout.addRow(raw)
            self._raw = raw
            return

        for param_name, parameter in signature.parameters.items():
            if param_name == "self" or parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            field = _build_field(parameter)
            label = param_name
            if parameter.default is inspect.Parameter.empty:
                label = f"{param_name} *"
                self._required.add(param_name)
            layout.addRow(label, field.widget)
            self._getters[param_name] = field.get_value
            self._setters[param_name] = field.set_value

    @property
    def action_name(self) -> str:
        return self._name

    def to_kwargs(self) -> dict[str, Any]:
        if self._raw is not None:
            text = self._raw.toPlainText().strip()
            if not text:
                return {}
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
        kwargs: dict[str, Any] = {}
        for name, getter in self._getters.items():
            value = getter()
            if value == "" and name not in self._required:
                continue
            kwargs[name] = value
        return kwargs

    def load_kwargs(self, kwargs: dict[str, Any]) -> None:
        if self._raw is not None:
            self._raw.setPlainText(json.dumps(kwargs, indent=2))
            return
        for name, value in kwargs.items():
            setter = self._setters.get(name)
            if setter is not None:
                setter(value)


class JSONEditorTab(BaseTab):
    """Tree + form editor for action lists, with a raw-JSON fallback."""

    def __init__(self, log, pool) -> None:
        super().__init__(log, pool)
        self._actions: list[list[Any]] = []
        self._current_form: _ActionForm | None = None
        self._current_form_row: int = -1
        self._suppress_sync = False
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        self.setAcceptDrops(True)

        self._action_list = QListWidget()
        self._action_list.currentRowChanged.connect(self._on_row_changed)

        self._form_stack = QStackedWidget()
        self._empty_label = QLabel("Select or add an action to edit its parameters.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._form_stack.addWidget(self._empty_label)

        self._raw_editor = QPlainTextEdit()
        self._raw_editor.setPlaceholderText('[\n  ["FA_create_dir", {"dir_path": "build"}]\n]')
        self._raw_editor.textChanged.connect(self._on_raw_changed)

        splitter = QSplitter()
        splitter.addWidget(self._build_left_pane())
        splitter.addWidget(self._build_right_pane())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        root = QVBoxLayout(self)
        root.addWidget(self._build_toolbar())
        root.addWidget(splitter)
        root.addWidget(self._build_run_bar())

        self._register_shortcuts()

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.make_button("Load JSON…", self._on_load))
        row.addWidget(self.make_button("Save JSON…", self._on_save))
        row.addWidget(self.make_button("Clear", self._on_clear))
        row.addStretch()
        self._raw_toggle = QCheckBox("Raw JSON")
        self._raw_toggle.toggled.connect(self._on_raw_toggled)
        row.addWidget(self._raw_toggle)
        return toolbar

    def _build_left_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Actions"))

        self._picker = QComboBox()
        self._picker.addItems(sorted(executor.registry.names()))
        layout.addWidget(self._picker)

        layout.addWidget(self._action_list)

        row = QHBoxLayout()
        row.addWidget(self.make_button("Add", self._on_add))
        row.addWidget(self.make_button("Duplicate", self._on_duplicate))
        row.addWidget(self.make_button("Remove", self._on_remove))
        layout.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(self.make_button("Up", lambda: self._on_move(-1)))
        row2.addWidget(self.make_button("Down", lambda: self._on_move(1)))
        layout.addLayout(row2)
        return pane

    def _build_right_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Parameters"))
        layout.addWidget(self._form_stack)
        layout.addWidget(self._raw_editor)
        self._raw_editor.hide()
        return pane

    def _build_run_bar(self) -> QWidget:
        box = QGroupBox("Run options")
        layout = QHBoxLayout(box)
        self._validate_first = QCheckBox("validate_first")
        self._dry_run = QCheckBox("dry_run")
        self._parallel = QCheckBox("parallel")
        self._workers = QSpinBox()
        self._workers.setRange(1, 32)
        self._workers.setValue(4)
        self._workers.setPrefix("workers=")
        layout.addWidget(self._validate_first)
        layout.addWidget(self._dry_run)
        layout.addWidget(self._parallel)
        layout.addWidget(self._workers)
        layout.addStretch()
        layout.addWidget(self.make_button("Validate", self._on_validate))
        layout.addWidget(self.make_button("Run", self._on_run))
        return box

    def _on_add(self) -> None:
        name = self._picker.currentText()
        if not name:
            return
        self._commit_current_form()
        self._actions.append([name, {}])
        self._refresh_list(select=len(self._actions) - 1)
        self._sync_raw_from_model()

    def _on_duplicate(self) -> None:
        row = self._action_list.currentRow()
        if row < 0:
            return
        self._commit_current_form()
        self._actions.insert(row + 1, json.loads(json.dumps(self._actions[row])))
        self._refresh_list(select=row + 1)
        self._sync_raw_from_model()

    def _on_remove(self) -> None:
        row = self._action_list.currentRow()
        if row < 0:
            return
        del self._actions[row]
        self._clear_current_form()
        self._refresh_list(select=min(row, len(self._actions) - 1))
        self._sync_raw_from_model()

    def _on_move(self, delta: int) -> None:
        row = self._action_list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < len(self._actions):
            return
        self._commit_current_form()
        self._actions[row], self._actions[target] = self._actions[target], self._actions[row]
        self._refresh_list(select=target)
        self._sync_raw_from_model()

    def _on_row_changed(self, row: int) -> None:
        self._commit_current_form()
        self._clear_current_form()
        if row < 0 or row >= len(self._actions):
            self._form_stack.setCurrentWidget(self._empty_label)
            return
        name, kwargs = self._unpack_action(self._actions[row])
        callable_ = executor.registry.resolve(name)
        if callable_ is None:
            self._form_stack.setCurrentWidget(self._empty_label)
            self._log.append_line(f"unknown action: {name}")
            return
        form = _ActionForm(name, callable_)
        form.load_kwargs(kwargs)
        self._form_stack.addWidget(form)
        self._form_stack.setCurrentWidget(form)
        self._current_form = form
        self._current_form_row = row

    def _commit_current_form(self) -> None:
        if self._current_form is None:
            return
        row = self._current_form_row
        if row < 0 or row >= len(self._actions):
            return
        self._actions[row] = [self._current_form.action_name, self._current_form.to_kwargs()]
        item = self._action_list.item(row)
        if item is not None:
            item.setText(self._summary_for(self._actions[row]))

    def _clear_current_form(self) -> None:
        if self._current_form is not None:
            self._form_stack.removeWidget(self._current_form)
            self._current_form.deleteLater()
        self._current_form = None
        self._current_form_row = -1

    def _refresh_list(self, select: int | None = None) -> None:
        self._action_list.blockSignals(True)
        self._action_list.clear()
        for action in self._actions:
            self._action_list.addItem(QListWidgetItem(self._summary_for(action)))
        self._action_list.blockSignals(False)
        if select is not None and 0 <= select < len(self._actions):
            self._action_list.setCurrentRow(select)
        elif not self._actions:
            self._on_row_changed(-1)

    def _summary_for(self, action: list[Any]) -> str:
        name, kwargs = self._unpack_action(action)
        if not kwargs:
            return name
        preview = ", ".join(f"{k}={v!r}" for k, v in list(kwargs.items())[:2])
        return f"{name}({preview})"

    @staticmethod
    def _unpack_action(action: list[Any]) -> tuple[str, dict[str, Any]]:
        if not action:
            return "", {}
        name = str(action[0])
        if len(action) < 2:
            return name, {}
        payload = action[1]
        if isinstance(payload, dict):
            return name, payload
        return name, {}

    def _on_load(self) -> None:
        start_dir = str(self._settings.value(_LAST_JSON_DIR_KEY, ""))
        path, _ = QFileDialog.getOpenFileName(
            self, "Load action JSON", start_dir, filter="JSON (*.json)"
        )
        if not path:
            return
        self._load_path(path)

    def _load_path(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError) as error:
            self._log.append_line(f"load error: {error}")
            return
        if not isinstance(data, list):
            self._log.append_line("load error: top-level JSON must be an array")
            return
        self._actions = data
        self._settings.setValue(_LAST_JSON_DIR_KEY, str(Path(path).parent))
        self._clear_current_form()
        self._refresh_list(select=0 if data else None)
        self._sync_raw_from_model()
        self._log.append_line(f"loaded {len(data)} actions from {path}")

    def _on_save(self) -> None:
        self._commit_current_form()
        start_dir = str(self._settings.value(_LAST_JSON_DIR_KEY, ""))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save action JSON", start_dir, filter="JSON (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(self._actions, fp, indent=2)
        except OSError as error:
            self._log.append_line(f"save error: {error}")
            return
        self._settings.setValue(_LAST_JSON_DIR_KEY, str(Path(path).parent))
        self._log.append_line(f"saved {len(self._actions)} actions to {path}")

    def _on_clear(self) -> None:
        self._actions = []
        self._clear_current_form()
        self._refresh_list(select=None)
        self._sync_raw_from_model()

    def _on_raw_toggled(self, on: bool) -> None:
        if on:
            self._commit_current_form()
            self._sync_raw_from_model()
            self._raw_editor.show()
            self._form_stack.hide()
        else:
            self._raw_editor.hide()
            self._form_stack.show()

    def _on_raw_changed(self) -> None:
        if self._suppress_sync or not self._raw_toggle.isChecked():
            return
        text = self._raw_editor.toPlainText().strip()
        if not text:
            self._actions = []
            self._refresh_list(select=None)
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return
        if not isinstance(data, list):
            return
        self._actions = data
        self._refresh_list(select=0 if data else None)

    def _sync_raw_from_model(self) -> None:
        self._suppress_sync = True
        try:
            self._raw_editor.setPlainText(json.dumps(self._actions, indent=2))
        finally:
            self._suppress_sync = False

    def _current_actions(self) -> list[list[Any]]:
        self._commit_current_form()
        return self._actions

    def _on_run(self) -> None:
        actions = self._current_actions()
        if not actions:
            self._log.append_line("no actions to run")
            return
        if self._parallel.isChecked():
            self.run_action(
                execute_action_parallel,
                f"execute_action_parallel({len(actions)})",
                kwargs={"action_list": actions, "max_workers": int(self._workers.value())},
            )
            return
        self.run_action(
            execute_action,
            f"execute_action({len(actions)})",
            kwargs={
                "action_list": actions,
                "validate_first": self._validate_first.isChecked(),
                "dry_run": self._dry_run.isChecked(),
            },
        )

    def _on_validate(self) -> None:
        actions = self._current_actions()
        if not actions:
            self._log.append_line("no actions to validate")
            return
        self.run_action(
            validate_action,
            f"validate_action({len(actions)})",
            kwargs={"action_list": actions},
        )

    def _register_shortcuts(self) -> None:
        for keys, handler in (
            ("Ctrl+O", self._on_load),
            ("Ctrl+S", self._on_save),
            ("Ctrl+R", self._on_run),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        if self._is_json_drop(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        if not self._is_json_drop(event):
            event.ignore()
            return
        url = event.mimeData().urls()[0]
        self._load_path(url.toLocalFile())
        event.acceptProposedAction()

    @staticmethod
    def _is_json_drop(event: QDragEnterEvent | QDropEvent) -> bool:
        mime = event.mimeData()
        if not mime.hasUrls():
            return False
        urls = mime.urls()
        if not urls:
            return False
        local = urls[0].toLocalFile()
        return bool(local) and local.lower().endswith(".json")
