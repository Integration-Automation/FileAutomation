"""Local filesystem / ZIP operations tab."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
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


class LocalOpsTab(BaseTab):
    """Form-driven local file, directory, and ZIP operations."""

    def __init__(self, log, pool) -> None:
        super().__init__(log, pool)
        root = QVBoxLayout(self)
        root.addWidget(self._file_group())
        root.addWidget(self._dir_group())
        root.addWidget(self._zip_group())
        root.addStretch()

    def _file_group(self) -> QGroupBox:
        box = QGroupBox("Files")
        form = QFormLayout(box)

        self._create_path = QLineEdit()
        self._create_content = QTextEdit()
        self._create_content.setPlaceholderText("Optional file content")
        form.addRow("Path", self._create_path)
        form.addRow("Content", self._create_content)
        create_btn = QPushButton("Create file")
        create_btn.clicked.connect(self._on_create_file)
        form.addRow(create_btn)

        self._copy_src = QLineEdit()
        self._copy_dst = QLineEdit()
        form.addRow("Copy source", self._copy_src)
        form.addRow("Copy target", self._copy_dst)
        copy_btn = QPushButton("Copy file")
        copy_btn.clicked.connect(self._on_copy_file)
        form.addRow(copy_btn)

        self._rename_src = QLineEdit()
        self._rename_dst = QLineEdit()
        form.addRow("Rename source", self._rename_src)
        form.addRow("Rename target", self._rename_dst)
        rename_btn = QPushButton("Rename file")
        rename_btn.clicked.connect(self._on_rename_file)
        form.addRow(rename_btn)

        self._remove_path = QLineEdit()
        form.addRow("Remove file", self._remove_path)
        remove_btn = QPushButton("Delete file")
        remove_btn.clicked.connect(self._on_remove_file)
        form.addRow(remove_btn)
        return box

    def _dir_group(self) -> QGroupBox:
        box = QGroupBox("Directories")
        form = QFormLayout(box)
        self._dir_create = QLineEdit()
        form.addRow("Create dir", self._dir_create)
        form.addRow(self._button("Create", self._on_create_dir))

        self._dir_copy_src = QLineEdit()
        self._dir_copy_dst = QLineEdit()
        form.addRow("Copy source", self._dir_copy_src)
        form.addRow("Copy target", self._dir_copy_dst)
        form.addRow(self._button("Copy dir", self._on_copy_dir))

        self._dir_rename_src = QLineEdit()
        self._dir_rename_dst = QLineEdit()
        form.addRow("Rename source", self._dir_rename_src)
        form.addRow("Rename target", self._dir_rename_dst)
        form.addRow(self._button("Rename dir", self._on_rename_dir))

        self._dir_remove = QLineEdit()
        form.addRow("Remove tree", self._dir_remove)
        form.addRow(self._button("Delete dir tree", self._on_remove_dir))
        return box

    def _zip_group(self) -> QGroupBox:
        box = QGroupBox("ZIP")
        form = QFormLayout(box)
        self._zip_target = QLineEdit()
        self._zip_name = QLineEdit()
        form.addRow("Path (file or dir)", self._zip_target)
        form.addRow("Archive name (no .zip)", self._zip_name)
        form.addRow(self._button("Zip file", self._on_zip_file))
        form.addRow(self._button("Zip directory", self._on_zip_dir))

        self._unzip_archive = QLineEdit()
        self._unzip_target = QLineEdit()
        form.addRow("Archive", self._unzip_archive)
        form.addRow("Extract to", self._unzip_target)
        form.addRow(self._button("Unzip all", self._on_unzip_all))
        return box

    @staticmethod
    def _button(label: str, handler) -> QPushButton:
        button = QPushButton(label)
        button.clicked.connect(handler)
        return button

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
        path = self._zip_target.text().strip()
        name = self._zip_name.text().strip()
        archive = name if name.endswith(".zip") else f"{name}.zip"
        self.run_action(
            zip_file,
            f"zip_file {path} -> {archive}",
            kwargs={"zip_file_path": archive, "file": path},
        )

    def _on_zip_dir(self) -> None:
        path = self._zip_target.text().strip()
        name = self._zip_name.text().strip()
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
