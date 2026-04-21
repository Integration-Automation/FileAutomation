"""Local filesystem / ZIP operations tab.

One operation visible at a time — a dropdown at the top selects an
action, and only that action's fields (plus its Run button) are shown
below. Avoids the "every field at once" wall of inputs that the flat
form layout produced.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from automation_file.local.dir_ops import copy_dir, create_dir, remove_dir_tree, rename_dir
from automation_file.local.file_ops import (
    copy_file,
    create_file,
    remove_file,
    rename_file,
)
from automation_file.local.zip_ops import unzip_all, zip_dir, zip_file
from automation_file.ui.tabs.base import BaseTab

_GROUP_SEPARATOR = "——"


class _ActionEntry(NamedTuple):
    group: str
    label: str
    build: Callable[[LocalOpsTab], QWidget]


class LocalOpsTab(BaseTab):
    """Dropdown-driven local file, directory, and ZIP operations."""

    def __init__(self, log, pool) -> None:
        super().__init__(log, pool)

        entries = self._entries()
        self._picker = QComboBox()
        self._stack = QStackedWidget()

        previous_group: str | None = None
        for entry in entries:
            if previous_group is not None and entry.group != previous_group:
                self._picker.insertSeparator(self._picker.count())
            self._picker.addItem(f"{entry.group}  {_GROUP_SEPARATOR}  {entry.label}")
            self._stack.addWidget(entry.build(self))
            previous_group = entry.group

        self._picker.currentIndexChanged.connect(self._on_picker_changed)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._picker)
        root.addWidget(self._stack, 1)
        root.addStretch()

    def _entries(self) -> list[_ActionEntry]:
        return [
            _ActionEntry("Files", "Create file", LocalOpsTab._page_create_file),
            _ActionEntry("Files", "Copy file", LocalOpsTab._page_copy_file),
            _ActionEntry("Files", "Rename file", LocalOpsTab._page_rename_file),
            _ActionEntry("Files", "Delete file", LocalOpsTab._page_delete_file),
            _ActionEntry("Directories", "Create directory", LocalOpsTab._page_create_dir),
            _ActionEntry("Directories", "Copy directory", LocalOpsTab._page_copy_dir),
            _ActionEntry("Directories", "Rename directory", LocalOpsTab._page_rename_dir),
            _ActionEntry("Directories", "Delete directory tree", LocalOpsTab._page_remove_dir),
            _ActionEntry("ZIP", "Zip file", LocalOpsTab._page_zip_file),
            _ActionEntry("ZIP", "Zip directory", LocalOpsTab._page_zip_dir),
            _ActionEntry("ZIP", "Unzip archive", LocalOpsTab._page_unzip),
        ]

    def _on_picker_changed(self, index: int) -> None:
        # Skip over inserted separators — QComboBox.itemData returns None for them.
        if index < 0:
            return
        stack_index = self._stack_index_for(index)
        if stack_index is None:
            return
        self._stack.setCurrentIndex(stack_index)

    def _stack_index_for(self, picker_index: int) -> int | None:
        """Translate a combobox row (which may include separators) to a stack index."""
        seen = 0
        for i in range(picker_index + 1):
            if self._picker.itemText(i) == "":  # separator rows have empty text
                continue
            if i == picker_index:
                return seen
            seen += 1
        return None

    # ----- page builders -----------------------------------------------------

    @staticmethod
    def _form_page() -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(4, 4, 4, 4)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)
        return page, form

    def _page_create_file(self) -> QWidget:
        page, form = self._form_page()
        self._create_path = QLineEdit()
        self._create_content = QTextEdit()
        self._create_content.setPlaceholderText("Optional file content")
        form.addRow("Path", self._create_path)
        form.addRow("Content", self._create_content)
        form.addRow(self._run_button("Create file", self._on_create_file))
        return page

    def _page_copy_file(self) -> QWidget:
        page, form = self._form_page()
        self._copy_src = QLineEdit()
        self._copy_dst = QLineEdit()
        form.addRow("Source", self._copy_src)
        form.addRow("Target", self._copy_dst)
        form.addRow(self._run_button("Copy file", self._on_copy_file))
        return page

    def _page_rename_file(self) -> QWidget:
        page, form = self._form_page()
        self._rename_src = QLineEdit()
        self._rename_dst = QLineEdit()
        form.addRow("Source", self._rename_src)
        form.addRow("New name", self._rename_dst)
        form.addRow(self._run_button("Rename file", self._on_rename_file))
        return page

    def _page_delete_file(self) -> QWidget:
        page, form = self._form_page()
        self._remove_path = QLineEdit()
        form.addRow("Path", self._remove_path)
        form.addRow(self._run_button("Delete file", self._on_remove_file))
        return page

    def _page_create_dir(self) -> QWidget:
        page, form = self._form_page()
        self._dir_create = QLineEdit()
        form.addRow("Path", self._dir_create)
        form.addRow(self._run_button("Create directory", self._on_create_dir))
        return page

    def _page_copy_dir(self) -> QWidget:
        page, form = self._form_page()
        self._dir_copy_src = QLineEdit()
        self._dir_copy_dst = QLineEdit()
        form.addRow("Source", self._dir_copy_src)
        form.addRow("Target", self._dir_copy_dst)
        form.addRow(self._run_button("Copy directory", self._on_copy_dir))
        return page

    def _page_rename_dir(self) -> QWidget:
        page, form = self._form_page()
        self._dir_rename_src = QLineEdit()
        self._dir_rename_dst = QLineEdit()
        form.addRow("Source", self._dir_rename_src)
        form.addRow("New name", self._dir_rename_dst)
        form.addRow(self._run_button("Rename directory", self._on_rename_dir))
        return page

    def _page_remove_dir(self) -> QWidget:
        page, form = self._form_page()
        self._dir_remove = QLineEdit()
        form.addRow("Path", self._dir_remove)
        form.addRow(self._run_button("Delete directory tree", self._on_remove_dir))
        return page

    def _page_zip_file(self) -> QWidget:
        page, form = self._form_page()
        self._zip_file_path = QLineEdit()
        self._zip_file_name = QLineEdit()
        form.addRow("File to compress", self._zip_file_path)
        form.addRow("Archive name (no .zip)", self._zip_file_name)
        form.addRow(self._run_button("Zip file", self._on_zip_file))
        return page

    def _page_zip_dir(self) -> QWidget:
        page, form = self._form_page()
        self._zip_dir_path = QLineEdit()
        self._zip_dir_name = QLineEdit()
        form.addRow("Directory to compress", self._zip_dir_path)
        form.addRow("Archive name (no .zip)", self._zip_dir_name)
        form.addRow(self._run_button("Zip directory", self._on_zip_dir))
        return page

    def _page_unzip(self) -> QWidget:
        page, form = self._form_page()
        self._unzip_archive = QLineEdit()
        self._unzip_target = QLineEdit()
        self._unzip_target.setPlaceholderText("leave blank to extract next to the archive")
        form.addRow("Archive", self._unzip_archive)
        form.addRow("Extract to", self._unzip_target)
        form.addRow(self._run_button("Unzip archive", self._on_unzip_all))
        return page

    @staticmethod
    def _run_button(label: str, handler: Callable[[], None]) -> QPushButton:
        button = QPushButton(label)
        button.clicked.connect(handler)
        return button

    # ----- handlers ----------------------------------------------------------

    def _on_create_file(self) -> None:
        path = self._create_path.text().strip()
        content = self._create_content.toPlainText()
        self.run_action(
            create_file,
            f"create_file {path}",
            kwargs={"file_path": path, "content": content},
        )

    def _on_copy_file(self) -> None:
        src, dst = self._copy_src.text().strip(), self._copy_dst.text().strip()
        self.run_action(
            copy_file,
            f"copy_file {src} -> {dst}",
            kwargs={"file_path": src, "target_path": dst},
        )

    def _on_rename_file(self) -> None:
        src, dst = self._rename_src.text().strip(), self._rename_dst.text().strip()
        self.run_action(
            rename_file,
            f"rename_file {src} -> {dst}",
            kwargs={"origin_file_path": src, "target_name": dst},
        )

    def _on_remove_file(self) -> None:
        path = self._remove_path.text().strip()
        self.run_action(remove_file, f"remove_file {path}", kwargs={"file_path": path})

    def _on_create_dir(self) -> None:
        path = self._dir_create.text().strip()
        self.run_action(create_dir, f"create_dir {path}", kwargs={"dir_path": path})

    def _on_copy_dir(self) -> None:
        src, dst = self._dir_copy_src.text().strip(), self._dir_copy_dst.text().strip()
        self.run_action(
            copy_dir,
            f"copy_dir {src} -> {dst}",
            kwargs={"dir_path": src, "target_dir_path": dst},
        )

    def _on_rename_dir(self) -> None:
        src, dst = self._dir_rename_src.text().strip(), self._dir_rename_dst.text().strip()
        self.run_action(
            rename_dir,
            f"rename_dir {src} -> {dst}",
            kwargs={"origin_dir_path": src, "target_dir": dst},
        )

    def _on_remove_dir(self) -> None:
        path = self._dir_remove.text().strip()
        self.run_action(remove_dir_tree, f"remove_dir_tree {path}", kwargs={"dir_path": path})

    def _on_zip_file(self) -> None:
        path = self._zip_file_path.text().strip()
        name = self._zip_file_name.text().strip()
        archive = name if name.endswith(".zip") else f"{name}.zip"
        self.run_action(
            zip_file,
            f"zip_file {path} -> {archive}",
            kwargs={"zip_file_path": archive, "file": path},
        )

    def _on_zip_dir(self) -> None:
        path = self._zip_dir_path.text().strip()
        name = self._zip_dir_name.text().strip()
        self.run_action(
            zip_dir,
            f"zip_dir {path} -> {name}.zip",
            kwargs={"dir_we_want_to_zip": path, "zip_name": name},
        )

    def _on_unzip_all(self) -> None:
        archive = self._unzip_archive.text().strip()
        target = self._unzip_target.text().strip() or None
        self.run_action(
            unzip_all,
            f"unzip_all {archive} -> {target}",
            kwargs={"zip_file_path": archive, "extract_path": target},
        )
