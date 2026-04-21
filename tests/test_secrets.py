"""Tests for automation_file.core.secrets."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.core.secrets import (
    ChainedSecretProvider,
    EnvSecretProvider,
    FileSecretProvider,
    SecretNotFoundException,
    default_provider,
    resolve_secret_refs,
)


def test_env_provider_reads_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SECRET", "top-secret")
    assert EnvSecretProvider().get("MY_SECRET") == "top-secret"
    assert EnvSecretProvider().get("NO_SUCH_VAR") is None


def test_file_provider_reads_file_without_trailing_newline(tmp_path: Path) -> None:
    (tmp_path / "webhook").write_text("https://example.com/x\n", encoding="utf-8")
    provider = FileSecretProvider(tmp_path)
    assert provider.get("webhook") == "https://example.com/x"
    assert provider.get("missing") is None


def test_chain_tries_each_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FROM_ENV", "e-value")
    (tmp_path / "FROM_FILE").write_text("f-value", encoding="utf-8")
    chain = ChainedSecretProvider([EnvSecretProvider(), FileSecretProvider(tmp_path)])
    assert chain.resolve_one("env", "FROM_ENV") == "e-value"
    assert chain.resolve_one("file", "FROM_FILE") == "f-value"


def test_chain_scheme_scoped_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONLY_ENV", "from-env")
    chain = ChainedSecretProvider([EnvSecretProvider(), FileSecretProvider(tmp_path)])
    # file:ONLY_ENV must not fall through to the env provider.
    with pytest.raises(SecretNotFoundException):
        chain.resolve_one("file", "ONLY_ENV")


def test_resolve_secret_refs_substitutes_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOOK", "https://hooks.slack.com/services/T/B/X")
    chain = default_provider()
    result = resolve_secret_refs({"url": "${env:HOOK}", "static": "hi"}, chain)
    assert result == {"url": "https://hooks.slack.com/services/T/B/X", "static": "hi"}


def test_resolve_secret_refs_walks_nested_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("U", "me")
    monkeypatch.setenv("P", "pw")
    chain = default_provider()
    result = resolve_secret_refs(
        {
            "notify": {
                "sinks": [
                    {"username": "${env:U}", "password": "${env:P}", "port": 587},
                ]
            }
        },
        chain,
    )
    assert result["notify"]["sinks"][0]["username"] == "me"
    assert result["notify"]["sinks"][0]["password"] == "pw"
    assert result["notify"]["sinks"][0]["port"] == 587


def test_resolve_secret_refs_raises_on_missing() -> None:
    chain = default_provider()
    with pytest.raises(SecretNotFoundException, match="DOES_NOT_EXIST"):
        resolve_secret_refs("${env:DOES_NOT_EXIST}", chain)


def test_resolve_secret_refs_multiple_in_one_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USER", "alice")
    monkeypatch.setenv("HOST", "smtp.example.com")
    chain = default_provider()
    assert resolve_secret_refs("${env:USER}@${env:HOST}", chain) == "alice@smtp.example.com"


def test_resolve_secret_refs_non_string_pass_through() -> None:
    chain = default_provider()
    assert resolve_secret_refs(42, chain) == 42
    assert resolve_secret_refs(None, chain) is None
    assert resolve_secret_refs(True, chain) is True


def test_default_provider_includes_file_root_when_given(tmp_path: Path) -> None:
    (tmp_path / "smtp_pw").write_text("secret", encoding="utf-8")
    chain = default_provider(tmp_path)
    assert chain.resolve_one("file", "smtp_pw") == "secret"
