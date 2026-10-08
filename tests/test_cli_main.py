"""Tests for ``automation_file.__main__`` subcommand wiring."""

from __future__ import annotations

import json
from typing import Any

import pytest

from automation_file import __main__ as cli_main


def test_mcp_subcommand_forwards_all_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}

    def _fake_cli(argv: list[str] | None = None) -> int:
        captured["argv"] = list(argv or [])
        return 0

    monkeypatch.setattr("automation_file.server.mcp_server._cli", _fake_cli)

    rc = cli_main.main(
        [
            "mcp",
            "--name",
            "svc",
            "--version",
            "3.2.1",
            "--allowed-actions",
            "FA_file_checksum,FA_fast_find",
        ]
    )

    assert rc == 0
    assert captured["argv"] == [
        "--name",
        "svc",
        "--version",
        "3.2.1",
        "--allowed-actions",
        "FA_file_checksum,FA_fast_find",
    ]


def test_mcp_subcommand_omits_allowed_actions_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[str]] = {}

    def _fake_cli(argv: list[str] | None = None) -> int:
        captured["argv"] = list(argv or [])
        return 0

    monkeypatch.setattr("automation_file.server.mcp_server._cli", _fake_cli)

    rc = cli_main.main(["mcp"])

    assert rc == 0
    assert "--allowed-actions" not in captured["argv"]
    assert captured["argv"] == ["--name", "automation_file", "--version", "1.0.0"]


def _capture_execute_action(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    received: list[Any] = []

    def _fake_execute(action_list: Any) -> dict:
        received.append(action_list)
        return {}

    monkeypatch.setattr(cli_main, "execute_action", _fake_execute)
    return received


def test_execute_str_accepts_single_encoded_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = _capture_execute_action(monkeypatch)
    actions = [["FA_create_file", {"file_path": "x.txt", "content": "hi"}]]

    rc = cli_main.main(["--execute_str", json.dumps(actions)])

    assert rc == 0
    assert received == [actions]


def test_execute_str_accepts_double_encoded_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received = _capture_execute_action(monkeypatch)
    actions = [["FA_create_file", {"file_path": "x.txt", "content": "hi"}]]

    # PyBreeze on Windows wraps the JSON list once more before handing the
    # argument to subprocess; the CLI must peel both layers off.
    rc = cli_main.main(["--execute_str", json.dumps(json.dumps(actions))])

    assert rc == 0
    assert received == [actions]


def test_legacy_flag_returns_1_when_an_action_failed(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps([["FA_no_such_action"], ["FA_no_such_action"]]), encoding="utf-8")

    assert cli_main.main(["--execute_file", str(actions)]) == 1
    assert "error: 2 action(s) failed" in capsys.readouterr().err


def test_legacy_flag_returns_0_when_every_action_passed(tmp_path: Any) -> None:
    target = tmp_path / "created.txt"
    actions = tmp_path / "actions.json"
    actions.write_text(
        json.dumps([["FA_create_file", {"file_path": str(target), "content": "x"}]]),
        encoding="utf-8",
    )

    assert cli_main.main(["--execute_file", str(actions)]) == 0
    assert target.exists()


def test_failures_of_an_earlier_run_are_not_counted_again(tmp_path: Any) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([["FA_no_such_action"]]), encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps([["FA_create_file", {"file_path": str(tmp_path / "x.txt"), "content": "x"}]]),
        encoding="utf-8",
    )

    assert cli_main.main(["--execute_file", str(bad)]) == 1
    assert cli_main.main(["--execute_file", str(good)]) == 0
