"""Box backend tests.

Live Box endpoints are outside CI; these tests verify registry wiring,
the Client singleton's guard clauses, and the error-path wrapping that
converts ``box_sdk_gen`` failures into :class:`BoxException`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from box_sdk_gen.schemas.file_base import FileBaseTypeField

from automation_file import (
    BoxClient,
    BoxException,
    box_instance,
    build_default_registry,
    register_box_ops,
)
from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import FileNotExistsException
from automation_file.remote.box import delete_ops, download_ops, list_ops, upload_ops


class _FakeItem:
    def __init__(self, item_id: str, name: str, item_type: Any) -> None:
        self.id = item_id
        self.name = name
        self.type = item_type


class _Uploads:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes]] = []

    def upload_file(self, attributes: Any, file: Any) -> Any:
        self.calls.append((attributes.name, attributes.parent.id, file.read()))
        return SimpleNamespace(entries=[SimpleNamespace(id="new-id")])


class _Downloads:
    def download_file_to_output_stream(self, file_id: str, output_stream: Any) -> None:
        output_stream.write(f"contents of {file_id}".encode())


class _Folders:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, bool]] = []

    def get_folder_items(self, folder_id: str, *, limit: int | None = None) -> Any:
        del folder_id, limit
        return SimpleNamespace(
            entries=[
                _FakeItem("1", "a.txt", FileBaseTypeField.FILE),
                _FakeItem("2", "subdir", "folder"),
            ]
        )

    def delete_folder_by_id(self, folder_id: str, *, recursive: bool | None = None) -> None:
        self.deleted.append((folder_id, bool(recursive)))


class _Files:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_file_by_id(self, file_id: str) -> None:
        self.deleted.append(file_id)


class _FakeBoxClient:
    """Mirrors the managers of :class:`box_sdk_gen.BoxClient` that the backend calls."""

    def __init__(self) -> None:
        self.uploads = _Uploads()
        self.downloads = _Downloads()
        self.folders = _Folders()
        self.files = _Files()


@pytest.fixture(name="fake_box")
def _fake_box(monkeypatch: pytest.MonkeyPatch) -> _FakeBoxClient:
    fake = _FakeBoxClient()
    monkeypatch.setattr(box_instance, "client", fake, raising=False)
    return fake


def test_require_client_raises_when_not_initialised() -> None:
    client = BoxClient()
    with pytest.raises(BoxException):
        client.require_client()


def test_later_init_rejects_empty_token() -> None:
    client = BoxClient()
    with pytest.raises(BoxException):
        client.later_init("")


def test_default_registry_contains_box() -> None:
    registry = build_default_registry()
    for name in (
        "FA_box_upload_file",
        "FA_box_list_folder",
        "FA_box_delete_file",
        "FA_box_delete_folder",
    ):
        assert name in registry


def test_register_box_ops_adds_entries() -> None:
    registry = ActionRegistry()
    register_box_ops(registry)
    assert "FA_box_upload_file" in registry


def test_upload_file_rejects_missing_source(tmp_path: Path, fake_box: _FakeBoxClient) -> None:
    del fake_box
    with pytest.raises(FileNotExistsException):
        upload_ops.box_upload_file(str(tmp_path / "gone.txt"))


def test_upload_file_returns_id(tmp_path: Path, fake_box: _FakeBoxClient) -> None:
    del fake_box
    src = tmp_path / "report.txt"
    src.write_text("ok", encoding="utf-8")
    file_id = upload_ops.box_upload_file(str(src))
    assert file_id == "new-id"


def test_upload_dir_uploads_each_file(tmp_path: Path, fake_box: _FakeBoxClient) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    uploaded_keys = upload_ops.box_upload_dir(str(tmp_path))
    assert sorted(uploaded_keys) == ["a.txt", "sub/b.txt"]
    assert sorted((name, parent) for name, parent, _ in fake_box.uploads.calls) == [
        ("a.txt", "0"),
        ("sub/b.txt", "0"),
    ]


def test_download_writes_target(tmp_path: Path, fake_box: _FakeBoxClient) -> None:
    del fake_box
    target = tmp_path / "out" / "f.txt"
    assert download_ops.box_download_file("42", str(target)) is True
    assert target.read_bytes() == b"contents of 42"


def test_list_folder_returns_entries(fake_box: _FakeBoxClient) -> None:
    del fake_box
    entries = list_ops.box_list_folder()
    assert entries == [
        {"id": "1", "name": "a.txt", "type": "file"},
        {"id": "2", "name": "subdir", "type": "folder"},
    ]


def test_delete_file_uses_client(fake_box: _FakeBoxClient) -> None:
    assert delete_ops.box_delete_file("7") is True
    assert fake_box.files.deleted == ["7"]


def test_delete_folder_uses_client(fake_box: _FakeBoxClient) -> None:
    assert delete_ops.box_delete_folder("7", recursive=True) is True
    assert fake_box.folders.deleted == [("7", True)]


def test_errors_in_sdk_surface_as_box_exception(
    monkeypatch: pytest.MonkeyPatch, fake_box: _FakeBoxClient
) -> None:
    def blow(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated SDK error")

    monkeypatch.setattr(fake_box.folders, "get_folder_items", blow)
    with pytest.raises(BoxException):
        list_ops.box_list_folder()


def test_upload_file_sends_name_parent_and_content(
    tmp_path: Path, fake_box: _FakeBoxClient
) -> None:
    src = tmp_path / "report.txt"
    src.write_bytes(b"payload")
    upload_ops.box_upload_file(str(src), parent_folder_id="99", name="renamed.txt")
    assert fake_box.uploads.calls == [("renamed.txt", "99", b"payload")]


def test_later_init_builds_a_real_sdk_client() -> None:
    import box_sdk_gen

    client = BoxClient()
    built = client.later_init("token-value", client_id="id", client_secret="secret")
    assert isinstance(built, box_sdk_gen.BoxClient)
    assert client.require_client() is built
    assert hasattr(built, "uploads") and hasattr(built, "folders")
