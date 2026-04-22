"""Tests for automation_file.core.content_store."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from automation_file.core.content_store import ContentStore
from automation_file.exceptions import CASException


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_put_bytes_roundtrip(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    digest = store.put_bytes(b"hello")
    assert digest == _sha(b"hello")
    assert store.exists(digest)
    with store.open(digest) as fh:
        assert fh.read() == b"hello"


def test_put_file_returns_matching_digest(tmp_path: Path) -> None:
    source = tmp_path / "src.bin"
    source.write_bytes(b"world")
    store = ContentStore(tmp_path / "cas")
    digest = store.put(source)
    assert digest == _sha(b"world")


def test_duplicate_put_is_idempotent(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    d1 = store.put_bytes(b"same")
    d2 = store.put_bytes(b"same")
    assert d1 == d2
    assert store.size() == 1


def test_path_layout_uses_fanout(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    digest = store.put_bytes(b"x")
    path = store.path_for(digest)
    assert path.parent.name == digest[:2]
    assert path.name == digest


def test_missing_blob_raises(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    with pytest.raises(CASException):
        store.open("0" * 64)


def test_invalid_digest_rejected(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    with pytest.raises(CASException):
        store.path_for("not-hex")


def test_copy_to_writes_blob(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    digest = store.put_bytes(b"payload")
    dest = tmp_path / "out" / "copy.bin"
    store.copy_to(digest, dest)
    assert dest.read_bytes() == b"payload"


def test_delete_removes_blob(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    digest = store.put_bytes(b"bye")
    assert store.delete(digest) is True
    assert store.exists(digest) is False
    assert store.delete(digest) is False


def test_iter_digests_lists_all(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    digests = {store.put_bytes(bytes([b])) for b in range(5)}
    assert set(store.iter_digests()) == digests


def test_put_missing_file_raises(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "cas")
    with pytest.raises(CASException):
        store.put(tmp_path / "nope.bin")
