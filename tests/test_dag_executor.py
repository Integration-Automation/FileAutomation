"""Tests for automation_file.core.dag_executor."""

from __future__ import annotations

import threading
import time

import pytest

from automation_file import add_command_to_executor, execute_action_dag
from automation_file.exceptions import DagException


@pytest.fixture(autouse=True)
def _register_test_commands() -> None:
    calls: list[str] = []
    lock = threading.Lock()

    def record(name: str, delay: float = 0.0) -> str:
        if delay:
            time.sleep(delay)
        with lock:
            calls.append(name)
        return name

    def boom() -> None:
        raise RuntimeError("planned-failure")

    add_command_to_executor(
        {
            "_dag_record": record,
            "_dag_boom": boom,
        }
    )


def test_linear_chain_runs_in_order() -> None:
    results = execute_action_dag(
        [
            {"id": "a", "action": ["_dag_record", ["a"]]},
            {"id": "b", "action": ["_dag_record", ["b"]], "depends_on": ["a"]},
            {"id": "c", "action": ["_dag_record", ["c"]], "depends_on": ["b"]},
        ]
    )
    assert results == {"a": "a", "b": "b", "c": "c"}


def test_diamond_converges() -> None:
    results = execute_action_dag(
        [
            {"id": "top", "action": ["_dag_record", ["top"]]},
            {"id": "left", "action": ["_dag_record", ["left"]], "depends_on": ["top"]},
            {"id": "right", "action": ["_dag_record", ["right"]], "depends_on": ["top"]},
            {
                "id": "bottom",
                "action": ["_dag_record", ["bottom"]],
                "depends_on": ["left", "right"],
            },
        ]
    )
    assert results["top"] == "top"
    assert results["left"] == "left"
    assert results["right"] == "right"
    assert results["bottom"] == "bottom"


def test_independent_branches_parallelise() -> None:
    start = time.monotonic()
    execute_action_dag(
        [
            {"id": "a", "action": ["_dag_record", ["a", 0.3]]},
            {"id": "b", "action": ["_dag_record", ["b", 0.3]]},
            {"id": "c", "action": ["_dag_record", ["c", 0.3]]},
        ],
        max_workers=3,
    )
    elapsed = time.monotonic() - start
    assert elapsed < 0.8, f"independent branches should parallelise, took {elapsed:.2f}s"


def test_failure_skips_dependents_by_default() -> None:
    results = execute_action_dag(
        [
            {"id": "root", "action": ["_dag_boom"]},
            {"id": "child", "action": ["_dag_record", ["child"]], "depends_on": ["root"]},
            {
                "id": "grand",
                "action": ["_dag_record", ["grand"]],
                "depends_on": ["child"],
            },
        ]
    )
    assert "RuntimeError" in results["root"]
    assert results["child"].startswith("skipped: dep 'root' failed")
    assert results["grand"].startswith("skipped: dep 'child' failed")


def test_fail_fast_false_still_runs_dependents() -> None:
    results = execute_action_dag(
        [
            {"id": "root", "action": ["_dag_boom"]},
            {"id": "child", "action": ["_dag_record", ["child"]], "depends_on": ["root"]},
        ],
        fail_fast=False,
    )
    assert "RuntimeError" in results["root"]
    assert results["child"] == "child"


def test_cycle_detected() -> None:
    with pytest.raises(DagException, match="cycle"):
        execute_action_dag(
            [
                {"id": "a", "action": ["_dag_record", ["a"]], "depends_on": ["b"]},
                {"id": "b", "action": ["_dag_record", ["b"]], "depends_on": ["a"]},
            ]
        )


def test_unknown_dep_rejected() -> None:
    with pytest.raises(DagException, match="unknown id"):
        execute_action_dag(
            [
                {"id": "a", "action": ["_dag_record", ["a"]], "depends_on": ["missing"]},
            ]
        )


def test_duplicate_id_rejected() -> None:
    with pytest.raises(DagException, match="duplicate"):
        execute_action_dag(
            [
                {"id": "dup", "action": ["_dag_record", ["a"]]},
                {"id": "dup", "action": ["_dag_record", ["b"]]},
            ]
        )


def test_self_dependency_rejected() -> None:
    with pytest.raises(DagException, match="itself"):
        execute_action_dag(
            [
                {"id": "a", "action": ["_dag_record", ["a"]], "depends_on": ["a"]},
            ]
        )


def test_missing_id_rejected() -> None:
    with pytest.raises(DagException, match="non-empty 'id'"):
        execute_action_dag([{"action": ["_dag_record", ["a"]]}])


def test_node_missing_action_list() -> None:
    results = execute_action_dag(
        [
            {"id": "bad"},
            {"id": "child", "action": ["_dag_record", ["child"]], "depends_on": ["bad"]},
        ]
    )
    assert "missing action list" in results["bad"]
    assert results["child"].startswith("skipped")


def test_dag_action_registered_in_default_registry() -> None:
    from automation_file.core.action_registry import build_default_registry

    assert "FA_execute_action_dag" in build_default_registry()
