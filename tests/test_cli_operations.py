"""The ``integrity``, ``pipeline`` and ``audit`` subcommands: JSON out, meaningful exit codes."""

# pylint: disable=line-too-long  # an expected value is kept on one line

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from automation_file.__main__ import main
from automation_file.audit import audit_trail
from automation_file.cli_common import cli_actor
from automation_file.cli_operations import _parameters
from automation_file.exceptions import ArgparseException
from automation_file.pipeline import MemoryRunStore, PipelineException, set_default_run_store
from automation_file.storage import clear_memory_stores, memory_store


@pytest.fixture(autouse=True)
def _isolated() -> Iterator[None]:
    clear_memory_stores()
    previous = set_default_run_store(MemoryRunStore())
    yield
    set_default_run_store(previous)
    audit_trail.close()
    clear_memory_stores()


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, Any]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def _forget_runs() -> None:
    """Stand in for a new process: the next command has only what its store file holds."""
    set_default_run_store(MemoryRunStore())


def _definition(tmp_path: Path, name: str = "cli-notes", source: str = "a.txt") -> Path:
    document = {
        "schema_version": 1,
        "name": name,
        "params": {"text": "default"},
        "tasks": {
            "write": {
                "action": [
                    "FA_storage_write_text",
                    {"uri": "memory://cli-pipe/a.txt", "text": "${params.text}"},
                ]
            },
            "read": {
                "action": ["FA_storage_read_text", {"uri": f"memory://cli-pipe/{source}"}],
                "depends_on": ["write"],
            },
        },
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# ---------------------------------------------------------------------- integrity


def test_integrity_baseline_verify_and_accept(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("alpha", encoding="utf-8")
    baseline = tmp_path / "baseline.json"

    code, stored = _run(capsys, "integrity", "baseline", str(tree), str(baseline))
    assert code == 0
    assert baseline.is_file()
    assert stored["algorithm"] == "sha256"

    code, report = _run(capsys, "integrity", "verify", str(tree), str(baseline))
    assert (code, report["ok"], report["deep"]) == (0, True, True)

    (tree / "a.txt").write_text("changed", encoding="utf-8")
    (tree / "new.txt").write_text("new", encoding="utf-8")
    code, report = _run(capsys, "integrity", "verify", str(tree), str(baseline))
    assert code == 1
    assert (report["counts"]["modified"], report["counts"]["created"]) == (1, 1)

    code, _ = _run(capsys, "integrity", "accept", str(tree), str(baseline))
    assert code == 0
    code, report = _run(capsys, "integrity", "verify", str(tree), str(baseline), "--quick")
    assert (code, report["ok"], report["deep"]) == (0, True, False)


def test_integrity_snapshot_prints_the_manifest_and_stores_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "報告.txt").write_text("alpha", encoding="utf-8")
    code, snapshot = _run(capsys, "integrity", "snapshot", str(tree), "--algorithm", "sha512")
    assert code == 0
    assert snapshot["algorithm"] == "sha512"
    assert [entry["path"] for entry in snapshot["entries"]] == ["報告.txt"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["tree"]


def test_integrity_works_on_a_storage_uri(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    memory_store("cli-tree").write_bytes("docs/a.txt", b"alpha")
    baseline = tmp_path / "memory.baseline.json"
    code, _ = _run(capsys, "integrity", "baseline", "memory://cli-tree/docs", str(baseline))
    assert code == 0
    memory_store("cli-tree").delete("docs/a.txt")
    code, report = _run(capsys, "integrity", "verify", "memory://cli-tree/docs", str(baseline))
    assert code == 1
    assert report["counts"]["deleted"] == 1


# ---------------------------------------------------------------------- pipeline


def test_pipeline_validate_says_what_is_wrong(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, result = _run(capsys, "pipeline", "validate", str(_definition(tmp_path)))
    assert (code, result) == (0, {"valid": True, "errors": []})

    broken = tmp_path / "broken.json"
    broken.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "broken",
                "tasks": {"a": {"action": ["FA_storage_schemes"], "depends_on": ["nowhere"]}},
            }
        ),
        encoding="utf-8",
    )
    code, result = _run(capsys, "pipeline", "validate", str(broken))
    assert code == 1
    assert result["valid"] is False
    assert any("nowhere" in problem for problem in result["errors"])


def test_pipeline_run_status_and_history_share_a_store_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    definition, store = str(_definition(tmp_path)), str(tmp_path / "runs.db")
    code, run = _run(
        capsys, "pipeline", "run", definition, "--param", "text=hello", "--store", store
    )
    assert code == 0
    assert run["status"] == "succeeded"
    assert run["tasks"]["read"]["result"] == "hello"

    _forget_runs()
    code, status = _run(capsys, "pipeline", "status", run["run_id"], "--store", store)
    assert (code, status["run_id"], status["status"]) == (0, run["run_id"], "succeeded")

    _forget_runs()
    code, history = _run(capsys, "pipeline", "history", "--pipeline", "cli-notes", "--store", store)
    assert code == 0
    assert [entry["run_id"] for entry in history] == [run["run_id"]]

    _forget_runs()
    with pytest.raises(PipelineException, match="unknown run"):
        main(["pipeline", "status", run["run_id"]])


def test_pipeline_dry_run_plans_and_executes_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, plan = _run(capsys, "pipeline", "run", str(_definition(tmp_path)), "--dry-run")
    assert code == 0
    assert {state["status"] for state in plan["tasks"].values()} == {"planned"}
    assert not memory_store("cli-pipe").exists("a.txt")


def test_a_failed_run_exits_1_and_can_be_resumed(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    definition = str(_definition(tmp_path, name="cli-late", source="late.txt"))
    store = str(tmp_path / "runs.db")
    code, run = _run(capsys, "pipeline", "run", definition, "--store", store)
    assert code == 1
    assert (run["status"], run["tasks"]["read"]["status"]) == ("failed", "failed")

    memory_store("cli-pipe").write_bytes("late.txt", b"arrived")
    _forget_runs()
    code, resumed = _run(capsys, "pipeline", "resume", run["run_id"], definition, "--store", store)
    assert code == 0
    assert resumed["tasks"]["read"]["result"] == "arrived"


def test_run_parameters_keep_json_types() -> None:
    assert _parameters(None) is None
    assert _parameters(["a=1", "b=x", 'c={"k": [1]}', "d=", "e=a=b"]) == {
        "a": 1,
        "b": "x",
        "c": {"k": [1]},
        "d": "",
        "e": "a=b",
    }
    for pair in ("novalue", "=x"):
        with pytest.raises(ArgparseException, match="name=value"):
            _parameters([pair])


# ---------------------------------------------------------------------- audit


def test_a_command_run_with_audit_is_found_by_audit_search(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    database = str(tmp_path / "audit.sqlite")
    memory_store("cli-audit").write_bytes("a.txt", b"alpha")
    code, _ = _run(
        capsys,
        "storage",
        "--audit",
        database,
        "cp",
        "memory://cli-audit/a.txt",
        "memory://cli-audit/b.txt",
    )
    assert code == 0
    assert audit_trail.active is False

    code, records = _run(
        capsys, "audit", "search", "--db", database, "--resource-prefix", "memory://cli-audit/"
    )
    assert code == 0
    copies = [record for record in records if record["action"] == "copy"]
    assert [record["resource"] for record in copies] == ["memory://cli-audit/b.txt"]
    assert copies[0]["actor"] == cli_actor()
    assert copies[0]["status"] == "ok"

    code, counted = _run(capsys, "audit", "count", "--db", database, "--action", "copy")
    assert (code, counted) == (0, {"count": 1})
    code, counted = _run(capsys, "audit", "count", "--db", database, "--status", "error")
    assert (code, counted) == (0, {"count": 0})


def test_audit_search_pages_and_purge_empties(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    database = str(tmp_path / "audit.sqlite")
    store = memory_store("cli-audit")
    for name in ("a", "b", "c"):
        store.write_bytes(f"{name}.txt", b"x")
        main(["storage", "--audit", database, "cat", f"memory://cli-audit/{name}.txt"])
    capsys.readouterr()

    code, first = _run(capsys, "audit", "search", "--db", database, "--limit", "2")
    code, rest = _run(capsys, "audit", "search", "--db", database, "--limit", "2", "--offset", "2")
    assert (len(first), len(rest)) == (2, 1)
    assert {record["id"] for record in first}.isdisjoint(record["id"] for record in rest)

    code, purged = _run(capsys, "audit", "purge", "--db", database, "--older-than-days", "30")
    assert (code, purged) == (0, {"purged": 0})


def test_a_time_without_a_zone_is_local_time(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    database = str(tmp_path / "audit.sqlite")
    memory_store("cli-audit").write_bytes("a.txt", b"x")
    main(["storage", "--audit", database, "cat", "memory://cli-audit/a.txt"])
    capsys.readouterr()
    code, counted = _run(capsys, "audit", "count", "--db", database, "--since", "2020-01-01")
    assert (code, counted) == (0, {"count": 1})
    code, counted = _run(
        capsys, "audit", "count", "--db", database, "--until", "2020-01-01T00:00:00+00:00"
    )
    assert (code, counted) == (0, {"count": 0})
    with pytest.raises(ArgparseException, match="--since takes an ISO 8601"):
        main(["audit", "count", "--db", database, "--since", "yesterday"])


def test_the_audit_database_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["audit", "search"])
    assert "--db" in capsys.readouterr().err
