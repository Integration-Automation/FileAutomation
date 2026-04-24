"""Tests for automation_file.local.data_ops YAML + Parquet helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file import (
    DataOpsException,
    build_default_registry,
    csv_to_parquet,
    parquet_read,
    parquet_write,
    yaml_delete,
    yaml_get,
    yaml_set,
)
from automation_file.exceptions import FileNotExistsException

# --- YAML -----------------------------------------------------------------


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_yaml_get_nested(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    _write_yaml(path, "a:\n  b:\n    c: 42\n")
    assert yaml_get(str(path), "a.b.c") == 42


def test_yaml_get_missing_returns_default(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    _write_yaml(path, "root: 1\n")
    assert yaml_get(str(path), "missing.key", default="fallback") == "fallback"


def test_yaml_get_list_index(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    _write_yaml(path, "items:\n  - a\n  - b\n  - c\n")
    assert yaml_get(str(path), "items.1") == "b"


def test_yaml_set_creates_intermediate_dicts(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    _write_yaml(path, "existing: kept\n")
    yaml_set(str(path), "new.nested.key", "value")
    assert yaml_get(str(path), "new.nested.key") == "value"
    assert yaml_get(str(path), "existing") == "kept"


def test_yaml_set_rejects_empty_key_path(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    _write_yaml(path, "a: 1\n")
    with pytest.raises(DataOpsException):
        yaml_set(str(path), "", "x")


def test_yaml_delete_returns_true_when_removed(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    _write_yaml(path, "a:\n  b: 1\n  c: 2\n")
    assert yaml_delete(str(path), "a.b") is True
    assert yaml_get(str(path), "a.b") is None
    assert yaml_get(str(path), "a.c") == 2


def test_yaml_delete_returns_false_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    _write_yaml(path, "a: 1\n")
    assert yaml_delete(str(path), "nope") is False


def test_yaml_load_rejects_malformed(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    _write_yaml(path, "a: [unterminated\n")
    with pytest.raises(DataOpsException):
        yaml_get(str(path), "a")


def test_yaml_handles_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotExistsException):
        yaml_get(str(tmp_path / "gone.yaml"), "a")


# --- Parquet --------------------------------------------------------------


def test_parquet_write_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    records = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    assert parquet_write(str(path), records) == 2
    assert parquet_read(str(path)) == records


def test_parquet_read_respects_limit(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    parquet_write(str(path), [{"i": n} for n in range(5)])
    assert parquet_read(str(path), limit=2) == [{"i": 0}, {"i": 1}]


def test_parquet_read_projects_columns(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    parquet_write(str(path), [{"id": 1, "name": "alice", "team": "red"}])
    assert parquet_read(str(path), columns=["id", "team"]) == [{"id": 1, "team": "red"}]


def test_parquet_write_rejects_non_list(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    with pytest.raises(DataOpsException):
        parquet_write(str(path), {"not": "a list"})  # type: ignore[arg-type]


def test_parquet_read_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotExistsException):
        parquet_read(str(tmp_path / "gone.parquet"))


def test_csv_to_parquet_roundtrip(tmp_path: Path) -> None:
    csv_path = tmp_path / "a.csv"
    csv_path.write_text("id,name\n1,alice\n2,bob\n", encoding="utf-8")
    parquet_path = tmp_path / "a.parquet"
    assert csv_to_parquet(str(csv_path), str(parquet_path)) == 2
    assert parquet_read(str(parquet_path)) == [
        {"id": "1", "name": "alice"},
        {"id": "2", "name": "bob"},
    ]


def test_yaml_parquet_actions_registered() -> None:
    registry = build_default_registry()
    for name in (
        "FA_yaml_get",
        "FA_yaml_set",
        "FA_yaml_delete",
        "FA_parquet_read",
        "FA_parquet_write",
        "FA_csv_to_parquet",
    ):
        assert name in registry
