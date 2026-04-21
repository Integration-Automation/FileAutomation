"""Tests for automation_file.project.project_builder."""
from __future__ import annotations

from pathlib import Path

from automation_file.project.project_builder import ProjectBuilder, create_project_dir


def test_project_builder_creates_skeleton(tmp_path: Path) -> None:
    ProjectBuilder(project_root=str(tmp_path), parent_name="demo").build()
    root = tmp_path / "demo"
    assert (root / "keyword" / "keyword_create.json").is_file()
    assert (root / "keyword" / "keyword_teardown.json").is_file()
    assert (root / "executor" / "executor_one_file.py").is_file()
    assert (root / "executor" / "executor_folder.py").is_file()


def test_create_project_dir_shim(tmp_path: Path) -> None:
    create_project_dir(project_path=str(tmp_path), parent_name="demo2")
    assert (tmp_path / "demo2" / "keyword").is_dir()
    assert (tmp_path / "demo2" / "executor").is_dir()


def test_keyword_json_contains_valid_actions(tmp_path: Path) -> None:
    import json

    create_project_dir(project_path=str(tmp_path), parent_name="proj")
    payload = json.loads(
        (tmp_path / "proj" / "keyword" / "keyword_create.json").read_text(encoding="utf-8")
    )
    assert ["FA_create_dir", {"dir_path": "test_dir"}] in payload
