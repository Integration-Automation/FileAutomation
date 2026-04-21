"""Project skeleton builder (Builder pattern)."""
from __future__ import annotations

from os import getcwd
from pathlib import Path

from automation_file.core.json_store import write_action_json
from automation_file.logging_config import file_automation_logger
from automation_file.project.templates import (
    EXECUTOR_FOLDER_TEMPLATE,
    EXECUTOR_ONE_FILE_TEMPLATE,
    KEYWORD_CREATE_TEMPLATE,
    KEYWORD_TEARDOWN_TEMPLATE,
)

_KEYWORD_DIR = "keyword"
_EXECUTOR_DIR = "executor"


class ProjectBuilder:
    """Create a ``keyword/`` + ``executor/`` skeleton under ``project_root``."""

    def __init__(self, project_root: str | None = None, parent_name: str = "FileAutomation") -> None:
        self.project_root: Path = Path(project_root or getcwd())
        self.parent: Path = self.project_root / parent_name
        self.keyword_dir: Path = self.parent / _KEYWORD_DIR
        self.executor_dir: Path = self.parent / _EXECUTOR_DIR

    def build(self) -> None:
        self.keyword_dir.mkdir(parents=True, exist_ok=True)
        self.executor_dir.mkdir(parents=True, exist_ok=True)
        self._write_keyword_files()
        self._write_executor_files()
        file_automation_logger.info("ProjectBuilder: built %s", self.parent)

    def _write_keyword_files(self) -> None:
        write_action_json(
            str(self.keyword_dir / "keyword_create.json"), KEYWORD_CREATE_TEMPLATE,
        )
        write_action_json(
            str(self.keyword_dir / "keyword_teardown.json"), KEYWORD_TEARDOWN_TEMPLATE,
        )

    def _write_executor_files(self) -> None:
        (self.executor_dir / "executor_one_file.py").write_text(
            EXECUTOR_ONE_FILE_TEMPLATE.format(
                keyword_json=str(self.keyword_dir / "keyword_create.json")
            ),
            encoding="utf-8",
        )
        (self.executor_dir / "executor_folder.py").write_text(
            EXECUTOR_FOLDER_TEMPLATE.format(keyword_dir=str(self.keyword_dir)),
            encoding="utf-8",
        )


def create_project_dir(
    project_path: str | None = None, parent_name: str = "FileAutomation"
) -> None:
    """Create a project skeleton (module-level shim)."""
    ProjectBuilder(project_root=project_path, parent_name=parent_name).build()
