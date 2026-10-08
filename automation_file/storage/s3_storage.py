"""S3 backend: ``s3://<bucket>/<key>``.

``S3Storage("reports")`` serves one bucket through the shared
:data:`~automation_file.remote.s3.client.s3_instance`, which the caller
initialises as before (``s3_instance.later_init(...)`` or ``FA_s3_later_init``).
Pass ``client=`` to use another boto3 S3 client, for another account or an
S3-compatible endpoint such as MinIO.

Uploads set ``ContentType`` from the key's suffix. ``stat`` reports the size,
modification time, ETag, content type, version ID and user metadata that
``HeadObject`` returns. Checksums are computed from the content: an S3 ETag is
not a digest of a multipart upload, so it is never used as one.
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
from automation_file.storage.backend import (
    StorageBackend,
    guess_content_type,
    missing_error,
)
from automation_file.storage.object_storage import ObjectStorage
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import StorageURI

S3_SCHEME = "s3"
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NoSuchBucket", "NotFound"})
_DENIED_CODES = frozenset(
    {"403", "AccessDenied", "Forbidden", "InvalidAccessKeyId", "SignatureDoesNotMatch"}
)
_TRANSIENT_CODES = frozenset(
    {
        "500",
        "502",
        "503",
        "504",
        "InternalError",
        "RequestTimeout",
        "ServiceUnavailable",
        "SlowDown",
        "Throttling",
        "ThrottlingException",
    }
)


def _error_code(error: Any) -> str:
    response = getattr(error, "response", None) or {}
    return str(response.get("Error", {}).get("Code", ""))


@contextlib.contextmanager
def _s3_errors(location: str) -> Iterator[None]:
    """Turn boto3 and botocore errors into the storage layer's exceptions."""
    try:
        from boto3.exceptions import Boto3Error
        from botocore import exceptions as botocore_errors
    except ImportError as error:
        raise StorageUnavailableException(
            "boto3 is not installed; the S3 backend needs it"
        ) from error
    try:
        yield
    except botocore_errors.ClientError as error:
        code = _error_code(error)
        if code in _MISSING_CODES:
            raise missing_error(location) from error
        if code in _DENIED_CODES:
            raise StoragePermissionException(f"access to {location} was denied ({code})") from error
        if code in _TRANSIENT_CODES:
            raise StorageTransientException(f"{location}: S3 answered {code}") from error
        raise StorageException(f"{location}: S3 error {code or 'unknown'}") from error
    except (botocore_errors.ConnectionError, botocore_errors.HTTPClientError) as error:
        raise StorageTransientException(f"{location}: {type(error).__name__}") from error
    except (botocore_errors.BotoCoreError, Boto3Error) as error:
        raise StorageException(f"{location}: {type(error).__name__}") from error


def _etag(raw: Any) -> str | None:
    return str(raw).strip('"') if raw else None


def _listed(entry: dict[str, Any]) -> FileInfo:
    return FileInfo(
        path=entry["Key"],
        size=int(entry.get("Size", 0)),
        modified_at=entry.get("LastModified"),
        etag=_etag(entry.get("ETag")),
    )


class S3Storage(ObjectStorage):
    """One S3 bucket, or the keys below one prefix of it."""

    scheme = S3_SCHEME
    capabilities = StorageCapabilities(
        directories=False,
        modified_at=True,
        etag=True,
        version=True,
        content_type=True,
        metadata=True,
    )

    def __init__(self, bucket: str, *, client: Any = None, prefix: str = "") -> None:
        if not bucket:
            raise StorageURIException("an S3 storage needs a bucket name")
        super().__init__(prefix)
        self._bucket = bucket
        self._explicit_client = client

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def _client(self) -> Any:
        if self._explicit_client is not None:
            return self._explicit_client
        from automation_file.remote.s3.client import s3_instance

        try:
            return s3_instance.require_client()
        except RuntimeError as error:
            raise StorageUnavailableException(
                "the S3 client is not initialised; call s3_instance.later_init() "
                "or pass client= to S3Storage"
            ) from error

    def uri_for(self, path: str = "") -> str:
        key = self._key(self._normalize(path))
        return str(StorageURI(S3_SCHEME, self._bucket, key))

    def _head(self, key: str) -> FileInfo | None:
        try:
            with _s3_errors(f"{S3_SCHEME}://{self._bucket}/{key}"):
                head = self._client.head_object(Bucket=self._bucket, Key=key)
        except StorageNotFoundException:
            return None
        return FileInfo(
            path=key,
            size=int(head.get("ContentLength", 0)),
            modified_at=head.get("LastModified"),
            etag=_etag(head.get("ETag")),
            version=head.get("VersionId"),
            content_type=head.get("ContentType"),
            metadata=dict(head.get("Metadata") or {}),
        )

    def _scan(self, key_prefix: str, *, shallow: bool) -> Iterable[FileInfo]:
        arguments = {"Bucket": self._bucket, "Prefix": key_prefix}
        if shallow:
            arguments["Delimiter"] = "/"
        found: list[FileInfo] = []
        with _s3_errors(f"{S3_SCHEME}://{self._bucket}/{key_prefix}"):
            for page in self._client.get_paginator("list_objects_v2").paginate(**arguments):
                found.extend(
                    FileInfo(path=item["Prefix"].rstrip("/"), is_dir=True)
                    for item in page.get("CommonPrefixes", [])
                )
                found.extend(_listed(entry) for entry in page.get("Contents", []))
        return found

    def _put(self, source: Path, key: str) -> None:
        content_type = guess_content_type(key)
        extra = {"ContentType": content_type} if content_type else None
        with _s3_errors(f"{S3_SCHEME}://{self._bucket}/{key}"):
            self._client.upload_file(str(source), self._bucket, key, ExtraArgs=extra)

    def _get(self, key: str, target: Path) -> None:
        with _s3_errors(f"{S3_SCHEME}://{self._bucket}/{key}"):
            self._client.download_file(self._bucket, key, str(target))

    def _remove(self, key: str) -> None:
        with _s3_errors(f"{S3_SCHEME}://{self._bucket}/{key}"):
            self._client.delete_object(Bucket=self._bucket, Key=key)

    def _copy_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, S3Storage) or source._client is not self._client:
            return False
        origin = {"Bucket": source.bucket, "Key": source._key(source_path)}
        with _s3_errors(self.uri_for(path)):
            self._client.copy(origin, self._bucket, self._key(path))
        return True

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, S3Storage)
            and other._bucket == self._bucket
            and other._prefix == self._prefix
            and other._explicit_client is self._explicit_client
        )

    def __hash__(self) -> int:
        return hash((S3_SCHEME, self._bucket, self._prefix, id(self._explicit_client)))

    def __repr__(self) -> str:
        return f"S3Storage({self._bucket!r}, prefix={self._prefix!r})"
