"""LocalStorage: the storage contract plus what is specific to a filesystem."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from automation_file.exceptions import (
    PathTraversalException,
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageUnsupportedException,
)
from automation_file.storage import LocalStorage, StorageBackend
from tests.storage_contract import StorageContract


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links cannot be created here")


def _rootless(path: Path) -> str:
    """Return ``path`` the way a rootless LocalStorage addresses it."""
    return path.resolve().as_posix().lstrip("/")


class TestRootedLocalStorageContract(StorageContract):
    @pytest.fixture
    def backend(self, tmp_path: Path) -> StorageBackend:
        root = tmp_path / "storage-root"
        root.mkdir()
        return LocalStorage(root)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    directory = tmp_path / "root"
    directory.mkdir()
    return directory


@pytest.fixture
def storage(root: Path) -> LocalStorage:
    return LocalStorage(root)


def test_files_land_under_the_root(storage: LocalStorage, root: Path) -> None:
    storage.write_bytes("a/b.txt", b"x")
    assert (root / "a" / "b.txt").read_bytes() == b"x"
    assert storage.root == root.resolve()
    assert storage.local_path("a/b.txt") == (root / "a" / "b.txt").resolve()


def test_uri_for_is_the_absolute_local_uri(storage: LocalStorage, root: Path) -> None:
    expected = "local:///" + (root.resolve() / "a" / "b.txt").as_posix().lstrip("/")
    assert storage.uri_for("a/b.txt") == expected


def test_rootless_storage_addresses_absolute_paths(tmp_path: Path) -> None:
    (tmp_path / "abs.txt").write_bytes(b"absolute")
    storage = LocalStorage()
    path = _rootless(tmp_path / "abs.txt")
    assert storage.root is None
    assert storage.read_bytes(path) == b"absolute"
    assert storage.local_path(path) == (tmp_path / "abs.txt").resolve()
    assert storage.uri_for(path) == f"local:///{path}"


def test_rootless_storage_refuses_to_delete_a_filesystem_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the root guard let a delete through")

    # The guard is what is under test; nothing may reach the filesystem if it fails.
    monkeypatch.setattr(LocalStorage, "_delete_directory", _must_not_run)
    monkeypatch.setattr(shutil, "rmtree", _must_not_run)
    anchor = Path(os.path.abspath(os.sep)).as_posix().strip("/")
    with pytest.raises(StorageUnsupportedException):
        LocalStorage().delete(anchor, recursive=True)


def test_a_link_out_of_the_root_is_a_path_traversal(storage: LocalStorage, root: Path) -> None:
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    _symlink(root / "escape", outside, directory=True)
    with pytest.raises(PathTraversalException):
        storage.read_bytes("escape/secret.txt")
    with pytest.raises(PathTraversalException):
        storage.write_bytes("escape/planted.txt", b"x")
    assert not (outside / "planted.txt").exists()


def test_deleting_a_linked_directory_leaves_its_target_alone(
    storage: LocalStorage, root: Path
) -> None:
    (root / "real").mkdir()
    (root / "real" / "keep.txt").write_bytes(b"keep")
    _symlink(root / "link", root / "real", directory=True)
    storage.delete("link", recursive=True)
    assert not (root / "link").exists()
    assert (root / "real" / "keep.txt").read_bytes() == b"keep"


def test_deleting_a_linked_file_leaves_its_target_alone(storage: LocalStorage, root: Path) -> None:
    (root / "real.txt").write_bytes(b"keep")
    _symlink(root / "link.txt", root / "real.txt")
    storage.delete("link.txt")
    assert not (root / "link.txt").is_symlink()
    assert (root / "real.txt").read_bytes() == b"keep"


def test_a_dangling_link_is_listed_and_can_be_deleted(storage: LocalStorage, root: Path) -> None:
    _symlink(root / "dangling", root / "gone.txt")
    assert [info.path for info in storage.list_dir()] == ["dangling"]
    assert storage.exists("dangling") is True
    storage.delete("dangling")
    assert storage.list_dir() == []


def test_recursive_listing_does_not_descend_into_linked_directories(
    storage: LocalStorage, root: Path
) -> None:
    (root / "real").mkdir()
    (root / "real" / "a.txt").write_bytes(b"x")
    _symlink(root / "real" / "loop", root, directory=True)
    assert [info.path for info in storage.list_dir(recursive=True)] == [
        "real",
        "real/a.txt",
        "real/loop",
    ]


@pytest.mark.skipif(os.sep != "\\", reason="backslash is a separator only on Windows")
def test_backslashes_are_separators_on_windows(storage: LocalStorage) -> None:
    storage.write_bytes("dir\\a.txt", b"x")
    assert storage.stat("dir/a.txt").path == "dir/a.txt"
    assert storage.stat("dir\\a.txt").path == "dir/a.txt"


def test_copy_between_two_local_roots(tmp_path: Path) -> None:
    source = LocalStorage(tmp_path)
    (tmp_path / "target").mkdir()
    target = LocalStorage(tmp_path / "target")
    source.write_bytes("a.txt", b"payload")
    info = target.copy_from(source, "a.txt", "nested/b.txt")
    assert info.path == "nested/b.txt"
    assert (tmp_path / "target" / "nested" / "b.txt").read_bytes() == b"payload"
    assert (tmp_path / "a.txt").read_bytes() == b"payload"


def test_move_between_two_local_roots(tmp_path: Path) -> None:
    source = LocalStorage(tmp_path)
    (tmp_path / "target").mkdir()
    target = LocalStorage(tmp_path / "target")
    source.write_bytes("a.txt", b"payload")
    target.move_from(source, "a.txt", "b.txt")
    assert (tmp_path / "target" / "b.txt").read_bytes() == b"payload"
    assert not (tmp_path / "a.txt").exists()


def test_upload_leaves_no_partial_file_behind(storage: LocalStorage, root: Path) -> None:
    storage.write_bytes("a.txt", b"x")
    assert [entry.name for entry in root.iterdir()] == ["a.txt"]


def test_a_failed_upload_keeps_the_previous_content(
    storage: LocalStorage, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.write_bytes("a.txt", b"previous")

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copyfile", _fail)
    with pytest.raises(StorageException, match="disk full"):
        storage.write_bytes("a.txt", b"next")
    assert [entry.name for entry in root.iterdir()] == ["a.txt"]
    assert (root / "a.txt").read_bytes() == b"previous"


def test_a_denied_operation_raises_the_permission_error(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.write_bytes("a.txt", b"x")

    def _deny(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(shutil, "copyfile", _deny)
    with pytest.raises(StoragePermissionException):
        storage.write_bytes("b.txt", b"y")
    assert storage.exists("b.txt") is False


def test_a_root_that_does_not_exist_reports_not_found(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "never-created")
    assert storage.exists("") is False
    with pytest.raises(StorageNotFoundException):
        storage.list_dir()
