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
