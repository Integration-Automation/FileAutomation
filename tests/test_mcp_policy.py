"""The permission model of the semantic MCP tools: ``MCPPolicy`` and ``StorageGuard``."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from automation_file.exceptions import (
    MCPServerException,
    StoragePermissionException,
    StorageURIException,
)
from automation_file.server.mcp_policy import (
    DEFAULT_MAX_READ_BYTES,
    DEFAULT_MAX_RESULTS,
    DELETE_NOT_ALLOWED,
    NO_ROOT,
    OUTSIDE_ROOT,
    OVERWRITE_NOT_ALLOWED,
    READ_ONLY,
    SEMANTIC_TOOL_NAMES,
    TOOL_DISABLED,
    MCPLocationException,
    MCPPermissionException,
    MCPPolicy,
    StorageGuard,
    names_windows_device,
    path_below,
)
from automation_file.storage import (
    File,
    LocalStorage,
    MemoryStorage,
    StorageResolver,
    clear_memory_stores,
    parse_storage_uri,
)
from tests.mcp_support import link_directory, remove_link

WINDOWS = os.sep == "\\"


@pytest.fixture(autouse=True)
def _memory() -> Iterator[None]:
    clear_memory_stores()
    yield
    clear_memory_stores()


@pytest.fixture
def links() -> Iterator[list[Path]]:
    """Collects the links a test made, so they are removed before the temporary tree is."""
    made: list[Path] = []
    yield made
    for link in made:
        remove_link(link)


def _uri(text: str):
    return parse_storage_uri(text)


def _refusal(policy: MCPPolicy, text: str) -> MCPLocationException:
    with pytest.raises(MCPLocationException) as caught:
        policy.candidates(_uri(text))
    return caught.value


# ---------------------------------------------------------------------- the policy object


def test_the_default_policy_allows_no_location_and_no_change() -> None:
    policy = MCPPolicy()
    assert policy.roots == ()
    assert (policy.allow_write, policy.allow_overwrite, policy.allow_delete) == (False,) * 3
    assert policy.max_read_bytes == DEFAULT_MAX_READ_BYTES
    assert policy.max_results == DEFAULT_MAX_RESULTS
    assert policy.pipeline_dir is None
    assert policy.pipeline_actions is None
    assert policy.enabled_tools() == SEMANTIC_TOOL_NAMES
    assert policy.actor == "mcp"


def test_there_are_fourteen_tools_with_the_roadmap_names() -> None:
    assert SEMANTIC_TOOL_NAMES == (
        "file_read",
        "file_write",
        "file_copy",
        "file_move",
        "file_search",
        "file_checksum",
        "file_verify",
        "storage_list",
        "storage_copy",
        "pipeline_create",
        "pipeline_run",
        "pipeline_status",
        "integrity_status",
        "audit_search",
    )


def test_roots_are_parsed_into_storage_uris(tmp_path: Path) -> None:
    policy = MCPPolicy(
        roots=[tmp_path, "s3://bucket/team/", "file:///srv/data", "s3://bucket/team"]
    )
    schemes = [root.scheme for root in policy.root_uris]
    assert schemes == ["local", "s3", "local"]
    assert str(policy.root_uris[1]) == "s3://bucket/team"
    assert policy.root_uris[0] == parse_storage_uri(tmp_path)


def test_one_root_may_be_given_without_a_list() -> None:
    assert [str(root) for root in MCPPolicy(roots="memory://box/in").root_uris] == [
        "memory://box/in"
    ]


def test_a_policy_cannot_be_changed() -> None:
    policy = MCPPolicy(roots=["memory://box"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.allow_write = True  # type: ignore[misc]
    assert isinstance(policy.roots, tuple)
    assert hash(policy) == hash(MCPPolicy(roots=["memory://box"]))


def test_a_root_with_credentials_is_refused_without_repeating_them() -> None:
    with pytest.raises(MCPServerException) as caught:
        MCPPolicy(roots=["sftp://alice:hunter2@nas/data"])
    assert "hunter2" not in str(caught.value)
    assert "alice" not in str(caught.value)


def test_overwrite_and_delete_need_write() -> None:
    with pytest.raises(MCPServerException, match="need allow_write"):
        MCPPolicy(allow_overwrite=True)
    with pytest.raises(MCPServerException, match="need allow_write"):
        MCPPolicy(allow_delete=True)
    assert MCPPolicy(allow_write=True, allow_overwrite=True, allow_delete=True).allow_delete


@pytest.mark.parametrize("value", [0, -1, True, "5", 1.5])
@pytest.mark.parametrize(
    "limit", ["max_read_bytes", "max_write_bytes", "max_results", "max_search_bytes"]
)
def test_a_limit_is_a_positive_integer(limit: str, value: object) -> None:
    with pytest.raises(MCPServerException, match=limit):
        MCPPolicy(**{limit: value})


def test_the_tool_list_takes_only_known_names_and_keeps_catalogue_order() -> None:
    policy = MCPPolicy(tools=["storage_list", "file_read"])
    assert policy.enabled_tools() == ("file_read", "storage_list")
    assert MCPPolicy(tools=[]).enabled_tools() == ()
    with pytest.raises(MCPServerException, match="file_delete"):
        MCPPolicy(tools=["file_read", "file_delete"])


def test_a_disabled_tool_is_refused_by_name() -> None:
    policy = MCPPolicy(tools=["file_read"])
    policy.require_tool("file_read")
    with pytest.raises(MCPPermissionException) as caught:
        policy.require_tool("file_write")
    assert caught.value.code == TOOL_DISABLED


def test_pipeline_actions_become_a_frozen_set_of_names() -> None:
    policy = MCPPolicy(pipeline_actions=["FA_storage_copy", " FA_notify_send "])
    assert policy.pipeline_actions == frozenset({"FA_storage_copy", "FA_notify_send"})
    with pytest.raises(MCPServerException, match="pipeline_actions"):
        MCPPolicy(pipeline_actions=["FA_storage_copy", 3])


def test_an_empty_actor_is_refused() -> None:
    with pytest.raises(MCPServerException, match="actor"):
        MCPPolicy(actor=" ")


def test_the_permission_checks_name_the_flag_that_would_allow_the_call() -> None:
    read_only = MCPPolicy()
    with pytest.raises(MCPPermissionException, match="--allow-write") as caught:
        read_only.require_write("file_write")
    assert caught.value.code == READ_ONLY
    writer = MCPPolicy(allow_write=True)
    writer.require_write("file_write")
    with pytest.raises(MCPPermissionException, match="--allow-overwrite") as caught:
        writer.require_overwrite("file_write")
    assert caught.value.code == OVERWRITE_NOT_ALLOWED
    with pytest.raises(MCPPermissionException, match="--allow-delete") as caught:
        writer.require_delete("file_move")
    assert caught.value.code == DELETE_NOT_ALLOWED
    with pytest.raises(MCPPermissionException) as caught:
        read_only.require_delete("file_move")
    assert caught.value.code == READ_ONLY


def test_results_are_clamped_to_the_policy() -> None:
    policy = MCPPolicy(max_results=10)
    assert policy.clamp_results(None) == 10
    assert policy.clamp_results(3) == 3
    assert policy.clamp_results(500) == 10


def test_describe_and_summary_say_what_is_allowed() -> None:
    policy = MCPPolicy(roots=["memory://box/in"], allow_write=True, tools=["file_read"])
    described = policy.describe()
    assert described["roots"] == ["memory://box/in"]
    assert described["allow_write"] is True
    assert described["tools"] == ["file_read"]
    assert described["pipeline_actions"] is None
    summary = policy.summary()
    assert "memory://box/in" in summary
    assert "Allowed: reading, writing." in summary
    assert "Refused: replacing existing files, deleting" in summary
    assert "No location is allowed yet." in MCPPolicy().summary()


# ---------------------------------------------------------------------- which locations


def test_without_a_root_every_location_is_refused_with_how_to_add_one() -> None:
    error = _refusal(MCPPolicy(), "memory://box/in/a.txt")
    assert error.code == NO_ROOT
    assert "--root" in str(error)
    assert "MCPPolicy(roots=" in str(error)


def test_a_location_at_or_below_a_root_is_allowed() -> None:
    policy = MCPPolicy(roots=["s3://bucket/team"])
    assert policy.candidates(_uri("s3://bucket/team")) == [(_uri("s3://bucket/team"), "")]
    assert policy.candidates(_uri("s3://bucket/team/2026/a.csv"))[0][1] == "2026/a.csv"


@pytest.mark.parametrize(
    "location",
    [
        "s3://bucket/team-b/a.csv",
        "s3://bucket/tea",
        "s3://bucket/a.csv",
        "s3://bucket",
        "s3://bucket-2/team/a.csv",
        "azure://bucket/team/a.csv",
        "memory://bucket/team/a.csv",
    ],
)
def test_a_sibling_prefix_another_authority_or_another_scheme_is_outside(location: str) -> None:
    error = _refusal(MCPPolicy(roots=["s3://bucket/team"]), location)
    assert error.code == OUTSIDE_ROOT
    assert "s3://bucket/team" in str(error)


def test_the_authority_is_compared_exactly() -> None:
    # memory://Box and memory://box are two different stores.
    assert _refusal(MCPPolicy(roots=["memory://box/in"]), "memory://Box/in/a.txt").code == (
        OUTSIDE_ROOT
    )


def test_nested_roots_are_tried_outermost_first() -> None:
    policy = MCPPolicy(roots=["s3://bucket/team/public", "s3://bucket/team"])
    found = policy.candidates(_uri("s3://bucket/team/public/a.csv"))
    assert [str(root) for root, _ in found] == ["s3://bucket/team", "s3://bucket/team/public"]
    assert [relative for _, relative in found] == ["public/a.csv", "a.csv"]


def test_is_root_recognises_only_the_roots_themselves() -> None:
    policy = MCPPolicy(roots=["memory://box/in"])
    assert policy.is_root(_uri("memory://box/in")) is True
    assert policy.is_root(_uri("memory://box/in/a")) is False
    assert policy.is_root(_uri("memory://box")) is False


def test_path_below_compares_whole_segments() -> None:
    assert path_below(_uri("s3://b/team"), _uri("s3://b/team/x/y")) == "x/y"
    assert path_below(_uri("s3://b/team"), _uri("s3://b/team")) == ""
    assert path_below(_uri("s3://b/team"), _uri("s3://b/team-b/x")) is None
    assert path_below(_uri("s3://b"), _uri("s3://b/anything")) == "anything"


def test_a_location_refusal_is_a_permission_error_of_both_kinds() -> None:
    error = _refusal(MCPPolicy(roots=["memory://box"]), "memory://other/a")
    assert isinstance(error, MCPPermissionException)
    assert isinstance(error, StoragePermissionException)
    assert isinstance(error, MCPServerException)


# ---------------------------------------------------------------------- the guard


def test_the_guard_serves_a_memory_root_and_refuses_its_neighbour() -> None:
    guard = StorageGuard(MCPPolicy(roots=["memory://box/in"]))
    File("memory://box/in/a.txt").write("inside")
    File("memory://box/in-b/a.txt").write("neighbour")
    assert File("memory://box/in/a.txt", resolver=guard).read() == b"inside"
    with pytest.raises(MCPLocationException) as caught:
        File("memory://box/in-b/a.txt", resolver=guard).read()
    assert caught.value.code == OUTSIDE_ROOT


def test_dot_dot_never_reaches_the_guard() -> None:
    guard = StorageGuard(MCPPolicy(roots=["memory://box/in"]))
    with pytest.raises(StorageURIException, match=r"\.\."):
        File("memory://box/in/../secret.txt", resolver=guard)


def test_a_local_root_is_served_by_a_backend_confined_to_it(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("inside", encoding="utf-8")
    guard = StorageGuard(MCPPolicy(roots=[root]))
    backend, path = guard.resolve(root / "a.txt")
    assert isinstance(backend, LocalStorage)
    assert backend.root == root.resolve()
    assert path == "a.txt"
    assert File(root / "a.txt", resolver=guard).read() == b"inside"
    assert guard.resolve(root)[1] == ""


def test_a_local_file_next_to_the_root_is_outside(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "root-b").mkdir()
    (tmp_path / "root-b" / "a.txt").write_text("neighbour", encoding="utf-8")
    guard = StorageGuard(MCPPolicy(roots=[root]))
    for outside in (tmp_path / "root-b" / "a.txt", tmp_path / "a.txt", tmp_path):
        with pytest.raises(MCPLocationException) as caught:
            guard.resolve(outside)
        assert caught.value.code == OUTSIDE_ROOT


def test_a_link_out_of_a_local_root_is_refused(tmp_path: Path, links: list[Path]) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link_directory(root / "escape", outside)
    links.append(root / "escape")
    guard = StorageGuard(MCPPolicy(roots=[root]))
    with pytest.raises(MCPLocationException) as caught:
        File(root / "escape" / "secret.txt", resolver=guard).read()
    assert caught.value.code == OUTSIDE_ROOT
    assert "link" in str(caught.value)
    with pytest.raises(MCPLocationException):
        File(root / "escape" / "new.txt", resolver=guard).write("x")
    assert not (outside / "new.txt").exists()


def test_a_link_that_stays_inside_a_local_root_is_followed(
    tmp_path: Path, links: list[Path]
) -> None:
    root = tmp_path / "root"
    (root / "real").mkdir(parents=True)
    (root / "real" / "a.txt").write_text("inside", encoding="utf-8")
    link_directory(root / "alias", root / "real")
    links.append(root / "alias")
    guard = StorageGuard(MCPPolicy(roots=[root]))
    assert File(root / "alias" / "a.txt", resolver=guard).read() == b"inside"


def test_a_link_between_two_roots_is_allowed_by_the_outer_one(
    tmp_path: Path, links: list[Path]
) -> None:
    outer = tmp_path / "outer"
    (outer / "public").mkdir(parents=True)
    (outer / "private").mkdir()
    (outer / "private" / "a.txt").write_text("kept", encoding="utf-8")
    link_directory(outer / "public" / "to-private", outer / "private")
    links.append(outer / "public" / "to-private")
    linked = outer / "public" / "to-private" / "a.txt"
    only_public = StorageGuard(MCPPolicy(roots=[outer / "public"]))
    with pytest.raises(MCPLocationException):
        File(linked, resolver=only_public).read()
    both = StorageGuard(MCPPolicy(roots=[outer / "public", outer]))
    assert File(linked, resolver=both).read() == b"kept"


@pytest.mark.skipif(not WINDOWS, reason="drive letters and case folding are Windows behaviour")
def test_windows_paths_are_matched_without_regard_to_case_and_slashes(tmp_path: Path) -> None:
    root = tmp_path / "Root"
    root.mkdir()
    (root / "a.txt").write_text("inside", encoding="utf-8")
    guard = StorageGuard(MCPPolicy(roots=[root]))
    shouted = f"local:///{str(root).upper()}/a.txt".replace("\\", "/")
    assert File(shouted, resolver=guard).read() == b"inside"
    backslashed = f"local:///{root}\\a.txt"
    assert File(backslashed, resolver=guard).read() == b"inside"
    with pytest.raises((MCPLocationException, StorageURIException)):
        File(f"local:///{root}\\..\\outside.txt", resolver=guard).exists()


@pytest.mark.skipif(not WINDOWS, reason="an absolute path with a drive letter")
def test_an_absolute_path_smuggled_below_a_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    guard = StorageGuard(MCPPolicy(roots=[root]))
    smuggled = f"local:///{root.as_posix()}/C:/Windows/win.ini"
    with pytest.raises(MCPLocationException):
        File(smuggled, resolver=guard).exists()


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("reports/CON", True),
        ("reports/nul.txt", True),
        ("COM1", True),
        ("a/lpt9.log/b.txt", True),
        ("a/aux ", True),
        ("a.txt:hidden", True),
        ("C:/Windows/win.ini", True),
        ("reports/a.csv", False),
        ("console/nullable.txt", False),
        ("com10", False),
        ("", False),
    ],
)
def test_windows_device_and_stream_names_are_recognised(relative: str, expected: bool) -> None:
    assert names_windows_device(relative) is expected


@pytest.mark.skipif(not WINDOWS, reason="device names and data streams are Windows behaviour")
def test_a_windows_device_or_data_stream_below_a_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("inside", encoding="utf-8")
    guard = StorageGuard(MCPPolicy(roots=[root]))
    base = f"local:///{root.as_posix()}"
    for name in ("NUL", "sub/CON", "com1.txt", "a.txt::$DATA", "b.txt:stream"):
        with pytest.raises(MCPLocationException, match="Windows device or a data stream") as caught:
            guard.resolve(f"{base}/{name}")
        assert caught.value.code == OUTSIDE_ROOT
    assert File(f"{base}/a.txt", resolver=guard).read() == b"inside"


def test_other_backends_are_resolved_by_the_inner_resolver() -> None:
    inner = StorageResolver(defaults=False)
    mounted = MemoryStorage("mounted")
    inner.mount("vault://jobs", mounted)
    guard = StorageGuard(MCPPolicy(roots=["vault://jobs/out"]), inner)
    assert guard.inner is inner
    assert guard.resolve("vault://jobs/out/a.txt") == (mounted, "out/a.txt")
    with pytest.raises(MCPLocationException):
        guard.resolve("vault://jobs/private/a.txt")


def test_a_root_below_a_mounted_local_backend_is_confined_to_the_root(
    tmp_path: Path, links: list[Path]
) -> None:
    jobs = tmp_path / "jobs"
    (jobs / "out").mkdir(parents=True)
    (jobs / "private").mkdir()
    (jobs / "private" / "a.txt").write_text("private", encoding="utf-8")
    link_directory(jobs / "out" / "sideways", jobs / "private")
    links.append(jobs / "out" / "sideways")
    inner = StorageResolver(defaults=False)
    inner.mount("sandbox://jobs", LocalStorage(jobs))
    guard = StorageGuard(MCPPolicy(roots=["sandbox://jobs/out"]), inner)
    backend, path = guard.resolve("sandbox://jobs/out/new.txt")
    assert isinstance(backend, LocalStorage)
    assert backend.root == (jobs / "out").resolve()
    assert path == "new.txt"
    # The mount itself would allow the link: it stays inside jobs/. The root does not.
    with pytest.raises(MCPLocationException):
        guard.resolve("sandbox://jobs/out/sideways/a.txt")


def test_a_root_that_is_a_mount_point_uses_the_mounted_backend(
    tmp_path: Path, links: list[Path]
) -> None:
    jobs, outside = tmp_path / "jobs", tmp_path / "outside"
    jobs.mkdir()
    outside.mkdir()
    link_directory(jobs / "escape", outside)
    links.append(jobs / "escape")
    inner = StorageResolver(defaults=False)
    mounted = LocalStorage(jobs)
    inner.mount("sandbox://jobs", mounted)
    guard = StorageGuard(MCPPolicy(roots=["sandbox://jobs"]), inner)
    assert guard.resolve("sandbox://jobs/a/b.txt") == (mounted, "a/b.txt")
    with pytest.raises(MCPLocationException) as caught:
        guard.resolve("sandbox://jobs/escape/secret.txt")
    assert caught.value.code == OUTSIDE_ROOT


def test_a_root_that_is_the_whole_filesystem_is_not_confined(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("anywhere", encoding="utf-8")
    guard = StorageGuard(MCPPolicy(roots=["local:///"]))
    backend, _path = guard.resolve(tmp_path / "a.txt")
    assert isinstance(backend, LocalStorage)
    assert backend.root is None
    assert File(tmp_path / "a.txt", resolver=guard).read() == b"anywhere"
