"""Checksum, FileInfo and StorageCapabilities value types."""

# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

import pytest

from automation_file.storage import Checksum, FileInfo, StorageCapabilities

DIGEST = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"


def test_checksum_is_normalised_to_lower_case() -> None:
    checksum = Checksum(" SHA256 ", f" {DIGEST.upper()} ")
    assert checksum == Checksum("sha256", DIGEST)
    assert str(checksum) == f"sha256:{DIGEST}"
    assert checksum.to_dict() == {"algorithm": "sha256", "value": DIGEST}


def test_checksum_parse() -> None:
    assert Checksum.parse(f"SHA256:{DIGEST}") == Checksum("sha256", DIGEST)
    assert Checksum.parse(str(Checksum("md5", "abc"))) == Checksum("md5", "abc")


@pytest.mark.parametrize("text", ["", DIGEST, "sha256:", ":abc", " : "])
def test_checksum_parse_rejects_text_without_both_parts(text: str) -> None:
    with pytest.raises(ValueError, match="sha256:<hex digest>"):
        Checksum.parse(text)


def test_checksum_matches() -> None:
    checksum = Checksum("sha256", DIGEST)
    assert checksum.matches(DIGEST) is True
    assert checksum.matches(f"  {DIGEST.upper()}\n") is True
    assert checksum.matches(f"sha256:{DIGEST}") is True
    assert checksum.matches(Checksum("SHA256", DIGEST)) is True
    assert checksum.matches(DIGEST[:-1] + "0") is False
    assert checksum.matches("") is False


def test_checksum_of_another_algorithm_never_matches() -> None:
    checksum = Checksum("sha256", DIGEST)
    assert checksum.matches(Checksum("sha512", DIGEST)) is False
    assert checksum.matches(f"md5:{DIGEST}") is False


def test_checksum_matches_tolerates_non_ascii_input() -> None:
    assert Checksum("sha256", DIGEST).matches("不是摘要") is False


def test_file_info_defaults_and_name() -> None:
    info = FileInfo("dir/sub/report.csv")
    assert info.name == "report.csv"
    assert info.is_dir is False
    assert info.size is None
    assert info.modified_at is None
    assert info.etag is None
    assert info.version is None
    assert info.content_type is None
    assert dict(info.metadata) == {}
    assert FileInfo("top.txt").name == "top.txt"
    assert FileInfo("", is_dir=True).name == ""


def test_file_info_is_frozen_and_hashable() -> None:
    info = FileInfo("a.txt", size=1, metadata={"owner": "ops"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.size = 2  # type: ignore[misc]
    assert info == FileInfo("a.txt", size=1, metadata={"owner": "ops"})
    assert info != FileInfo("a.txt", size=1, metadata={"owner": "dev"})
    assert len({info, FileInfo("a.txt", size=1, metadata={"owner": "ops"})}) == 1


def test_file_info_to_dict_is_json_serialisable() -> None:
    info = FileInfo(
        "dir/report.csv",
        size=12,
        modified_at=datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc),
        etag="abc",
        version="7",
        content_type="text/csv",
        metadata={"owner": "ops"},
    )
    document = json.loads(json.dumps(info.to_dict()))
    assert document == {
        "path": "dir/report.csv",
        "name": "report.csv",
        "is_dir": False,
        "size": 12,
        "modified_at": "2026-10-08T02:30:00+00:00",
        "etag": "abc",
        "version": "7",
        "content_type": "text/csv",
        "metadata": {"owner": "ops"},
    }
    assert FileInfo("dir", is_dir=True).to_dict()["modified_at"] is None


def test_capabilities_defaults_and_to_dict() -> None:
    capabilities = StorageCapabilities()
    assert capabilities.to_dict() == {
        "directories": True,
        "modified_at": True,
        "etag": False,
        "version": False,
        "content_type": False,
        "metadata": False,
    }
    assert StorageCapabilities(directories=False, etag=True).to_dict()["directories"] is False
