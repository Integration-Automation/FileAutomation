"""FA_storage_* actions: the storage layer through the registry, the executor and MCP."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file import (
    ActionRegistry,
    build_default_registry,
    execute_action,
    register_storage_ops,
    tools_from_registry,
)
from automation_file.exceptions import (
    StorageAlreadyExistsException,
    StorageChecksumException,
    StorageNotEmptyException,
    StorageNotFoundException,
    StorageUnsupportedException,
)
from automation_file.storage import actions, clear_memory_stores, memory_store

NAMES = [
    "FA_storage_checksum",
    "FA_storage_copy",
    "FA_storage_copy_tree",
    "FA_storage_delete",
    "FA_storage_download",
    "FA_storage_exists",
    "FA_storage_list",
    "FA_storage_mkdir",
    "FA_storage_move",
    "FA_storage_read_text",
    "FA_storage_schemes",
    "FA_storage_stat",
    "FA_storage_sync",
    "FA_storage_upload",
    "FA_storage_verify",
    "FA_storage_write_text",
]
SHA256_HELLO = hashlib.sha256(b"hello").hexdigest()


@pytest.fixture(autouse=True)
def _fresh_stores() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


def test_the_default_registry_has_every_storage_action() -> None:
    registry = build_default_registry()
    assert sorted(name for name in registry.event_dict if name.startswith("FA_storage_")) == NAMES


def test_register_storage_ops_fills_a_custom_registry() -> None:
    registry = ActionRegistry()
    register_storage_ops(registry)
    assert sorted(registry.event_dict) == NAMES
    assert sorted(actions.storage_commands()) == NAMES


def test_write_stat_and_read() -> None:
    written = actions.storage_write_text("memory://scratch/dir/note.txt", "hello")
    assert written["uri"] == "memory://scratch/dir/note.txt"
    assert written["path"] == "dir/note.txt"
    assert written["size"] == 5
    assert written["is_dir"] is False
    assert actions.storage_exists("memory://scratch/dir/note.txt") is True
    assert actions.storage_exists("memory://scratch/dir/nope.txt") is False
    assert actions.storage_stat("memory://scratch/dir/note.txt") == written
    assert actions.storage_read_text("memory://scratch/dir/note.txt") == "hello"
    assert actions.storage_stat("memory://scratch/dir")["is_dir"] is True


def test_write_respects_overwrite_and_encoding() -> None:
    actions.storage_write_text("memory://scratch/a.txt", "été", encoding="latin-1")
    assert memory_store("scratch").read_bytes("a.txt") == b"\xe9t\xe9"
    assert actions.storage_read_text("memory://scratch/a.txt", encoding="latin-1") == "été"
    with pytest.raises(StorageAlreadyExistsException):
        actions.storage_write_text("memory://scratch/a.txt", "again", overwrite=False)


def test_list_reports_relative_paths_and_absolute_uris() -> None:
    for path in ("reports/2026/q1.csv", "reports/2026/q2.csv", "reports/readme.txt"):
        actions.storage_write_text(f"memory://scratch/{path}", "x")
    shallow = actions.storage_list("memory://scratch/reports")
    assert [(entry["path"], entry["is_dir"]) for entry in shallow] == [
        ("2026", True),
        ("readme.txt", False),
    ]
    assert [entry["uri"] for entry in shallow] == [
        "memory://scratch/reports/2026",
        "memory://scratch/reports/readme.txt",
    ]
    deep = actions.storage_list("memory://scratch/reports", recursive=True)
    assert [entry["path"] for entry in deep] == [
        "2026",
        "2026/q1.csv",
        "2026/q2.csv",
        "readme.txt",
    ]
    assert deep[1]["uri"] == "memory://scratch/reports/2026/q1.csv"


def test_upload_download_copy_and_move(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"hello")
    uploaded = actions.storage_upload(str(source), "memory://scratch/in/a.txt")
    assert (uploaded["uri"], uploaded["size"]) == ("memory://scratch/in/a.txt", 5)

    copied = actions.storage_copy("memory://scratch/in/a.txt", str(tmp_path / "copy" / "a.txt"))
    assert (tmp_path / "copy" / "a.txt").read_bytes() == b"hello"
    assert copied["uri"].startswith("local:///")
    assert copied["size"] == 5
    with pytest.raises(StorageAlreadyExistsException):
        actions.storage_copy(
            "memory://scratch/in/a.txt", str(tmp_path / "copy" / "a.txt"), overwrite=False
        )

    moved = actions.storage_move("memory://scratch/in/a.txt", "memory://archive/2026/a.txt")
    assert moved["uri"] == "memory://archive/2026/a.txt"
    assert actions.storage_exists("memory://scratch/in/a.txt") is False

    target = tmp_path / "down" / "a.txt"
    assert actions.storage_download("memory://archive/2026/a.txt", str(target)) == str(target)
    assert target.read_bytes() == b"hello"


def test_checksum_and_verify() -> None:
    actions.storage_write_text("memory://scratch/a.txt", "hello")
    assert actions.storage_checksum("memory://scratch/a.txt") == {
        "algorithm": "sha256",
        "value": SHA256_HELLO,
    }
    md5 = hashlib.md5(b"hello", usedforsecurity=False).hexdigest()
    assert actions.storage_checksum("memory://scratch/a.txt", "md5")["value"] == md5
    assert actions.storage_verify("memory://scratch/a.txt", SHA256_HELLO) is True
    assert actions.storage_verify("memory://scratch/a.txt", f"md5:{md5}") is True
    assert actions.storage_verify("memory://scratch/a.txt", md5, algorithm="md5") is True
    assert actions.storage_verify("memory://scratch/a.txt", "0" * 64) is False
    assert actions.storage_verify("memory://scratch/a.txt", SHA256_HELLO, strict=True) is True
    with pytest.raises(StorageChecksumException, match="expected digest"):
        actions.storage_verify("memory://scratch/a.txt", "0" * 64, strict=True)
    with pytest.raises(StorageUnsupportedException):
        actions.storage_checksum("memory://scratch/a.txt", "no-such-hash")


def test_mkdir_and_delete() -> None:
    assert actions.storage_mkdir("memory://scratch/empty/nested") is True
    assert actions.storage_stat("memory://scratch/empty/nested")["is_dir"] is True
    actions.storage_write_text("memory://scratch/empty/nested/a.txt", "x")
    with pytest.raises(StorageNotEmptyException):
        actions.storage_delete("memory://scratch/empty")
    assert actions.storage_delete("memory://scratch/empty/nested/a.txt") is True
    assert actions.storage_delete("memory://scratch/empty", recursive=True) is True
    assert actions.storage_exists("memory://scratch/empty") is False
    with pytest.raises(StorageNotFoundException):
        actions.storage_delete("memory://scratch/empty")
    assert actions.storage_delete("memory://scratch/empty", missing_ok=True) is True
    with pytest.raises(StorageUnsupportedException):
        actions.storage_delete("memory://scratch", recursive=True)


def test_schemes_lists_the_registered_backends() -> None:
    assert {"local", "memory", "s3", "azure"} <= set(actions.storage_schemes())


def test_an_action_list_runs_through_the_executor(tmp_path: Path) -> None:
    results = execute_action(
        [
            ["FA_storage_write_text", {"uri": "memory://scratch/in/a.txt", "text": "hello"}],
            ["FA_storage_copy", ["memory://scratch/in/a.txt", str(tmp_path / "a.txt")]],
            ["FA_storage_checksum", {"uri": str(tmp_path / "a.txt")}],
            ["FA_storage_list", {"uri": "memory://scratch", "recursive": True}],
            ["FA_storage_read_text", {"uri": "memory://scratch/in/missing.txt"}],
            ["FA_storage_schemes"],
        ]
    )
    values = list(results.values())
    assert json.loads(json.dumps(values[:4])) == values[:4]
    assert values[0]["uri"] == "memory://scratch/in/a.txt"
    assert (tmp_path / "a.txt").read_bytes() == b"hello"
    assert values[2] == {"algorithm": "sha256", "value": SHA256_HELLO}
    assert [entry["path"] for entry in values[3]] == ["in", "in/a.txt"]
    assert "StorageNotFoundException" in values[4]
    assert "memory" in values[5]


def test_the_actions_are_mcp_tools_with_their_parameters() -> None:
    tools = {tool["name"]: tool for tool in tools_from_registry(build_default_registry())}
    assert set(NAMES) <= set(tools)
    copy = tools["FA_storage_copy"]["inputSchema"]
    assert list(copy["properties"]) == ["source", "target", "overwrite"]
    assert copy["required"] == ["source", "target"]
    assert tools["FA_storage_schemes"]["inputSchema"].get("required", []) == []
    assert "Copy the file" in tools["FA_storage_copy"]["description"]


def test_copy_tree_and_sync_actions(tmp_path: Path) -> None:
    for path in ("a.txt", "sub/b.txt"):
        actions.storage_write_text(f"memory://scratch/src/{path}", "x")
    copied = actions.storage_copy_tree("memory://scratch/src", str(tmp_path / "out"))
    assert copied == {
        "copied": ["a.txt", "sub/b.txt"],
        "skipped": [],
        "deleted": [],
        "errors": {},
        "dry_run": False,
    }
    assert (tmp_path / "out" / "sub" / "b.txt").read_bytes() == b"x"
    (tmp_path / "out" / "extra.txt").write_bytes(b"extra")
    preview = actions.storage_sync(
        "memory://scratch/src", str(tmp_path / "out"), delete=True, dry_run=True
    )
    assert preview["deleted"] == ["extra.txt"]
    assert preview["dry_run"] is True
    assert (tmp_path / "out" / "extra.txt").exists()
    synced = actions.storage_sync("memory://scratch/src", str(tmp_path / "out"), delete=True)
    assert synced["deleted"] == ["extra.txt"]
    assert not (tmp_path / "out" / "extra.txt").exists()
    assert json.loads(json.dumps(synced)) == synced
