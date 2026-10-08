"""FA_integrity_* actions: the monitor through the registry, the executor and MCP."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file import ActionExecutor, ActionRegistry, tools_from_registry
from automation_file.events import Event, IntegrityViolation, event_bus
from automation_file.integrity import IntegrityException, actions, register_integrity_ops
from automation_file.storage import File, Storage, clear_memory_stores

NAMES = [
    "FA_integrity_accept",
    "FA_integrity_baseline",
    "FA_integrity_snapshot",
    "FA_integrity_status",
    "FA_integrity_verify",
    "FA_integrity_watch_start",
    "FA_integrity_watch_stop",
]
TREE = "memory://actions/tree"
BASELINE = "memory://actions-state/tree.json"
WAIT = 10.0


@pytest.fixture(autouse=True)
def _fresh_state() -> Iterator[None]:
    clear_memory_stores()
    yield
    actions.stop_all_monitors()
    clear_memory_stores()


@pytest.fixture
def tree() -> Storage:
    storage = Storage(TREE)
    storage.file("a.txt").write(b"alpha")
    storage.file("sub/b.txt").write(b"bravo")
    return storage


@pytest.fixture
def executor() -> ActionExecutor:
    registry = ActionRegistry()
    register_integrity_ops(registry)
    return ActionExecutor(registry)


@pytest.fixture
def drift() -> Iterator[threading.Event]:
    """Set once an IntegrityViolation for the tree reaches the process-wide bus."""
    seen = threading.Event()

    def _note(event: Event) -> None:
        if event.payload.get("resource") == TREE:
            seen.set()

    subscription = event_bus.subscribe(_note, types=IntegrityViolation)
    yield seen
    event_bus.unsubscribe(subscription)


def test_register_integrity_ops_fills_a_registry() -> None:
    registry = ActionRegistry()
    register_integrity_ops(registry)
    assert sorted(registry.event_dict) == NAMES
    assert sorted(actions.integrity_commands()) == NAMES


def test_snapshot_returns_the_tree_and_stores_nothing(tree: Storage) -> None:
    snapshot = actions.integrity_snapshot(TREE)
    assert json.loads(json.dumps(snapshot)) == snapshot
    assert (snapshot["root"], snapshot["backend"], snapshot["algorithm"]) == (
        TREE,
        "memory",
        "sha256",
    )
    assert [entry["path"] for entry in snapshot["entries"]] == ["a.txt", "sub/b.txt"]
    assert snapshot["entries"][0]["checksum"] == hashlib.sha256(b"alpha").hexdigest()
    assert actions.integrity_snapshot(TREE, "sha512")["entries"][0]["checksum"] == (
        hashlib.sha512(b"alpha").hexdigest()
    )
    assert Storage("memory://actions-state").exists("tree.json") is False


def test_a_weak_algorithm_cannot_be_chosen_through_an_action(tree: Storage) -> None:
    with pytest.raises(IntegrityException, match="not collision-resistant"):
        actions.integrity_snapshot(TREE, "md5")
    with pytest.raises(IntegrityException, match="not collision-resistant"):
        actions.integrity_baseline(TREE, BASELINE, "md5")
    assert File(BASELINE).exists() is False


def test_baseline_verify_and_accept(tree: Storage) -> None:
    stored = actions.integrity_baseline(TREE, BASELINE)
    assert stored == {
        "target": TREE,
        "baseline": BASELINE,
        "backend": "memory",
        "algorithm": "sha256",
        "created_at": stored["created_at"],
        "entries": 2,
    }
    assert json.loads(File(BASELINE).read_text())["schema_version"] == 2
    clean = actions.integrity_verify(TREE, BASELINE)
    assert (clean["ok"], clean["deep"], clean["checked"], clean["changes"]) == (True, True, 2, [])

    tree.file("a.txt").write(b"tampered")
    tree.file("new.txt").write(b"novel")
    report = actions.integrity_verify(TREE, BASELINE)
    assert json.loads(json.dumps(report)) == report
    assert report["ok"] is False
    assert (report["counts"]["modified"], report["counts"]["created"]) == (1, 1)
    assert [(change["kind"], change["path"]) for change in report["changes"]] == [
        ("modified", "a.txt"),
        ("created", "new.txt"),
    ]
    quick = actions.integrity_verify(TREE, BASELINE, deep=False)
    assert (quick["deep"], quick["hashed"], quick["counts"]["modified"]) == (False, 2, 1)

    accepted = actions.integrity_accept(TREE, BASELINE)
    assert (accepted["entries"], accepted["baseline"], accepted["algorithm"]) == (
        3,
        BASELINE,
        "sha256",
    )
    assert actions.integrity_verify(TREE, BASELINE)["ok"] is True


def test_the_baseline_may_be_a_local_path(tree: Storage, tmp_path: Path) -> None:
    location = str(tmp_path / "state" / "tree.json")
    stored = actions.integrity_baseline(TREE, location, "blake2b")
    assert stored["baseline"].startswith("local:///")
    assert stored["algorithm"] == "blake2b"
    assert (tmp_path / "state" / "tree.json").is_file()
    assert actions.integrity_verify(TREE, location)["algorithm"] == "blake2b"


def test_an_action_list_runs_through_the_executor(tree: Storage, executor: ActionExecutor) -> None:
    results = executor.execute_action(
        [
            ["FA_integrity_snapshot", {"target": TREE}],
            ["FA_integrity_baseline", {"target": TREE, "baseline": BASELINE}],
            ["FA_integrity_verify", [TREE, BASELINE]],
            ["FA_integrity_verify", {"target": TREE, "baseline": "memory://nowhere/b.json"}],
            ["FA_integrity_accept", {"target": TREE, "baseline": BASELINE}],
            ["FA_integrity_status"],
            ["FA_integrity_status", {"name": "nobody"}],
        ]
    )
    values = list(results.values())
    assert json.loads(json.dumps(values)) == values
    assert len(values[0]["entries"]) == 2
    assert values[1]["entries"] == 2
    assert values[2]["ok"] is True
    assert "IntegrityException" in values[3] and "no baseline at" in values[3]
    assert values[4]["entries"] == 2
    assert values[5] == []
    assert "no integrity monitor named 'nobody'" in values[6]


def test_a_named_monitor_runs_until_it_is_stopped(
    tree: Storage, executor: ActionExecutor, drift: threading.Event
) -> None:
    actions.integrity_baseline(TREE, BASELINE)
    tree.file("a.txt").write(b"tampered")
    started = executor.execute_action(
        [
            [
                "FA_integrity_watch_start",
                {"name": "tree", "target": TREE, "baseline": BASELINE, "interval": 0.02},
            ]
        ]
    )
    (status,) = started.values()
    assert (status["name"], status["running"], status["interval"]) == ("tree", True, 0.02)
    assert (status["target"], status["baseline"]) == (TREE, BASELINE)
    assert drift.wait(WAIT), "the named monitor did not verify"

    (listed,) = actions.integrity_status()
    (named,) = actions.integrity_status("tree")
    assert listed["name"] == named["name"] == "tree"
    assert named["running"] is True
    assert named["last_run"] is not None
    assert named["last_error"] is None
    assert named["last_report"]["counts"]["modified"] == 1
    assert json.loads(json.dumps(named)) == named

    with pytest.raises(IntegrityException, match="already running"):
        actions.integrity_watch_start("tree", TREE, BASELINE)
    stopped = actions.integrity_watch_stop("tree")
    assert (stopped["name"], stopped["running"]) == ("tree", False)
    assert stopped["last_report"]["ok"] is False
    assert actions.integrity_status() == []
    with pytest.raises(IntegrityException, match="no integrity monitor named 'tree'"):
        actions.integrity_watch_stop("tree")


def test_a_named_monitor_needs_a_name_a_baseline_and_a_positive_interval(tree: Storage) -> None:
    with pytest.raises(IntegrityException, match="create it first with FA_integrity_baseline"):
        actions.integrity_watch_start("tree", TREE, BASELINE)
    actions.integrity_baseline(TREE, BASELINE)
    with pytest.raises(IntegrityException, match="needs a name"):
        actions.integrity_watch_start(" ", TREE, BASELINE)
    with pytest.raises(IntegrityException, match="interval must be positive"):
        actions.integrity_watch_start("tree", TREE, BASELINE, interval=0)
    assert actions.integrity_status() == []


def test_stop_all_monitors_stops_every_named_monitor(tree: Storage) -> None:
    actions.integrity_baseline(TREE, BASELINE)
    actions.integrity_watch_start("one", TREE, BASELINE, interval=30.0)
    actions.integrity_watch_start("two", TREE, BASELINE, interval=30.0)
    assert [status["name"] for status in actions.integrity_status()] == ["one", "two"]
    stopped = actions.stop_all_monitors()
    assert [(status["name"], status["running"]) for status in stopped] == [
        ("one", False),
        ("two", False),
    ]
    assert actions.integrity_status() == []


def test_the_actions_are_mcp_tools_with_their_parameters() -> None:
    registry = ActionRegistry()
    register_integrity_ops(registry)
    tools = {tool["name"]: tool for tool in tools_from_registry(registry)}
    assert set(NAMES) <= set(tools)
    verify = tools["FA_integrity_verify"]["inputSchema"]
    assert list(verify["properties"]) == ["target", "baseline", "deep"]
    assert verify["required"] == ["target", "baseline"]
    start = tools["FA_integrity_watch_start"]["inputSchema"]
    assert list(start["properties"]) == ["name", "target", "baseline", "interval"]
    assert start["required"] == ["name", "target", "baseline"]
    assert tools["FA_integrity_status"]["inputSchema"].get("required", []) == []
    assert "Compare" in tools["FA_integrity_verify"]["description"]
