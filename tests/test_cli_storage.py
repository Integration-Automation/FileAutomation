"""The ``storage`` subcommand: one JSON document per call, exit codes that mean something."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file.__main__ import main
from automation_file.exceptions import StorageNotFoundException
from automation_file.storage import clear_memory_stores, memory_store


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(["storage", *argv])
    return code, capsys.readouterr().out


def test_ls_stat_and_cat(capsys: pytest.CaptureFixture[str]) -> None:
    store = memory_store("cli")
    store.write_bytes("docs/a.txt", "報告 ✓".encode())
    store.write_bytes("docs/sub/b.txt", b"x")
    code, out = _run(capsys, "ls", "memory://cli/docs")
    assert code == 0
    assert [(entry["path"], entry["is_dir"]) for entry in json.loads(out)] == [
        ("a.txt", False),
        ("sub", True),
    ]
    code, out = _run(capsys, "ls", "memory://cli/docs", "--recursive")
    assert [entry["path"] for entry in json.loads(out)] == ["a.txt", "sub", "sub/b.txt"]
    code, out = _run(capsys, "stat", "memory://cli/docs/a.txt")
    assert json.loads(out)["uri"] == "memory://cli/docs/a.txt"
    code, out = _run(capsys, "cat", "memory://cli/docs/a.txt")
    assert (code, out) == (0, "報告 ✓")


def test_cp_mv_rm_and_mkdir(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_bytes(b"payload")
    code, out = _run(capsys, "cp", str(source), "memory://cli/in/a.txt")
    assert code == 0
    assert json.loads(out)["size"] == 7
    code, out = _run(capsys, "mv", "memory://cli/in/a.txt", "memory://cli/out/b.txt")
    assert json.loads(out)["uri"] == "memory://cli/out/b.txt"
    assert memory_store("cli").exists("in/a.txt") is False
    code, out = _run(capsys, "mkdir", "memory://cli/empty")
    assert json.loads(out) == {"created": "memory://cli/empty"}
    code, out = _run(capsys, "rm", "memory://cli/out", "-r")
    assert json.loads(out) == {"deleted": "memory://cli/out"}
    assert memory_store("cli").exists("out") is False
    code, _ = _run(capsys, "rm", "memory://cli/out", "--missing-ok")
    assert code == 0
    with pytest.raises(StorageNotFoundException):
        main(["storage", "rm", "memory://cli/out"])


def test_copy_without_overwrite_and_recursive_copy(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    store = memory_store("cli")
    store.write_bytes("src/a.txt", b"a")
    store.write_bytes("src/sub/b.txt", b"b")
    code, out = _run(capsys, "cp", "-r", "memory://cli/src", str(tmp_path / "out"))
    assert code == 0
    assert json.loads(out)["copied"] == ["a.txt", "sub/b.txt"]
    assert (tmp_path / "out" / "sub" / "b.txt").read_bytes() == b"b"
    code, out = _run(
        capsys, "cp", "-r", "--no-overwrite", "memory://cli/src", str(tmp_path / "out")
    )
    assert json.loads(out)["skipped"] == ["a.txt", "sub/b.txt"]


def test_checksum_and_verify_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    memory_store("cli").write_bytes("a.txt", b"hello")
    code, out = _run(capsys, "checksum", "memory://cli/a.txt")
    digest = json.loads(out)
    assert digest["algorithm"] == "sha256"
    code, out = _run(capsys, "verify", "memory://cli/a.txt", digest["value"])
    assert (code, json.loads(out)["matches"]) == (0, True)
    code, out = _run(capsys, "verify", "memory://cli/a.txt", "0" * 64)
    assert (code, json.loads(out)["matches"]) == (1, False)
    code, out = _run(capsys, "checksum", "memory://cli/a.txt", "--algorithm", "md5")
    assert json.loads(out)["algorithm"] == "md5"


def test_sync_reports_and_signals_errors(capsys: pytest.CaptureFixture[str]) -> None:
    store = memory_store("cli")
    store.write_bytes("src/a.txt", b"a")
    store.write_bytes("dst/stale.txt", b"s")
    code, out = _run(
        capsys, "sync", "memory://cli/src", "memory://cli/dst", "--delete", "--dry-run"
    )
    preview = json.loads(out)
    assert (code, preview["copied"], preview["deleted"], preview["dry_run"]) == (
        0,
        ["a.txt"],
        ["stale.txt"],
        True,
    )
    assert store.exists("dst/stale.txt") is True
    code, out = _run(capsys, "sync", "memory://cli/src", "memory://cli/dst", "--delete")
    assert code == 0
    assert store.exists("dst/stale.txt") is False
    store.write_bytes("blocked/a.txt/inner", b"x")
    code, out = _run(capsys, "sync", "memory://cli/src", "memory://cli/blocked")
    assert code == 1
    assert list(json.loads(out)["errors"]) == ["a.txt"]


def test_schemes_and_init(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, out = _run(capsys, "schemes")
    assert {"local", "memory"} <= set(json.loads(out))
    marker = tmp_path / "made-by-init"
    init = json.dumps([["FA_create_dir", {"dir_path": str(marker)}]])
    code, out = _run(capsys, "--init", init, "schemes")
    assert code == 0
    assert marker.is_dir()


def test_a_subcommand_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["storage"])
    assert "storage" in capsys.readouterr().err
