"""Tests for automation_file.local.data_ops (CSV + JSONL)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_file import (
    DataOpsException,
    build_default_registry,
    csv_filter,
    csv_to_jsonl,
    jsonl_append,
    jsonl_iter,
)
from automation_file.exceptions import FileNotExistsException


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")


def test_csv_filter_passthrough(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    _write_csv(src, [["id", "name"], ["1", "alice"], ["2", "bob"]])
    dest = tmp_path / "b.csv"
    assert csv_filter(str(src), str(dest)) == 2
    assert dest.read_text(encoding="utf-8").splitlines() == ["id,name", "1,alice", "2,bob"]


def test_csv_filter_projects_columns(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    _write_csv(src, [["id", "name", "team"], ["1", "alice", "red"], ["2", "bob", "blue"]])
    dest = tmp_path / "b.csv"
    csv_filter(str(src), str(dest), columns=["name", "id"])
    assert dest.read_text(encoding="utf-8").splitlines() == ["name,id", "alice,1", "bob,2"]


def test_csv_filter_where_clause(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    _write_csv(src, [["id", "team"], ["1", "red"], ["2", "blue"], ["3", "red"]])
    dest = tmp_path / "b.csv"
    written = csv_filter(str(src), str(dest), where_column="team", where_equals="red")
    assert written == 2
    assert dest.read_text(encoding="utf-8").splitlines() == ["id,team", "1,red", "3,red"]


def test_csv_filter_rejects_unknown_column(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    _write_csv(src, [["id"], ["1"]])
    with pytest.raises(DataOpsException):
        csv_filter(str(src), str(tmp_path / "b.csv"), columns=["missing"])


def test_csv_filter_requires_paired_where(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    _write_csv(src, [["id"], ["1"]])
    with pytest.raises(DataOpsException):
        csv_filter(str(src), str(tmp_path / "b.csv"), where_column="id")


def test_csv_filter_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotExistsException):
        csv_filter(str(tmp_path / "gone.csv"), str(tmp_path / "out.csv"))


def test_csv_to_jsonl_basic(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    _write_csv(src, [["id", "name"], ["1", "alice"], ["2", "bob"]])
    dest = tmp_path / "a.jsonl"
    assert csv_to_jsonl(str(src), str(dest)) == 2
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"id": "1", "name": "alice"}
    assert json.loads(lines[1]) == {"id": "2", "name": "bob"}


def test_jsonl_iter_parses_records(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(
        '{"a": 1}\n'
        "\n"  # blank line should be skipped
        '{"a": 2}\n',
        encoding="utf-8",
    )
    records = jsonl_iter(str(path))
    assert records == [{"a": 1}, {"a": 2}]


def test_jsonl_iter_respects_limit(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text('{"a":1}\n{"a":2}\n{"a":3}\n', encoding="utf-8")
    assert jsonl_iter(str(path), limit=2) == [{"a": 1}, {"a": 2}]


def test_jsonl_iter_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text('{"a":1}\n["not","object"]\n', encoding="utf-8")
    with pytest.raises(DataOpsException):
        jsonl_iter(str(path))


def test_jsonl_iter_rejects_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text("{bad\n", encoding="utf-8")
    with pytest.raises(DataOpsException):
        jsonl_iter(str(path))


def test_jsonl_append_appends(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    assert jsonl_append(str(path), {"a": 1}) is True
    assert jsonl_append(str(path), {"a": 2}) is True
    assert jsonl_iter(str(path)) == [{"a": 1}, {"a": 2}]


def test_jsonl_append_rejects_non_dict(tmp_path: Path) -> None:
    with pytest.raises(DataOpsException):
        jsonl_append(str(tmp_path / "x.jsonl"), ["not", "a", "dict"])  # type: ignore[arg-type]


def test_data_ops_registered() -> None:
    registry = build_default_registry()
    for name in ("FA_csv_filter", "FA_csv_to_jsonl", "FA_jsonl_iter", "FA_jsonl_append"):
        assert name in registry
