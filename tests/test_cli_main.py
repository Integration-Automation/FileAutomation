"""Tests for ``automation_file.__main__`` subcommand wiring."""

from __future__ import annotations

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
