"""JSON action list runner — executes arbitrary ``FA_*`` batches."""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from automation_file.core.action_executor import (
    execute_action,
    execute_action_parallel,
    validate_action,
)
from automation_file.ui.tabs.base import BaseTab

_EXAMPLE = (
    "[\n"
    '    ["FA_create_dir", {"dir_path": "build"}],\n'
    '    ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}]\n'
    "]\n"
)


class ActionRunnerTab(BaseTab):
    """Paste a JSON action list and dispatch it through the shared executor."""

    def __init__(self, log, pool) -> None:
        super().__init__(log, pool)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("JSON action list"))
        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText(_EXAMPLE)
        root.addWidget(self._editor)

        options = QHBoxLayout()
        self._validate_first = QCheckBox("validate_first")
        self._dry_run = QCheckBox("dry_run")
        self._parallel = QCheckBox("parallel")
        self._workers = QSpinBox()
        self._workers.setRange(1, 32)
        self._workers.setValue(4)
        self._workers.setPrefix("workers=")
        options.addWidget(self._validate_first)
        options.addWidget(self._dry_run)
        options.addWidget(self._parallel)
        options.addWidget(self._workers)
        options.addStretch()
        root.addLayout(options)

        buttons = QHBoxLayout()
        run_btn = QPushButton("Run")
        run_btn.clicked.connect(self._on_run)
        validate_btn = QPushButton("Validate only")
        validate_btn.clicked.connect(self._on_validate)
        buttons.addWidget(run_btn)
        buttons.addWidget(validate_btn)
        buttons.addStretch()
        root.addLayout(buttons)

    def _parsed_actions(self) -> list | None:
        text = self._editor.toPlainText().strip() or _EXAMPLE
        try:
            actions = json.loads(text)
        except json.JSONDecodeError as error:
            self._log.append_line(f"parse error: {error}")
            return None
        if not isinstance(actions, list):
            self._log.append_line("parse error: top-level JSON must be an array")
            return None
        return actions

    def _on_run(self) -> None:
        actions = self._parsed_actions()
        if actions is None:
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
        actions = self._parsed_actions()
        if actions is None:
            return
        self.run_action(
            validate_action,
            f"validate_action({len(actions)})",
            kwargs={"action_list": actions},
        )
