"""The semantic tools that work on a directory: ``storage_list``, ``storage_copy``, ``file_search``."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file.exceptions import StorageTransientException
from automation_file.server.mcp_policy import (
    OUTSIDE_ROOT,
    OVERWRITE_NOT_ALLOWED,
    READ_ONLY,
    MCPPolicy,
)
from automation_file.server.mcp_tools import SemanticToolkit
from automation_file.storage import File, Storage
from tests.mcp_support import (
    BOX,
    INBOX,
    clean_state,
    failed,
    link_directory,
    refused,
    remove_link,
    succeed,
    toolkit,
    writable,
)

TREE = f"{INBOX}/tree"
COPY = f"{INBOX}/copy"
FILES = {
    "readme.txt": "A report about needles.\nNothing else.\n",
    "2026/q1.csv": "id,amount\n1,10\n",
    "2026/q2.csv": "id,amount\n2,20\nNEEDLE,30\n",
    "2026/notes/todo.txt": "find the needle\nand another needle\n",
}


@pytest.fixture(autouse=True)
def _state() -> Iterator[None]:
    with clean_state():
        for path, content in FILES.items():
            File(f"{TREE}/{path}").write(content)
        yield


def _paths(body: dict, key: str = "matches") -> list[str]:
    return [entry["path"] for entry in body[key]]


# ---------------------------------------------------------------------- storage_list


def test_storage_list_returns_the_direct_children() -> None:
    body = succeed(toolkit().call("storage_list", {"uri": TREE}))
    assert _paths(body, "entries") == ["2026", "readme.txt"]
    folder, readme = body["entries"]
    assert (folder["is_dir"], folder["size"], folder["uri"]) == (True, None, f"{TREE}/2026")
    assert (readme["is_dir"], readme["size"], readme["name"]) == (False, 38, "readme.txt")
    assert readme["modified_at"] is not None
    assert (body["count"], body["total"], body["truncated"], body["recursive"]) == (
        2,
        2,
        False,
        False,
    )


def test_storage_list_recursive_is_capped_by_the_argument_and_by_the_policy() -> None:
    everything = succeed(toolkit().call("storage_list", {"uri": TREE, "recursive": True}))
    assert _paths(everything, "entries") == [
        "2026",
        "2026/notes",
        "2026/notes/todo.txt",
        "2026/q1.csv",
        "2026/q2.csv",
        "readme.txt",
    ]
    two = succeed(
        toolkit().call("storage_list", {"uri": TREE, "recursive": True, "max_results": 2})
    )
    assert (two["count"], two["total"], two["truncated"]) == (2, 6, True)
    capped = toolkit(max_results=3)
    body = succeed(capped.call("storage_list", {"uri": TREE, "recursive": True, "max_results": 50}))
    assert (body["count"], body["truncated"]) == (3, True)


def test_storage_list_of_a_file_or_of_nothing_fails() -> None:
    kit = toolkit()
    error = failed(kit.call("storage_list", {"uri": f"{TREE}/readme.txt"}), "failed")
    assert "not a directory" in error["message"]
    failed(kit.call("storage_list", {"uri": f"{INBOX}/absent"}), "not_found")


# ---------------------------------------------------------------------- file_search


def test_file_search_by_name_pattern() -> None:
    kit = toolkit()
    body = succeed(kit.call("file_search", {"uri": TREE, "pattern": "*.csv"}))
    assert _paths(body) == ["2026/q1.csv", "2026/q2.csv"]
    assert body["matches"][0]["uri"] == f"{TREE}/2026/q1.csv"
    assert (body["count"], body["truncated"], body["candidates"]) == (2, False, 2)
    assert _paths(succeed(kit.call("file_search", {"uri": TREE}))) == sorted(FILES)
    assert _paths(succeed(kit.call("file_search", {"uri": TREE, "pattern": "Q?.CSV"}))) == [
        "2026/q1.csv",
        "2026/q2.csv",
    ]
    sensitive = {"uri": TREE, "pattern": "Q?.CSV", "case_sensitive": True}
    assert _paths(succeed(kit.call("file_search", sensitive))) == []


def test_a_pattern_with_a_slash_is_matched_against_the_path() -> None:
    kit = toolkit()
    body = succeed(kit.call("file_search", {"uri": TREE, "pattern": "2026/*/*.txt"}))
    assert _paths(body) == ["2026/notes/todo.txt"]


def test_file_search_without_recursion_stays_in_the_directory() -> None:
    body = succeed(toolkit().call("file_search", {"uri": TREE, "recursive": False}))
    assert _paths(body) == ["readme.txt"]


def test_file_search_by_content_returns_the_first_matching_line() -> None:
    body = succeed(toolkit().call("file_search", {"uri": TREE, "content": "needle"}))
    assert _paths(body) == ["2026/notes/todo.txt", "2026/q2.csv", "readme.txt"]
    todo, q2, readme = body["matches"]
    assert (todo["line"], todo["snippet"], todo["matching_lines"]) == (1, "find the needle", 2)
    assert (q2["line"], q2["snippet"]) == (3, "NEEDLE,30")
    assert readme["line"] == 1
    assert (body["searched_files"], body["complete"], body["skipped"]) == (4, True, [])
    assert body["searched_bytes"] == sum(len(text) for text in FILES.values())
    sensitive = {"uri": TREE, "content": "needle", "case_sensitive": True}
    assert _paths(succeed(toolkit().call("file_search", sensitive))) == [
        "2026/notes/todo.txt",
        "readme.txt",
    ]


def test_file_search_combines_the_name_and_the_content() -> None:
    body = succeed(
        toolkit().call("file_search", {"uri": TREE, "pattern": "*.csv", "content": "needle"})
    )
    assert _paths(body) == ["2026/q2.csv"]
    assert body["searched_files"] == 2


def test_file_search_stops_at_the_result_cap() -> None:
    by_name = succeed(toolkit().call("file_search", {"uri": TREE, "max_results": 1}))
    assert (by_name["count"], by_name["truncated"]) == (1, True)
    by_content = succeed(
        toolkit().call("file_search", {"uri": TREE, "content": "needle", "max_results": 1})
    )
    assert _paths(by_content) == ["2026/notes/todo.txt"]
    assert (by_content["truncated"], by_content["complete"]) == (True, False)
    assert by_content["searched_files"] == 1


def test_a_content_search_reads_no_more_than_its_budget() -> None:
    File(f"{TREE}/big.log").write("x" * 500 + " needle")
    kit = toolkit(max_search_bytes=100)
    body = succeed(kit.call("file_search", {"uri": TREE, "content": "needle"}))
    assert body["searched_bytes"] <= 100
    assert body["complete"] is False
    skipped = {entry["uri"]: entry["reason"] for entry in body["skipped"]}
    assert "read budget" in skipped[f"{TREE}/big.log"]
    assert f"{TREE}/big.log" not in [match["uri"] for match in body["matches"]]
    assert body["skipped_count"] == len(skipped)


def test_a_content_search_skips_binary_files_and_files_it_cannot_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    File(f"{TREE}/blob.bin").write(b"\x00\x01needle\x00")
    real = File.open_read

    def flaky(self: File):
        if self.name == "q1.csv":
            raise StorageTransientException("the backend timed out")
        return real(self)

    monkeypatch.setattr(File, "open_read", flaky)
    body = succeed(toolkit().call("file_search", {"uri": TREE, "content": "needle"}))
    reasons = {entry["uri"]: entry["reason"] for entry in body["skipped"]}
    assert reasons == {
        f"{TREE}/blob.bin": "not a text file",
        f"{TREE}/2026/q1.csv": "StorageTransientException",
    }
    assert body["complete"] is False
    assert len(body["matches"]) == 3


def test_a_pattern_or_a_needle_that_is_too_long_is_refused() -> None:
    kit = toolkit()
    failed(kit.call("file_search", {"uri": TREE, "pattern": "*" * 300}), "invalid_arguments")
    failed(kit.call("file_search", {"uri": TREE, "content": "n" * 2000}), "invalid_arguments")
    failed(kit.call("file_search", {"uri": TREE, "content": ""}), "invalid_arguments")


def test_file_search_does_not_follow_a_link_out_of_a_local_root(tmp_path: Path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "inside.txt").write_text("needle inside", encoding="utf-8")
    (outside / "secret.txt").write_text("needle outside", encoding="utf-8")
    link = root / "escape"
    link_directory(link, outside)
    try:
        kit = SemanticToolkit(MCPPolicy(roots=[root]))
        body = succeed(kit.call("file_search", {"uri": str(root), "content": "needle"}))
        assert _paths(body) == ["inside.txt"]
        refused(kit.call("file_search", {"uri": str(link), "content": "needle"}), OUTSIDE_ROOT)
    finally:
        remove_link(link)


# ---------------------------------------------------------------------- storage_copy


def test_storage_copy_of_a_file_behaves_like_file_copy() -> None:
    source, target = f"{TREE}/readme.txt", f"{INBOX}/readme-copy.txt"
    body = succeed(writable().call("storage_copy", {"source": source, "target": target}))
    assert (body["kind"], body["done"], body["size"]) == ("file", True, 38)
    assert File(target).read() == File(source).read()
    verified = succeed(
        writable().call(
            "storage_copy", {"source": source, "target": f"{INBOX}/v.txt", "verify": True}
        )
    )
    assert verified["verified"] is True


def test_storage_copy_of_a_tree_plans_first_and_then_copies() -> None:
    kit = writable()
    plan = succeed(kit.call("storage_copy", {"source": TREE, "target": COPY, "dry_run": True}))
    assert (plan["kind"], plan["dry_run"], plan["done"]) == ("tree", True, False)
    assert plan["planned"] == {
        "copy": 4,
        "overwrite": 0,
        "skip": 0,
        "bytes": sum(len(text) for text in FILES.values()),
    }
    assert plan["paths"] == sorted(FILES)
    assert plan["existing"] == []
    assert not Storage(COPY).exists()
    done = succeed(kit.call("storage_copy", {"source": TREE, "target": COPY}))
    assert (done["done"], done["ok"], done["copied"], done["failed"]) == (True, True, 4, 0)
    for path, content in FILES.items():
        assert File(f"{COPY}/{path}").read_text() == content


def test_a_tree_copy_skips_existing_files_unless_overwriting_is_asked_and_allowed() -> None:
    File(f"{COPY}/readme.txt").write("kept")
    kit = writable()
    plan = succeed(kit.call("storage_copy", {"source": TREE, "target": COPY, "dry_run": True}))
    assert plan["planned"]["copy"] == 3
    assert plan["planned"]["skip"] == 1
    assert plan["existing"] == ["readme.txt"]
    arguments = {"source": TREE, "target": COPY, "overwrite": True}
    refused(kit.call("storage_copy", {**arguments, "dry_run": True}), OVERWRITE_NOT_ALLOWED)
    refused(kit.call("storage_copy", arguments), OVERWRITE_NOT_ALLOWED)
    done = succeed(kit.call("storage_copy", {"source": TREE, "target": COPY}))
    assert (done["copied"], done["skipped"]) == (3, 1)
    assert File(f"{COPY}/readme.txt").read() == b"kept"
    allowed = writable(allow_overwrite=True)
    plan = succeed(allowed.call("storage_copy", {**arguments, "dry_run": True}))
    assert plan["planned"]["overwrite"] == 4
    replaced = succeed(allowed.call("storage_copy", arguments))
    assert (replaced["copied"], replaced["skipped"]) == (4, 0)
    assert File(f"{COPY}/readme.txt").read_text() == FILES["readme.txt"]


def test_a_tree_copy_reports_the_files_that_failed_as_an_error_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = File.copy_to

    def flaky(self: File, target, *, overwrite: bool = True) -> File:
        if self.name == "q1.csv":
            raise StorageTransientException("the backend timed out")
        return real(self, target, overwrite=overwrite)

    monkeypatch.setattr(File, "copy_to", flaky)
    outcome = writable().call("storage_copy", {"source": TREE, "target": COPY})
    error = failed(outcome, "failed")
    assert "finished with failures" in error["message"]
    body = outcome.payload
    assert (body["ok"], body["copied"], body["failed"]) == (False, 3, 1)
    assert "StorageTransientException" in body["errors"]["2026/q1.csv"]


def test_a_tree_cannot_be_copied_into_itself_or_out_of_the_roots() -> None:
    kit = writable()
    inside = kit.call("storage_copy", {"source": TREE, "target": f"{TREE}/2026/again"})
    assert "inside" in failed(inside, "invalid_arguments")["message"]
    same = kit.call("storage_copy", {"source": TREE, "target": TREE})
    failed(same, "invalid_arguments")
    refused(kit.call("storage_copy", {"source": TREE, "target": f"{BOX}/elsewhere"}), OUTSIDE_ROOT)
    assert not Storage(f"{BOX}/elsewhere").exists()


def test_storage_copy_is_refused_on_a_read_only_server() -> None:
    refused(toolkit().call("storage_copy", {"source": TREE, "target": COPY}), READ_ONLY)
    failed(
        writable().call("storage_copy", {"source": f"{INBOX}/absent", "target": COPY}),
        ("not_found"),
    )


def test_the_lists_of_a_tree_plan_are_capped() -> None:
    kit = writable(max_results=2)
    plan = succeed(kit.call("storage_copy", {"source": TREE, "target": COPY, "dry_run": True}))
    assert plan["planned"]["copy"] == 4
    assert len(plan["paths"]) == 2
    assert plan["truncated"] is True
