"""Tests for FA_if_exists / FA_if_newer / FA_if_size_gt conditional primitives."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from automation_file import (
    build_default_registry,
    if_exists,
    if_newer,
    if_size_gt,
)
from automation_file.core.action_executor import executor
from automation_file.exceptions import FileAutomationException


def _register_probes() -> None:
    if "test_cond_then" not in executor.registry:
        executor.registry.register("test_cond_then", lambda: "then-ran")
    if "test_cond_else" not in executor.registry:
        executor.registry.register("test_cond_else", lambda: "else-ran")


def test_if_exists_runs_then_when_path_present(tmp_path: Path) -> None:
    _register_probes()
    target = tmp_path / "here.txt"
    target.write_text("x", encoding="utf-8")
    outcome = if_exists(str(target), then=[["test_cond_then"]], else_=[["test_cond_else"]])
    assert outcome["matched"] is True
    assert any("then-ran" in str(v) for v in outcome["results"].values())


def test_if_exists_runs_else_when_path_missing(tmp_path: Path) -> None:
    _register_probes()
    outcome = if_exists(
        str(tmp_path / "absent"), then=[["test_cond_then"]], else_=[["test_cond_else"]]
    )
    assert outcome["matched"] is False
    assert any("else-ran" in str(v) for v in outcome["results"].values())


def test_if_exists_empty_branch_returns_no_results(tmp_path: Path) -> None:
    outcome = if_exists(str(tmp_path / "absent"))
    assert outcome == {"matched": False, "results": {}}


def test_if_newer_true_when_source_newer(tmp_path: Path) -> None:
    _register_probes()
    older = tmp_path / "old.txt"
    newer = tmp_path / "new.txt"
    older.write_text("o", encoding="utf-8")
    newer.write_text("n", encoding="utf-8")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_001_000, 1_700_001_000))
    outcome = if_newer(str(newer), str(older), then=[["test_cond_then"]])
    assert outcome["matched"] is True


def test_if_newer_false_when_source_older(tmp_path: Path) -> None:
    _register_probes()
    older = tmp_path / "old.txt"
    newer = tmp_path / "new.txt"
    older.write_text("o", encoding="utf-8")
    newer.write_text("n", encoding="utf-8")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_001_000, 1_700_001_000))
    outcome = if_newer(str(older), str(newer), then=[["test_cond_then"]])
    assert outcome["matched"] is False


def test_if_newer_missing_reference_treats_source_as_newer(tmp_path: Path) -> None:
    source = tmp_path / "src.txt"
    source.write_text("x", encoding="utf-8")
    outcome = if_newer(str(source), str(tmp_path / "absent"))
    assert outcome["matched"] is True


def test_if_size_gt_true(tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 100)
    outcome = if_size_gt(str(path), 50)
    assert outcome["matched"] is True


def test_if_size_gt_false(tmp_path: Path) -> None:
    path = tmp_path / "small.bin"
    path.write_bytes(b"x" * 10)
    outcome = if_size_gt(str(path), 50)
    assert outcome["matched"] is False


def test_if_size_gt_rejects_negative_threshold(tmp_path: Path) -> None:
    with pytest.raises(FileAutomationException):
        if_size_gt(str(tmp_path / "x"), -1)


def test_default_registry_wires_conditionals() -> None:
    registry = build_default_registry()
    for name in ("FA_if_exists", "FA_if_newer", "FA_if_size_gt"):
        assert name in registry
