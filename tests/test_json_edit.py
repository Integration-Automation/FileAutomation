from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_file import (
    JsonEditException,
    build_default_registry,
    json_delete,
    json_get,
    json_set,
)


@pytest.fixture
def sample_json(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {"a": {"b": {"c": 1}}, "list": [10, 20, 30], "top": "level"},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def test_json_get_nested(sample_json: Path) -> None:
    assert json_get(str(sample_json), "a.b.c") == 1


def test_json_get_missing_returns_default(sample_json: Path) -> None:
    assert json_get(str(sample_json), "a.b.missing", default=42) == 42


def test_json_get_list_index(sample_json: Path) -> None:
    assert json_get(str(sample_json), "list.1") == 20


def test_json_set_nested(sample_json: Path) -> None:
    assert json_set(str(sample_json), "a.b.c", 99) is True
    assert json.loads(sample_json.read_text(encoding="utf-8"))["a"]["b"]["c"] == 99


def test_json_set_creates_missing_path(sample_json: Path) -> None:
    json_set(str(sample_json), "x.y.z", "new")
    data = json.loads(sample_json.read_text(encoding="utf-8"))
    assert data["x"]["y"]["z"] == "new"


def test_json_set_list_index(sample_json: Path) -> None:
    json_set(str(sample_json), "list.0", 999)
    data = json.loads(sample_json.read_text(encoding="utf-8"))
    assert data["list"][0] == 999


def test_json_set_list_append_at_len(sample_json: Path) -> None:
    json_set(str(sample_json), "list.3", 40)
    data = json.loads(sample_json.read_text(encoding="utf-8"))
    assert data["list"] == [10, 20, 30, 40]


def test_json_set_list_out_of_range(sample_json: Path) -> None:
    with pytest.raises(JsonEditException):
        json_set(str(sample_json), "list.99", "x")


def test_json_delete(sample_json: Path) -> None:
    assert json_delete(str(sample_json), "a.b.c") is True
    data = json.loads(sample_json.read_text(encoding="utf-8"))
    assert "c" not in data["a"]["b"]


def test_json_delete_missing_returns_false(sample_json: Path) -> None:
    assert json_delete(str(sample_json), "a.missing.x") is False


def test_json_delete_list_index(sample_json: Path) -> None:
    json_delete(str(sample_json), "list.0")
    data = json.loads(sample_json.read_text(encoding="utf-8"))
    assert data["list"] == [20, 30]


def test_empty_key_path_raises(sample_json: Path) -> None:
    with pytest.raises(JsonEditException):
        json_set(str(sample_json), "", "v")


def test_nonexistent_file_raises(tmp_path: Path) -> None:
    with pytest.raises(JsonEditException):
        json_get(str(tmp_path / "no.json"), "x")


def test_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(JsonEditException):
        json_get(str(path), "x")


def test_registered_actions() -> None:
    registry = build_default_registry()
    assert "FA_json_get" in registry
    assert "FA_json_set" in registry
    assert "FA_json_delete" in registry


def test_atomic_write_preserves_on_failure(
    sample_json: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = sample_json.read_text(encoding="utf-8")

    def broken_replace(*_a: object, **_kw: object) -> None:
        raise OSError("simulated")

    monkeypatch.setattr("os.replace", broken_replace)
    with pytest.raises(JsonEditException):
        json_set(str(sample_json), "a.b.c", 777)
    assert sample_json.read_text(encoding="utf-8") == original
