"""The Files and Storage services of the application layer, on private resolvers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from automation_file.app import (
    AppException,
    BackendStatus,
    FileService,
    StorageService,
)
from automation_file.app import storage_service as storage_module
from automation_file.core.optional import install_hint
from automation_file.exceptions import (
    PathTraversalException,
    StorageNotEmptyException,
    StorageNotFoundException,
    StorageURIException,
)
from automation_file.storage import (
    File,
    FileInfo,
    LocalStorage,
    MemoryStorage,
    StorageBackend,
    StorageResolver,
)

ROOT = "memory://files"


class _Remote(StorageBackend):
    """A backend that is neither local nor in-memory to the service: files are fetched whole."""

    scheme = "remote"

    def __init__(self) -> None:
        self._inner = MemoryStorage()

    def _stat(self, path: str) -> FileInfo | None:
        return self._inner._stat(path)

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        return self._inner._list_dir(path)

    def _upload(self, source: Path, path: str) -> None:
        self._inner._upload(source, path)

    def _download(self, path: str, target: Path) -> None:
        self._inner._download(path, target)

    def _delete_file(self, path: str) -> None:
        self._inner._delete_file(path)

    def _mkdir(self, path: str) -> None:
        self._inner._mkdir(path)

    def _rmdir(self, path: str) -> None:
        self._inner._rmdir(path)


@pytest.fixture(name="resolver")
def _resolver() -> StorageResolver:
    resolver = StorageResolver(defaults=False)
    resolver.mount(ROOT, MemoryStorage())
    resolver.mount("remote://far", _Remote())
    return resolver


@pytest.fixture(name="files")
def _files(resolver: StorageResolver) -> FileService:
    return FileService(resolver)


def _write(resolver: StorageResolver, uri: str, data: bytes | str) -> None:
    File(uri, resolver=resolver).write(data)


# ---------------------------------------------------------------------- files


def test_listing_puts_directories_first_and_carries_the_uri(
    files: FileService, resolver: StorageResolver
) -> None:
    _write(resolver, f"{ROOT}/b.txt", "bb")
    _write(resolver, f"{ROOT}/A.txt", "a")
    files.mkdir(f"{ROOT}/zeta")
    entries = files.list_dir(ROOT)
    assert [(entry.name, entry.is_dir) for entry in entries] == [
        ("zeta", True),
        ("A.txt", False),
        ("b.txt", False),
    ]
    assert entries[1].uri == f"{ROOT}/A.txt"
    assert entries[2].size == 2
    assert entries[1].modified_at is not None
    assert entries[0].to_dict()["is_dir"] is True


def test_a_recursive_listing_reports_paths_below_the_directory(
    files: FileService, resolver: StorageResolver
) -> None:
    _write(resolver, f"{ROOT}/dir/inner/a.txt", "a")
    paths = [entry.path for entry in files.list_dir(ROOT, recursive=True)]
    assert paths == ["dir", "dir/inner", "dir/inner/a.txt"]
    assert files.list_dir(f"{ROOT}/dir", recursive=True)[-1].uri == f"{ROOT}/dir/inner/a.txt"


def test_stat_exists_and_the_uri_helpers(files: FileService, resolver: StorageResolver) -> None:
    _write(resolver, f"{ROOT}/dir/a.txt", "hello")
    entry = files.stat(f"{ROOT}/dir/a.txt")
    assert (entry.name, entry.size, entry.is_dir) == ("a.txt", 5, False)
    assert files.exists(f"{ROOT}/dir") is True
    assert files.exists(f"{ROOT}/missing") is False
    assert files.parent(f"{ROOT}/dir/a.txt") == f"{ROOT}/dir"
    assert files.parent(ROOT) == ROOT
    assert files.child(f"{ROOT}/dir", "b.txt") == f"{ROOT}/dir/b.txt"
    assert files.normalize("MEMORY://files//dir/./a.txt") == f"{ROOT}/dir/a.txt"
    with pytest.raises(StorageNotFoundException):
        files.stat(f"{ROOT}/missing")


def test_a_path_cannot_climb_out_and_a_uri_cannot_carry_credentials(files: FileService) -> None:
    with pytest.raises(StorageURIException):
        files.list_dir(f"{ROOT}/../other")
    with pytest.raises(StorageURIException):
        files.child(ROOT, "../x")
    with pytest.raises(StorageURIException) as caught:
        files.stat("memory://user:hunter2@files/a.txt")
    assert "hunter2" not in str(caught.value)


def test_a_preview_is_bounded(files: FileService, resolver: StorageResolver) -> None:
    _write(resolver, f"{ROOT}/big.txt", "x" * 500)
    preview = files.preview(f"{ROOT}/big.txt", max_bytes=100)
    assert (preview.shown, preview.truncated, preview.binary) == (100, True, False)
    assert preview.text == "x" * 100
    assert preview.size == 500
    whole = files.preview(f"{ROOT}/big.txt")
    assert (whole.shown, whole.truncated) == (500, False)
    assert whole.to_dict()["uri"] == f"{ROOT}/big.txt"


def test_a_preview_cut_inside_a_character_is_still_text(
    files: FileService, resolver: StorageResolver
) -> None:
    _write(resolver, f"{ROOT}/utf8.txt", "é" * 10)
    preview = files.preview(f"{ROOT}/utf8.txt", max_bytes=5)
    assert preview.binary is False
    assert preview.text == "éé"


def test_binary_content_is_shown_as_hexadecimal(
    files: FileService, resolver: StorageResolver
) -> None:
    _write(resolver, f"{ROOT}/blob.bin", bytes(range(256)) * 4)
    preview = files.preview(f"{ROOT}/blob.bin")
    assert preview.binary is True
    assert preview.text.startswith("00 01 02 03")
    assert (preview.shown, preview.truncated) == (256, True)
    assert "hexadecimal" in preview.note


def test_a_large_remote_file_is_not_fetched_for_a_preview(resolver: StorageResolver) -> None:
    files = FileService(resolver, preview_bytes=10, fetch_limit=100)
    _write(resolver, "remote://far/huge.txt", "y" * 101)
    _write(resolver, "remote://far/small.txt", "z" * 50)
    _write(resolver, f"{ROOT}/huge.txt", "y" * 101)
    refused = files.preview("remote://far/huge.txt")
    assert (refused.text, refused.shown, refused.truncated) == ("", 0, True)
    assert "not fetched" in refused.note
    assert files.preview("remote://far/small.txt").text == "z" * 10
    assert files.preview(f"{ROOT}/huge.txt").text == "y" * 10


def test_a_directory_has_no_preview_and_the_limits_must_be_positive(
    files: FileService, resolver: StorageResolver
) -> None:
    files.mkdir(f"{ROOT}/dir")
    with pytest.raises(AppException, match="is a directory"):
        files.preview(f"{ROOT}/dir")
    with pytest.raises(AppException, match="at least one byte"):
        files.preview(f"{ROOT}/dir", max_bytes=0)
    with pytest.raises(AppException):
        FileService(resolver, preview_bytes=0)


def test_copy_to_a_file_to_a_directory_and_of_a_tree(
    files: FileService, resolver: StorageResolver
) -> None:
    _write(resolver, f"{ROOT}/src/a.txt", "a")
    _write(resolver, f"{ROOT}/src/sub/b.txt", "b")
    assert files.copy(f"{ROOT}/src/a.txt", f"{ROOT}/copy.txt").uri == f"{ROOT}/copy.txt"
    files.mkdir(f"{ROOT}/inbox")
    assert files.copy(f"{ROOT}/src/a.txt", f"{ROOT}/inbox").uri == f"{ROOT}/inbox/a.txt"
    tree = files.copy(f"{ROOT}/src", "remote://far/mirror")
    assert tree.is_dir is True
    assert File("remote://far/mirror/sub/b.txt", resolver=resolver).read_text() == "b"
    assert files.exists(f"{ROOT}/src/a.txt") is True


def test_move_a_file_and_refuse_a_directory(files: FileService, resolver: StorageResolver) -> None:
    _write(resolver, f"{ROOT}/a.txt", "a")
    files.mkdir(f"{ROOT}/done")
    moved = files.move(f"{ROOT}/a.txt", f"{ROOT}/done")
    assert moved.uri == f"{ROOT}/done/a.txt"
    assert files.exists(f"{ROOT}/a.txt") is False
    with pytest.raises(AppException, match="copy it and delete the original"):
        files.move(f"{ROOT}/done", f"{ROOT}/elsewhere")


def test_delete_needs_recursive_for_a_directory_with_entries(
    files: FileService, resolver: StorageResolver
) -> None:
    _write(resolver, f"{ROOT}/dir/a.txt", "a")
    with pytest.raises(StorageNotEmptyException):
        files.delete(f"{ROOT}/dir")
    assert files.delete(f"{ROOT}/dir", recursive=True) is True
    assert files.exists(f"{ROOT}/dir") is False
    with pytest.raises(StorageNotFoundException):
        files.delete(f"{ROOT}/dir")


def test_a_mounted_local_directory_cannot_be_left(tmp_path: Path) -> None:
    resolver = StorageResolver(defaults=False)
    inside = tmp_path / "inside"
    inside.mkdir()
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    (inside / "a.txt").write_text("in", encoding="utf-8")
    StorageService(resolver).mount_local("sandbox://jobs", inside)
    files = FileService(resolver)
    assert files.preview("sandbox://jobs/a.txt").text == "in"
    with pytest.raises(StorageURIException):
        files.preview("sandbox://jobs/../secret.txt")
    assert [entry.name for entry in files.list_dir("sandbox://jobs")] == ["a.txt"]


# ---------------------------------------------------------------------- storage


def test_schemes_and_mounts_of_a_resolver(resolver: StorageResolver) -> None:
    storage = StorageService(resolver)
    assert storage.resolver is resolver
    assert storage.schemes() == ["memory", "remote"]
    assert [mount.to_dict() for mount in storage.mounts()] == [
        {"uri": "memory://files", "scheme": "memory", "backend": "MemoryStorage"},
        {"uri": "remote://far", "scheme": "remote", "backend": "_Remote"},
    ]
    assert storage.capabilities(ROOT) == {
        "directories": True,
        "modified_at": True,
        "etag": False,
        "version": False,
        "content_type": False,
        "metadata": False,
    }


def test_mounting_and_unmounting(tmp_path: Path) -> None:
    storage = StorageService(StorageResolver(defaults=False))
    mount = storage.mount_local("sandbox://jobs/in", tmp_path)
    assert (mount.uri, mount.backend) == ("sandbox://jobs/in", "LocalStorage")
    assert storage.mount("memory://scratch", MemoryStorage()).scheme == "memory"
    assert [status.name for status in storage.backends() if status.kind == "mount"] == [
        "memory://scratch",
        "sandbox://jobs/in",
    ]
    assert storage.unmount("sandbox://jobs/in") is True
    assert storage.unmount("sandbox://jobs/in") is False
    with pytest.raises(AppException, match="not a directory"):
        storage.mount_local("sandbox://jobs", tmp_path / "missing")
    with pytest.raises(AppException, match="not a StorageBackend"):
        storage.mount("memory://bad", object())  # type: ignore[arg-type]


def test_a_local_mount_is_confined_to_its_directory(tmp_path: Path) -> None:
    resolver = StorageResolver(defaults=False)
    StorageService(resolver).mount_local("sandbox://jobs", tmp_path)
    backend, _path = resolver.resolve("sandbox://jobs/a.txt")
    assert isinstance(backend, LocalStorage)
    with pytest.raises((PathTraversalException, StorageURIException)):
        backend.stat("../outside.txt")


def _status(statuses: list[BackendStatus], name: str) -> BackendStatus:
    return next(status for status in statuses if status.name == name)


def test_the_default_resolver_lists_every_built_in_scheme_and_the_box_client() -> None:
    statuses = StorageService().backends()
    names = [status.name for status in statuses]
    for scheme in ("local", "memory", "s3", "azure", "gdrive", "dropbox", "onedrive", "sftp"):
        assert scheme in names
    assert {"ftp", "ftps", "box"} <= set(names)
    local = _status(statuses, "local")
    assert (local.kind, local.usable, local.detail, local.install_hint) == (
        "scheme",
        True,
        "ready",
        None,
    )
    assert _status(statuses, "memory").usable is True
    box = _status(statuses, "box")
    assert (box.kind, box.extra) == ("client", "box")


def test_an_uninitialised_client_says_how_to_initialise_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_module, "is_installed", lambda _module: True)
    s3 = _status(StorageService().backends(), "s3")
    assert (s3.installed, s3.ready, s3.usable) == (True, False, False)
    assert s3.install_hint is None
    assert "not initialised" in s3.detail
    assert "s3_instance.later_init" in s3.detail
    assert s3.label == "Amazon S3"


def test_a_missing_extra_is_reported_with_its_install_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_module, "is_installed", lambda module: module is None)
    statuses = StorageService().backends()
    s3 = _status(statuses, "s3")
    assert (s3.installed, s3.usable) == (False, False)
    assert s3.install_hint == install_hint("s3")
    assert install_hint("s3") in s3.detail
    assert "boto3 is not installed" in s3.detail
    ftp = _status(statuses, "ftp")
    assert (ftp.installed, ftp.install_hint) == (True, None)
    assert _status(statuses, "local").usable is True
    assert s3.to_dict()["install_hint"] == 'pip install "automation_file[s3]"'


def test_a_client_that_is_ready_makes_its_scheme_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    from automation_file.remote.s3.client import s3_instance

    monkeypatch.setattr(s3_instance, "client", object())
    s3 = _status(StorageService().backends(), "s3")
    assert (s3.ready, s3.usable, s3.detail) == (True, True, "ready")


def test_is_installed_does_not_import_and_tolerates_a_missing_parent() -> None:
    assert storage_module.is_installed(None) is True
    assert storage_module.is_installed("json") is True
    assert storage_module.is_installed("no_such_package_for_fa.sub.module") is False
    assert storage_module.is_installed("no_such_package_for_fa") is False


def test_a_scheme_registered_by_the_application_is_listed_as_such() -> None:
    resolver = StorageResolver(defaults=False)
    store = MemoryStorage()
    resolver.register_scheme("vault", lambda uri: (store, uri.path))
    statuses = StorageService(resolver).backends()
    vault = _status(statuses, "vault")
    assert (vault.kind, vault.usable) == ("scheme", True)
    assert "application" in vault.detail
