"""Tests for automation_file.core.manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_file.core.manifest import (
    ManifestException,
    verify_manifest,
    write_manifest,
)
from automation_file.exceptions import DirNotExistsException


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_write_and_verify_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    manifest_path = tmp_path / "manifest.json"
    _touch(root / "a.txt", "one")
    _touch(root / "nested" / "b.txt", "two")

    manifest = write_manifest(root, manifest_path)
    assert manifest["version"] == 1
    assert manifest["algorithm"] == "sha256"
    assert set(manifest["files"].keys()) == {"a.txt", "nested/b.txt"}
    assert manifest["files"]["a.txt"]["size"] == 3

    result = verify_manifest(root, manifest_path)
    assert result["ok"] is True
    assert set(result["matched"]) == {"a.txt", "nested/b.txt"}
    assert result["missing"] == []
    assert result["modified"] == []


def test_verify_detects_modified_file(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    manifest_path = tmp_path / "m.json"
    _touch(root / "a.txt", "original")
    write_manifest(root, manifest_path)

    (root / "a.txt").write_text("tampered", encoding="utf-8")

    result = verify_manifest(root, manifest_path)
    assert result["ok"] is False
    assert result["modified"] == ["a.txt"]


def test_verify_detects_missing_file(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    manifest_path = tmp_path / "m.json"
    _touch(root / "gone.txt", "bye")
    write_manifest(root, manifest_path)

    (root / "gone.txt").unlink()

    result = verify_manifest(root, manifest_path)
    assert result["ok"] is False
    assert result["missing"] == ["gone.txt"]


def test_verify_reports_extras_without_failing(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    manifest_path = tmp_path / "m.json"
    _touch(root / "a.txt", "one")
    write_manifest(root, manifest_path)

    _touch(root / "unexpected.txt", "extra")

    result = verify_manifest(root, manifest_path)
    assert result["ok"] is True  # extras do not fail verification
    assert result["extra"] == ["unexpected.txt"]


def test_write_manifest_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(DirNotExistsException):
        write_manifest(tmp_path / "missing", tmp_path / "m.json")


def test_verify_manifest_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(DirNotExistsException):
        verify_manifest(tmp_path / "missing", tmp_path / "m.json")


def test_verify_manifest_rejects_missing_manifest(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    with pytest.raises(ManifestException, match="not found"):
        verify_manifest(root, tmp_path / "no-such-manifest.json")


def test_verify_manifest_rejects_bad_json(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestException, match="cannot read"):
        verify_manifest(root, bad)


def test_verify_manifest_rejects_malformed_document(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(ManifestException, match="'files'"):
        verify_manifest(root, bad)


def test_manifest_actions_registered() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    assert "FA_write_manifest" in registry
    assert "FA_verify_manifest" in registry


def test_manifest_custom_algorithm(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    manifest_path = tmp_path / "m.json"
    _touch(root / "a.txt", "data")

    manifest = write_manifest(root, manifest_path, algorithm="md5")
    assert manifest["algorithm"] == "md5"
    # md5 digests are 32 hex chars.
    assert len(manifest["files"]["a.txt"]["checksum"]) == 32

    assert verify_manifest(root, manifest_path)["ok"] is True


def test_manifest_size_mismatch_reports_modified(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    manifest_path = tmp_path / "m.json"
    _touch(root / "a.txt", "abc")
    write_manifest(root, manifest_path)

    # Tamper with size by appending.
    with (root / "a.txt").open("a", encoding="utf-8") as handle:
        handle.write("xyz")

    result = verify_manifest(root, manifest_path)
    assert result["modified"] == ["a.txt"]
    assert result["ok"] is False
