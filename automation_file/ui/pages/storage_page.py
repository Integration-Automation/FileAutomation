"""Storage page: the backends, whether each can be used, and the mounts."""

from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from automation_file.app import BackendStatus, StorageService
from automation_file.exceptions import FileAutomationException
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage, fill_table, make_table, selected_cell

_COLUMNS = ("Backend", "Kind", "Label", "Extra", "Installed", "Usable", "Detail")
_MOUNT_KIND = "mount"
#: Schemes whose root can be resolved without a bucket, a container or a session.
_ROOT_URIS = {"local": "local:///", "memory": "memory:///"}
_NAME_COLUMN = 0
_KIND_COLUMN = 1


class StoragePage(BasePage):
    """Shows every scheme, mount and shared client, and mounts a local directory."""

    title = "Storage"

    def __init__(self, service: StorageService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._backends: list[BackendStatus] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._backends_group(), 1)
        root.addWidget(self._mount_group())
        root.addWidget(self.status_label())

    def _backends_group(self) -> QGroupBox:
        box = QGroupBox("Backends")
        layout = QVBoxLayout(box)
        layout.addWidget(
            self.muted_label(
                "A cloud backend becomes usable once its client has been initialised: use the "
                "Credentials panel under Advanced, Transfer, or its FA_*_later_init action. "
                "When the package of its extra is missing, Detail shows the install command."
            )
        )
        self._table = make_table(_COLUMNS)
        self._table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self._table)
        self._capabilities = QLabel("Select a backend to see what it provides.")
        self._capabilities.setWordWrap(True)
        layout.addWidget(self._capabilities)
        row = QHBoxLayout()
        row.addWidget(self.make_button("Refresh", self.refresh))
        row.addWidget(self.make_button("Unmount selected", self.unmount_selected))
        row.addStretch()
        layout.addLayout(row)
        return box

    def _mount_group(self) -> QGroupBox:
        box = QGroupBox("Mount a local directory")
        form = QFormLayout(box)
        self._mount_uri = QLineEdit()
        self._mount_uri.setPlaceholderText("sandbox://jobs")
        self._mount_root = QLineEdit()
        self._mount_root.setPlaceholderText("an existing directory; the mount cannot leave it")
        root_row = QHBoxLayout()
        root_row.addWidget(self._mount_root, 1)
        root_row.addWidget(self.make_button("Browse…", self._on_browse))
        form.addRow("URI", self._mount_uri)
        form.addRow("Directory", root_row)
        form.addRow(self.make_button("Mount", self.mount_local))
        return box

    # ------------------------------------------------------------------ data

    def backends(self) -> list[BackendStatus]:
        """Return the statuses the table shows."""
        return list(self._backends)

    def refresh(self) -> None:
        self.run_async(
            self._service.backends, "read backends", self._show, key="refresh", quiet=True
        )

    def _show(self, backends: list[BackendStatus]) -> None:
        self._backends = backends
        fill_table(
            self._table,
            [
                [
                    status.name,
                    status.kind,
                    status.label,
                    status.extra,
                    status.installed,
                    status.usable,
                    status.detail,
                ]
                for status in backends
            ],
        )

    def _on_selection(self) -> None:
        name = selected_cell(self._table, _NAME_COLUMN)
        kind = selected_cell(self._table, _KIND_COLUMN)
        if name is None:
            return
        probe = name if kind == _MOUNT_KIND else _ROOT_URIS.get(name)
        if probe is None:
            self._capabilities.setText(
                f"{name}: what it provides depends on the bucket, container or session; "
                "open one of its URIs on the Files page."
            )
            return
        try:
            # Resolving a mount or the local root touches no network and no disk.
            found = self._service.capabilities(probe)
        except FileAutomationException as error:
            self._capabilities.setText(f"{name}: {error}")
            return
        provided = ", ".join(f"{key}: {'yes' if value else 'no'}" for key, value in found.items())
        self._capabilities.setText(f"{name} provides {provided}")

    # ------------------------------------------------------------------ mounts

    def _on_browse(self) -> None:
        chosen = self.pick_directory()
        if chosen:
            self._mount_root.setText(chosen)

    def mount_local(self) -> None:
        uri = self._mount_uri.text().strip()
        root = self._mount_root.text().strip()
        if not uri or not root:
            self.report_error("enter the URI to serve and the directory to serve it from")
            return
        self.run_async(
            lambda: self._service.mount_local(uri, root),
            f"mount {uri}",
            lambda mount: self._after_change(f"mounted {mount.uri} on {root}"),
        )

    def unmount_selected(self) -> None:
        name = selected_cell(self._table, _NAME_COLUMN)
        if name is None or selected_cell(self._table, _KIND_COLUMN) != _MOUNT_KIND:
            self.report_error("select a mount to unmount")
            return
        self.run_async(
            lambda: self._service.unmount(name),
            f"unmount {name}",
            lambda removed: self._after_change(
                f"unmounted {name}" if removed else f"{name} was not mounted"
            ),
        )

    def _after_change(self, message: str) -> None:
        self.report(message)
        self.refresh()
