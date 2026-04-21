"""Tests for automation_file.utils.file_discovery."""

from __future__ import annotations

from pathlib import Path

from automation_file.utils.file_discovery import get_dir_files_as_list


def test_finds_json_files(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("[]", encoding="utf-8")
    (tmp_path / "b.json").write_text("[]", encoding="utf-8")
    (tmp_path / "c.txt").write_text("no", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "d.json").write_text("[]", encoding="utf-8")

    result = get_dir_files_as_list(str(tmp_path))
    names = sorted(Path(p).name for p in result)
    assert names == ["a.json", "b.json", "d.json"]


def test_extension_is_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "X.JSON").write_text("[]", encoding="utf-8")
    result = get_dir_files_as_list(str(tmp_path))
    assert len(result) == 1


def test_custom_extension_without_dot(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("a", encoding="utf-8")
    (tmp_path / "b.json").write_text("[]", encoding="utf-8")
    result = get_dir_files_as_list(str(tmp_path), default_search_file_extension="yaml")
    assert [Path(p).name for p in result] == ["a.yaml"]
