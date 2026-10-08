"""Unit tests for the shared action ACL."""

from __future__ import annotations

import pytest

from automation_file import ActionACL, ActionNotPermittedException


def test_default_acl_permits_all() -> None:
    acl = ActionACL()
    acl.enforce([["FA_anything"], ["FA_other", {}]])
    assert acl.is_allowed("anything") is True


def test_allowlist_rejects_outside_names() -> None:
    acl = ActionACL.build(allowed=["FA_list"])
    with pytest.raises(ActionNotPermittedException):
        acl.enforce([["FA_run_shell", {"argv": ["echo"]}]])


def test_allowlist_permits_listed_names() -> None:
    acl = ActionACL.build(allowed=["FA_list", "FA_create_file"])
    acl.enforce([["FA_list"], ["FA_create_file", {"file_path": "x"}]])


def test_denylist_wins_over_allowlist() -> None:
    acl = ActionACL.build(allowed=["FA_foo"], denied=["FA_foo"])
    with pytest.raises(ActionNotPermittedException):
        acl.enforce([["FA_foo"]])


def test_enforce_accepts_dict_payload_shape() -> None:
    acl = ActionACL.build(allowed=["FA_foo"])
    acl.enforce({"actions": [["FA_foo"]]})
    with pytest.raises(ActionNotPermittedException):
        acl.enforce({"actions": [["FA_bar"]]})


def test_enforce_ignores_malformed_entries() -> None:
    acl = ActionACL.build(allowed=["FA_foo"])
    # Non-list / empty / non-string-first entries are skipped silently.
    acl.enforce([[], [1, 2], "garbage"])  # type: ignore[list-item]


def test_an_action_nested_in_an_action_list_is_checked() -> None:
    acl = ActionACL.build(denied=["FA_run_shell"])
    nested = [["FA_execute_action", [[["FA_run_shell", {"argv": ["echo"]}]]]]]
    with pytest.raises(ActionNotPermittedException, match="FA_run_shell"):
        acl.enforce(nested)
    acl.enforce([["FA_execute_action", [[["FA_create_file", {"file_path": "x"}]]]]])


def test_an_action_named_by_a_pipeline_definition_is_checked() -> None:
    acl = ActionACL.build(allowed=["FA_pipeline_run", "FA_storage_copy"])
    definition = {
        "schema_version": 1,
        "name": "copy",
        "tasks": {
            "copy": {"action": ["FA_storage_copy", {"source": "a", "target": "b"}]},
            "wipe": {"action": ["FA_storage_delete", {"uri": "b"}], "depends_on": ["copy"]},
        },
    }
    with pytest.raises(ActionNotPermittedException, match="FA_storage_delete"):
        acl.enforce([["FA_pipeline_run", {"definition": definition}]])
    del definition["tasks"]["wipe"]
    acl.enforce([["FA_pipeline_run", {"definition": definition}]])


def test_a_nested_name_is_found_under_a_key_and_at_any_depth() -> None:
    acl = ActionACL.build(denied=["FA_storage_delete"])
    deep: object = "FA_storage_delete"
    for _ in range(5000):
        deep = [deep]
    with pytest.raises(ActionNotPermittedException):
        acl.enforce([["FA_execute_action", deep]])
    with pytest.raises(ActionNotPermittedException):
        acl.enforce([["FA_schedule_add", {"job": {"FA_storage_delete": {"uri": "b"}}}]])


def test_arguments_that_are_not_action_names_pass_an_allow_list() -> None:
    acl = ActionACL.build(allowed=["FA_storage_copy"])
    acl.enforce([["FA_storage_copy", {"source": "reports/q1.csv", "target": ["a", "b"]}]])
    acl.enforce([["FA_storage_copy", ["local:///a.txt", "local:///b.txt"]]])
