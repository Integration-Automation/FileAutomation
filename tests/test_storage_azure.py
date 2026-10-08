"""AzureStorage: the storage contract against an in-memory stand-in for BlobServiceClient.

The stand-in answers the calls the adapter makes -- ``get_blob_client`` (with
``get_blob_properties``, ``upload_blob``, ``download_blob().readinto`` and
``delete_blob``) and ``get_container_client`` (with ``list_blobs`` and
``walk_blobs``) -- and raises the real ``azure.core`` exceptions. No request
leaves the process.
"""

# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=raising-bad-type  # a stand-in raises what the test hands it
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=unidiomatic-typecheck  # the exact class is what is asserted
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, BinaryIO

import pytest

pytest.importorskip("azure.storage.blob", reason="needs the azure extra")

# pylint: disable=wrong-import-position  # importorskip must precede these imports
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from azure.storage.blob import (
    BlobClient,
    BlobProperties,
    BlobServiceClient,
    ContainerClient,
    ContentSettings,
    StorageStreamDownloader,
)

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.remote.azure_blob.client import azure_blob_instance
from automation_file.storage import (
    AzureStorage,
    File,
    StorageBackend,
    StorageResolver,
)
from tests.storage_contract import StorageContract


def _http_error(status: int) -> HttpResponseError:
    error = HttpResponseError(message=f"status {status}")
    error.status_code = status
    return error


@dataclass
class _Blob:
    data: bytes
    content_type: str | None
    modified: datetime

    def properties(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(
            name=name,
            size=len(self.data),
            last_modified=self.modified,
            etag=f'"0x{hashlib.md5(self.data, usedforsecurity=False).hexdigest()[:16].upper()}"',  # nosec B324  # nosemgrep  # the digest under test, not a security use
            content_settings=SimpleNamespace(content_type=self.content_type),
            metadata={},
            version_id=None,
        )


class _Download:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def readinto(self, stream: BinaryIO) -> int:
        return stream.write(self._data)


class _BlobClient:
    def __init__(self, service: FakeBlobService, container: str, name: str) -> None:
        self._service = service
        self._container = container
        self._name = name

    def _existing(self) -> _Blob:
        blobs = self._service.blobs(self._container)
        if self._name not in blobs:
            raise ResourceNotFoundError("The specified blob does not exist.")
        return blobs[self._name]

    def get_blob_properties(self) -> SimpleNamespace:
        return self._existing().properties(self._name)

    def upload_blob(
        self, data: BinaryIO, overwrite: bool = False, content_settings: Any = None
    ) -> None:
        blobs = self._service.blobs(self._container)
        if self._name in blobs and not overwrite:
            raise ResourceExistsError("The specified blob already exists.")
        content_type = getattr(content_settings, "content_type", None)
        blobs[self._name] = _Blob(data.read(), content_type, datetime.now(timezone.utc))

    def download_blob(self) -> _Download:
        return _Download(self._existing().data)

    def delete_blob(self) -> None:
        self._existing()
        del self._service.blobs(self._container)[self._name]


class _ContainerClient:
    def __init__(self, service: FakeBlobService, container: str) -> None:
        self._service = service
        self._container = container

    def list_blobs(self, name_starts_with: str | None = None):
        blobs = self._service.blobs(self._container)
        prefix = name_starts_with or ""
        for name in sorted(blobs):
            if name.startswith(prefix):
                yield blobs[name].properties(name)

    def walk_blobs(self, name_starts_with: str | None = None, delimiter: str = "/"):
        blobs = self._service.blobs(self._container)
        prefix = name_starts_with or ""
        seen: set[str] = set()
        for name in sorted(blobs):
            if not name.startswith(prefix):
                continue
            rest = name[len(prefix) :]
            if delimiter in rest:
                deeper = prefix + rest.split(delimiter, 1)[0] + delimiter
                if deeper not in seen:
                    seen.add(deeper)
                    yield SimpleNamespace(name=deeper, prefix=deeper)
                continue
            yield blobs[name].properties(name)


class FakeBlobService:
    """The subset of BlobServiceClient that AzureStorage calls."""

    def __init__(self, *containers: str) -> None:
        self.containers: dict[str, dict[str, _Blob]] = {
            name: {} for name in containers or ("container",)
        }
        self.fail_with: Exception | None = None
        self.fail_times: int | None = None  # None: every call while fail_with is set

    def blobs(self, container: str) -> dict[str, _Blob]:
        if self.fail_with is not None and self.fail_times != 0:
            if self.fail_times is not None:
                self.fail_times -= 1
            raise self.fail_with
        if container not in self.containers:
            raise ResourceNotFoundError("The specified container does not exist.")
        return self.containers[container]

    def get_blob_client(self, container: str, blob: str) -> _BlobClient:
        return _BlobClient(self, container, blob)

    def get_container_client(self, container: str) -> _ContainerClient:
        return _ContainerClient(self, container)


_FAILURES = {
    "denied": lambda: _http_error(403),
    "transient": lambda: _http_error(503),
}


class TestAzureStorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return AzureStorage("container", service=FakeBlobService())

    @pytest.fixture
    def break_storage(self, backend: StorageBackend) -> Callable[..., None]:
        assert isinstance(backend, AzureStorage)
        service = backend._service

        def fail(kind: str, times: int = 1) -> None:
            service.fail_with = _FAILURES[kind]()
            service.fail_times = times

        return fail


class TestPrefixedAzureStorageContract(TestAzureStorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        service = FakeBlobService()
        service.containers["container"]["other-tenant/keep.txt"] = _Blob(
            b"keep", "text/plain", datetime.now(timezone.utc)
        )
        return AzureStorage("container", service=service, prefix="tenant/a")


@pytest.fixture
def service() -> FakeBlobService:
    return FakeBlobService("container", "archive")


@pytest.fixture
def storage(service: FakeBlobService) -> AzureStorage:
    return AzureStorage("container", service=service)


def test_stat_reports_the_blob_properties(storage: AzureStorage) -> None:
    info = storage.write_bytes("reports/q1.json", b"{}")
    assert info.path == "reports/q1.json"
    assert info.size == 2
    assert info.etag is not None
    assert not info.etag.startswith('"')
    assert info.content_type == "application/json"
    assert info.version is None
    assert dict(info.metadata) == {}
    assert info.modified_at is not None


def test_a_blob_without_a_known_suffix_has_no_content_type(storage: AzureStorage) -> None:
    assert storage.write_bytes("blob", b"x").content_type is None


def test_a_prefix_confines_the_backend_to_its_blobs(service: FakeBlobService) -> None:
    service.containers["container"]["other/keep.txt"] = _Blob(
        b"k", None, datetime.now(timezone.utc)
    )
    tenant = AzureStorage("container", service=service, prefix="tenant/a")
    tenant.write_bytes("docs/a.txt", b"x")
    assert sorted(service.containers["container"]) == ["other/keep.txt", "tenant/a/docs/a.txt"]
    assert [info.path for info in tenant.list_dir("", recursive=True)] == ["docs", "docs/a.txt"]
    assert tenant.uri_for("docs/a.txt") == "azure://container/tenant/a/docs/a.txt"
    tenant.delete("docs", recursive=True)
    assert sorted(service.containers["container"]) == ["other/keep.txt"]


def test_a_folder_placeholder_is_a_directory_not_a_file(
    storage: AzureStorage, service: FakeBlobService
) -> None:
    service.containers["container"]["folder/"] = _Blob(b"", None, datetime.now(timezone.utc))
    assert storage.stat("folder").is_dir is True
    assert storage.list_dir("folder") == []
    assert [(info.path, info.is_dir) for info in storage.list_dir()] == [("folder", True)]
    storage.delete("folder")
    assert service.containers["container"] == {}


def test_copy_between_containers(storage: AzureStorage, service: FakeBlobService) -> None:
    storage.write_bytes("a.txt", b"payload")
    AzureStorage("archive", service=service).copy_from(storage, "a.txt", "2026/a.txt")
    assert service.containers["archive"]["2026/a.txt"].data == b"payload"
    assert service.containers["archive"]["2026/a.txt"].content_type == "text/plain"


@pytest.mark.parametrize(
    "error,expected",
    [
        (ClientAuthenticationError("bad key"), StoragePermissionException),
        (_http_error(403), StoragePermissionException),
        (_http_error(429), StorageTransientException),
        (_http_error(503), StorageTransientException),
        (_http_error(400), StorageException),
        (ServiceRequestError("connection refused"), StorageTransientException),
    ],
)
def test_sdk_errors_become_storage_errors(
    storage: AzureStorage, service: FakeBlobService, error: Exception, expected: type[Exception]
) -> None:
    service.fail_with = error
    with pytest.raises(expected) as caught:
        storage.stat("a.txt")
    assert caught.value.__cause__ is error
    assert type(caught.value) is expected


def test_a_missing_container_is_not_found(service: FakeBlobService) -> None:
    missing = AzureStorage("no-such-container", service=service)
    assert missing.exists("a.txt") is False
    with pytest.raises(StorageNotFoundException):
        missing.list_dir()


def test_a_container_name_is_required() -> None:
    with pytest.raises(StorageURIException):
        AzureStorage("")


def test_equality_and_repr(service: FakeBlobService) -> None:
    first, second = (
        AzureStorage("container", service=service),
        AzureStorage("container", service=service),
    )
    assert first == second
    assert AzureStorage("container", service=service) != AzureStorage("archive", service=service)
    assert AzureStorage("container", service=service) != AzureStorage(
        "container", service=FakeBlobService()
    )
    assert (
        repr(AzureStorage("container", service=service, prefix="a"))
        == "AzureStorage('container', prefix='a')"
    )
    assert AzureStorage("container", service=service).container == "container"
    assert AzureStorage("container", service=service).uri_for("") == "azure://container"


def test_the_shared_client_must_be_initialised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(azure_blob_instance, "service", None)
    with pytest.raises(StorageUnavailableException, match="later_init"):
        AzureStorage("container").exists("a.txt")


def test_azure_uris_use_the_shared_client(
    monkeypatch: pytest.MonkeyPatch, service: FakeBlobService, tmp_path: Path
) -> None:
    monkeypatch.setattr(azure_blob_instance, "service", service)
    resolver = StorageResolver()
    report = File("azure://container/reports/q1.csv", resolver=resolver)
    report.write(b"a,b\n")
    assert service.containers["container"]["reports/q1.csv"].data == b"a,b\n"
    assert File("az://container/reports/q1.csv", resolver=resolver).read() == b"a,b\n"
    assert resolver.resolve("az://container/reports/q1.csv") == (
        AzureStorage("container"),
        "reports/q1.csv",
    )
    report.move_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    assert service.containers["container"] == {}


def test_an_azure_uri_needs_a_container() -> None:
    with pytest.raises(StorageURIException, match="container"):
        StorageResolver().resolve("azure:///blob-without-container")


# ---------------------------------------------------------------------- the real azure SDK


def test_the_sdk_has_the_calls_the_adapter_makes() -> None:
    """The stand-in above is only as good as its match with azure-storage-blob."""
    blob_client = inspect.signature(BlobServiceClient.get_blob_client).parameters
    assert {"container", "blob"} <= set(blob_client)
    assert "container" in inspect.signature(BlobServiceClient.get_container_client).parameters
    assert "name_starts_with" in inspect.signature(ContainerClient.list_blobs).parameters
    assert {"name_starts_with", "delimiter"} <= set(
        inspect.signature(ContainerClient.walk_blobs).parameters
    )
    # overwrite= and content_settings= travel through **kwargs.
    assert "kwargs" in inspect.signature(BlobClient.upload_blob).parameters
    for method in ("get_blob_properties", "download_blob", "delete_blob"):
        assert callable(getattr(BlobClient, method))
    assert list(inspect.signature(StorageStreamDownloader.readinto).parameters) == [
        "self",
        "stream",
    ]
    properties = BlobProperties()
    for attribute in ("name", "size", "last_modified", "etag", "content_settings", "metadata"):
        assert hasattr(properties, attribute)
    assert hasattr(properties, "version_id")
    assert ContentSettings(content_type="text/plain").content_type == "text/plain"


def test_two_prefixes_of_one_container_do_not_lose_a_blob_to_itself(
    service: FakeBlobService,
) -> None:
    whole = AzureStorage("container", service=service)
    tenant = AzureStorage("container", service=service, prefix="tenant/a")
    tenant.write_bytes("docs/a.txt", b"payload")
    for operation in (whole.move_from, whole.copy_from):
        with pytest.raises(StorageException, match="same file"):
            operation(tenant, "docs/a.txt", "tenant/a/docs/a.txt")
    with pytest.raises(StorageException, match="same file"):
        tenant.move_from(whole, "tenant/a/docs/a.txt", "docs/a.txt")
    assert service.containers["container"]["tenant/a/docs/a.txt"].data == b"payload"
    elsewhere = AzureStorage("container", service=FakeBlobService())
    elsewhere.copy_from(tenant, "docs/a.txt", "tenant/a/docs/a.txt")
    assert elsewhere.read_bytes("tenant/a/docs/a.txt") == b"payload"
