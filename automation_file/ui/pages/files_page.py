"""Files page: browse a storage URI, preview a file, copy, move, delete, make a directory."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from automation_file.app import FileEntry, FilePreview, FileService
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage, fill_table, make_table

_COLUMNS = ("Name", "Type", "Size", "Modified")
_DIRECTORY = "directory"
_FILE = "file"


class FilesPage(BasePage):
    """A file manager over storage URIs; every operation goes through the Files service."""

    title = "Files"

    def __init__(self, service: FileService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._entries: list[FileEntry] = []
        self._current = ""
        self._note = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addLayout(self._location_row())
        splitter = QSplitter()
        splitter.addWidget(self._listing_group())
        splitter.addWidget(self._preview_group())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)
        root.addWidget(self._operations_group())
        root.addWidget(self.status_label())

    # ------------------------------------------------------------------ layout

    def _location_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._uri = QLineEdit()
        self._uri.setPlaceholderText(
            "storage URI or local path, e.g. local:///data, s3://bucket/reports, memory://demo"
        )
        self._uri.returnPressed.connect(self.open_location)
        row.addWidget(self._uri, 1)
        row.addWidget(self.make_button("Open", self.open_location))
        row.addWidget(self.make_button("Up", self.go_up))
        row.addWidget(self.make_button("Refresh", self.refresh))
        row.addWidget(self.make_button("Browse local…", self._on_browse))
        return row

    def _listing_group(self) -> QGroupBox:
        box = QGroupBox("Entries")
        layout = QVBoxLayout(box)
        self._table = make_table(_COLUMNS)
        self._table.cellDoubleClicked.connect(lambda _row, _column: self.open_selected())
        layout.addWidget(self._table)
        return box

    def _preview_group(self) -> QGroupBox:
        box = QGroupBox("Preview")
        layout = QVBoxLayout(box)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("Double-click a file, or select it and press Preview.")
        layout.addWidget(self._preview)
        layout.addWidget(self.make_button("Preview selected", self.preview_selected))
        return box

    def _operations_group(self) -> QWidget:
        box = QGroupBox("Operations on the selected entry")
        form = QFormLayout(box)
        self._target = QLineEdit()
        self._target.setPlaceholderText("target URI; an existing directory receives the file")
        self._overwrite = QCheckBox("Overwrite an existing target")
        self._overwrite.setChecked(True)
        transfer = QHBoxLayout()
        transfer.addWidget(self._target, 1)
        transfer.addWidget(self._overwrite)
        transfer.addWidget(self.make_button("Copy", self.copy_selected))
        transfer.addWidget(self.make_button("Move", self.move_selected))
        form.addRow("Copy / move to", transfer)

        self._folder = QLineEdit()
        self._folder.setPlaceholderText("name of a new directory below the current location")
        self._recursive = QCheckBox("Delete a directory with its contents")
        manage = QHBoxLayout()
        manage.addWidget(self._folder, 1)
        manage.addWidget(self.make_button("Create directory", self.create_directory))
        manage.addWidget(self._recursive)
        manage.addWidget(self.make_button("Delete selected", self.delete_selected))
        form.addRow("Manage", manage)
        return box

    # ------------------------------------------------------------------ navigation

    def location(self) -> str:
        """Return the URI the listing shows."""
        return self._current

    def entries(self) -> list[FileEntry]:
        """Return the entries the listing shows."""
        return list(self._entries)

    def refresh(self) -> None:
        if self._current:
            self._list(self._current)

    def open_location(self, uri: str | None = None) -> None:
        """List the URI in the location field, or ``uri`` when one is given."""
        wanted = (self._uri.text() if uri is None else uri).strip()
        if not wanted:
            self.report_error("enter a storage URI or a local path first")
            return
        self._list(wanted)

    def go_up(self) -> None:
        if self._current:
            self._list(self._service.parent(self._current))

    def open_selected(self) -> None:
        """Enter the selected directory, or preview the selected file."""
        entry = self.selected_entry()
        if entry is None:
            return
        if entry.is_dir:
            self._list(entry.uri)
        else:
            self._load_preview(entry.uri)

    def selected_entry(self) -> FileEntry | None:
        row = self._table.currentRow()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def select_entry(self, name: str) -> bool:
        """Select the entry called ``name``; return whether it is listed."""
        for row, entry in enumerate(self._entries):
            if entry.name == name:
                self._table.selectRow(row)
                return True
        return False

    def _on_browse(self) -> None:
        chosen = self.pick_directory()
        if chosen:
            self._list(chosen)

    def _list(self, uri: str) -> None:
        self.run_async(
            lambda: (self._service.normalize(uri), self._service.list_dir(uri)),
            f"list {uri}",
            self._show_listing,
            quiet=True,
        )

    def _show_listing(self, result: tuple[str, list[FileEntry]]) -> None:
        self._current, self._entries = result
        self._uri.setText(self._current)
        fill_table(
            self._table,
            [
                [
                    entry.name,
                    _DIRECTORY if entry.is_dir else _FILE,
                    None if entry.is_dir else entry.size,
                    entry.modified_at,
                ]
                for entry in self._entries
            ],
        )
        note, self._note = self._note, ""
        self.report(note or f"{len(self._entries)} entries in {self._current}")

    # ------------------------------------------------------------------ preview

    def preview_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.report_error("select a file to preview")
        elif entry.is_dir:
            self.report_error(f"{entry.name} is a directory; open it instead")
        else:
            self._load_preview(entry.uri)

    def preview_text(self) -> str:
        """Return what the preview pane shows."""
        return self._preview.toPlainText()

    def _load_preview(self, uri: str) -> None:
        self.run_async(
            lambda: self._service.preview(uri), f"preview {uri}", self._show_preview, quiet=True
        )

    def _show_preview(self, preview: FilePreview) -> None:
        self._preview.setPlainText(preview.text)
        parts = [f"{preview.shown} of {preview.size} bytes of {preview.uri}"]
        if preview.truncated:
            parts.append("truncated")
        if preview.note:
            parts.append(preview.note)
        self.report("; ".join(parts))

    # ------------------------------------------------------------------ operations

    def copy_selected(self) -> None:
        self._transfer("copy", self._service.copy)

    def move_selected(self) -> None:
        self._transfer("move", self._service.move)

    def _transfer(self, verb: str, operation: Callable[[str, str, bool], FileEntry]) -> None:
        entry = self.selected_entry()
        target = self._target.text().strip()
        if entry is None or not target:
            self.report_error(f"select an entry and enter a target URI to {verb} it")
            return
        overwrite = self._overwrite.isChecked()
        self.run_async(
            lambda: operation(entry.uri, target, overwrite),
            f"{verb} {entry.uri} to {target}",
            lambda done: self._after_change(f"{verb}: {entry.uri} -> {done.uri}"),
        )

    def create_directory(self) -> None:
        name = self._folder.text().strip()
        if not self._current or not name:
            self.report_error("open a location and enter a directory name first")
            return
        self.run_async(
            lambda: self._make_directory(name),
            f"create directory {name}",
            lambda uri: self._after_change(f"created {uri}"),
        )

    def _make_directory(self, name: str) -> str:
        uri = self._service.child(self._current, name)
        self._service.mkdir(uri)
        return uri

    def delete_selected(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.report_error("select an entry to delete")
            return
        if not self.confirm(f"Delete {entry.uri}? This cannot be undone."):
            return
        recursive = self._recursive.isChecked()
        self.run_async(
            lambda: self._service.delete(entry.uri, recursive),
            f"delete {entry.uri}",
            lambda _done: self._after_change(f"deleted {entry.uri}"),
        )

    def _after_change(self, message: str) -> None:
        if not self._current:
            self.report(message)
            return
        self._note = message
        self.refresh()
