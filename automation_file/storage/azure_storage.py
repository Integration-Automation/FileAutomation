"""Azure Blob backend: ``azure://<container>/<blob>`` (alias ``az://``).

``AzureStorage("backups")`` serves one container through the shared
:data:`~automation_file.remote.azure_blob.client.azure_blob_instance`, which the
caller initialises as before (``azure_blob_instance.later_init(...)`` or
``FA_azure_blob_later_init``). Pass ``service=`` to use another
``BlobServiceClient``, for another account or the Azurite emulator.

Uploads set the blob's content type from its name. ``stat`` reports the size,
modification time, ETag, content type, version ID and metadata of the blob.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.storage.backend import guess_content_type, missing_error
from automation_file.storage.object_storage import ObjectStorage
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import StorageURI

AZURE_SCHEME = "azure"
_DENIED_STATUS = frozenset({401, 403})
_MISSING_STATUS = frozenset({404})
_TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_NOT_INSTALLED = "azure-storage-blob is not installed; the Azure Blob backend needs it"


@contextlib.contextmanager
def _azure_errors(location: str) -> Iterator[None]:
    """Turn azure-core errors into the storage layer's exceptions."""
    try:
        from azure.core import exceptions as azure_errors
    except ImportError as error:
        raise StorageUnavailableException(_NOT_INSTALLED) from error
    try:
        yield
    except azure_errors.ResourceNotFoundError as error:
        raise missing_error(location) from error
    except azure_errors.ClientAuthenticationError as error:
        raise StoragePermissionException(f"access to {location} was denied") from error
    except azure_errors.HttpResponseError as error:
        status = getattr(error, "status_code", None)
        if status in _MISSING_STATUS:
            raise missing_error(location) from error
        if status in _DENIED_STATUS:
            raise StoragePermissionException(
                f"access to {location} was denied ({status})"
            ) from error
        if status in _TRANSIENT_STATUS:
            raise StorageTransientException(f"{location}: Azure answered {status}") from error
        raise StorageException(f"{location}: Azure error {status or 'unknown'}") from error
    except (azure_errors.ServiceRequestError, azure_errors.ServiceResponseError) as error:
        raise StorageTransientException(f"{location}: {type(error).__name__}") from error
    except azure_errors.AzureError as error:
        raise StorageException(f"{location}: {type(error).__name__}") from error


def _blob_info(properties: Any) -> FileInfo:
    settings = getattr(properties, "content_settings", None)
    etag = getattr(properties, "etag", None)
    return FileInfo(
        path=properties.name,
        size=int(getattr(properties, "size", 0) or 0),
        modified_at=getattr(properties, "last_modified", None),
        etag=str(etag).strip('"') if etag else None,
        version=getattr(properties, "version_id", None),
        content_type=getattr(settings, "content_type", None),
        metadata=dict(getattr(properties, "metadata", None) or {}),
    )


class AzureStorage(ObjectStorage):
    """One Azure Blob container, or the blobs below one prefix of it."""

    scheme = AZURE_SCHEME
    capabilities = StorageCapabilities(
        directories=False,
        modified_at=True,
        etag=True,
        version=True,
        content_type=True,
        metadata=True,
    )

    def __init__(self, container: str, *, service: Any = None, prefix: str = "") -> None:
        if not container:
            raise StorageURIException("an Azure Blob storage needs a container name")
        super().__init__(prefix)
        self._container = container
        self._explicit_service = service

    @property
    def container(self) -> str:
        return self._container

    @property
    def _service(self) -> Any:
        if self._explicit_service is not None:
            return self._explicit_service
        from automation_file.remote.azure_blob.client import azure_blob_instance

        try:
            return azure_blob_instance.require_service()
        except RuntimeError as error:
            raise StorageUnavailableException(
                "the Azure Blob client is not initialised; call azure_blob_instance.later_init() "
                "or pass service= to AzureStorage"
            ) from error

    def uri_for(self, path: str = "") -> str:
        key = self._key(self._normalize(path))
        return str(StorageURI(AZURE_SCHEME, self._container, key))

    def _location(self, key: str) -> str:
        return f"{AZURE_SCHEME}://{self._container}/{key}"

    def _blob(self, key: str) -> Any:
        return self._service.get_blob_client(container=self._container, blob=key)

    def _head(self, key: str) -> FileInfo | None:
        try:
            with _azure_errors(self._location(key)):
                properties = self._blob(key).get_blob_properties()
        except StorageNotFoundException:
            return None
        return _blob_info(properties)

    def _scan(self, key_prefix: str, *, shallow: bool) -> Iterable[FileInfo]:
        found: list[FileInfo] = []
        with _azure_errors(self._location(key_prefix)):
            container = self._service.get_container_client(self._container)
            starts_with = key_prefix or None
            if not shallow:
                return [
                    _blob_info(item) for item in container.list_blobs(name_starts_with=starts_with)
                ]
            for item in container.walk_blobs(name_starts_with=starts_with, delimiter="/"):
                # A deeper level arrives as a prefix whose name ends with the delimiter.
                if item.name.endswith("/") and item.name != key_prefix:
                    found.append(FileInfo(path=item.name.rstrip("/"), is_dir=True))
                else:
                    found.append(_blob_info(item))
        return found

    def _put(self, source: Path, key: str) -> None:
        try:
            from azure.storage.blob import ContentSettings
        except ImportError as error:
            raise StorageUnavailableException(_NOT_INSTALLED) from error
        content_type = guess_content_type(key)
        settings = ContentSettings(content_type=content_type) if content_type else None
        with _azure_errors(self._location(key)), open(source, "rb") as handle:
            self._blob(key).upload_blob(handle, overwrite=True, content_settings=settings)

    def _get(self, key: str, target: Path) -> None:
        with _azure_errors(self._location(key)), open(target, "wb") as handle:
            self._blob(key).download_blob().readinto(handle)

    def _remove(self, key: str) -> None:
        with _azure_errors(self._location(key)):
            self._blob(key).delete_blob()

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, AzureStorage)
            and other._container == self._container
            and other._prefix == self._prefix
            and other._explicit_service is self._explicit_service
        )

    def __hash__(self) -> int:
        return hash((AZURE_SCHEME, self._container, self._prefix, id(self._explicit_service)))

    def __repr__(self) -> str:
        return f"AzureStorage({self._container!r}, prefix={self._prefix!r})"
