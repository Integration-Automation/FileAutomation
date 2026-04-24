"""Box backend tests.

Live Box endpoints are outside CI; these tests verify registry wiring,
the Client singleton's guard clauses, and the error-path wrapping that
converts ``boxsdk`` failures into :class:`BoxException`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

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
    def __init__(self, item_id: str, name: str, item_type: str = "file") -> None:
        self.id = item_id
        self.name = name
        self.type = item_type


class _FakeFile:
    def __init__(self, file_id: str) -> None:
        self.id = file_id

    def download_to(self, writer: Any) -> None:
        writer.write(b"contents")

    def delete(self) -> None:
        return None


class _FakeFolder:
    def __init__(self, folder_id: str) -> None:
        self.id = folder_id
        self._uploads: list[tuple[str, str]] = []

    def upload(self, file_path: str, file_name: str) -> _FakeFile:
        self._uploads.append((file_path, file_name))
        return _FakeFile("new-id")

    def get_items(self, limit: int = 100) -> list[_FakeItem]:
        del limit
        return [_FakeItem("1", "a.txt"), _FakeItem("2", "subdir", "folder")]

    def delete(self, recursive: bool = False) -> None:
        del recursive


class _FakeBoxClient:
    def __init__(self) -> None:
        self._files: dict[str, _FakeFile] = {}
        self._folders: dict[str, _FakeFolder] = {}

    def file(self, file_id: str) -> _FakeFile:
        self._files.setdefault(file_id, _FakeFile(file_id))
        return self._files[file_id]

    def folder(self, folder_id: str) -> _FakeFolder:
        self._folders.setdefault(folder_id, _FakeFolder(folder_id))
        return self._folders[folder_id]


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
    folder = fake_box.folder("0")
    flat_names = sorted(name for _, name in folder._uploads)  # pylint: disable=protected-access
    assert flat_names == ["a.txt", "sub/b.txt"]


def test_download_writes_target(tmp_path: Path, fake_box: _FakeBoxClient) -> None:
    del fake_box
    target = tmp_path / "out" / "f.txt"
    assert download_ops.box_download_file("42", str(target)) is True
    assert target.read_bytes() == b"contents"


def test_list_folder_returns_entries(fake_box: _FakeBoxClient) -> None:
    del fake_box
    entries = list_ops.box_list_folder()
    assert entries == [
        {"id": "1", "name": "a.txt", "type": "file"},
        {"id": "2", "name": "subdir", "type": "folder"},
    ]


def test_delete_file_uses_client(fake_box: _FakeBoxClient) -> None:
    del fake_box
    assert delete_ops.box_delete_file("7") is True


def test_delete_folder_uses_client(fake_box: _FakeBoxClient) -> None:
    del fake_box
    assert delete_ops.box_delete_folder("7", recursive=True) is True


def test_errors_in_sdk_surface_as_box_exception(
    monkeypatch: pytest.MonkeyPatch, fake_box: _FakeBoxClient
) -> None:
    def blow(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated SDK error")

    monkeypatch.setattr(fake_box, "folder", blow)
    with pytest.raises(BoxException):
        list_ops.box_list_folder()
