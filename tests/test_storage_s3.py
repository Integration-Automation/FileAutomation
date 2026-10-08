"""S3Storage: the storage contract against an in-memory stand-in for the boto3 client.

The stand-in answers the calls the adapter makes -- ``head_object``, the
``list_objects_v2`` paginator, ``upload_file``, ``download_file``,
``delete_object`` and ``copy`` -- with the shapes boto3 documents, and raises the
real ``botocore`` exceptions. No request leaves the process.
"""

# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=raising-bad-type  # a stand-in raises what the test hands it
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=too-many-locals  # one scenario told in order
# pylint: disable=unidiomatic-typecheck  # the exact class is what is asserted
# pylint: disable=unused-argument  # a fixture is requested for its effect; a stand-in keeps the real signature
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

boto3 = pytest.importorskip("boto3", reason="needs the s3 extra")

# pylint: disable=wrong-import-position  # importorskip must precede these imports
from botocore import UNSIGNED  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore.exceptions import (  # noqa: E402
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)
from botocore.stub import Stubber  # noqa: E402

from automation_file.exceptions import (  # noqa: E402
    StorageException,
    StorageNotFoundException,
    StoragePermissionException,
    StorageTransientException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.remote.s3.client import s3_instance  # noqa: E402
from automation_file.storage import File, S3Storage, StorageBackend, StorageResolver  # noqa: E402
from tests.storage_contract import StorageContract  # noqa: E402

PAGE_SIZE = 2


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


@dataclass
class _Object:
    data: bytes
    content_type: str
    modified: datetime

    @property
    def etag(self) -> str:
        return f'"{hashlib.md5(self.data, usedforsecurity=False).hexdigest()}"'  # nosec B324  # nosemgrep  # the digest under test, not a security use


class _Paginator:
    def __init__(self, client: FakeS3Client) -> None:
        self._client = client

    def paginate(self, **arguments: Any):
        prefix: str = arguments.get("Prefix", "")
        delimiter: str | None = arguments.get("Delimiter")
        objects = self._client.objects(arguments["Bucket"], "ListObjectsV2")
        contents: list[dict[str, Any]] = []
        prefixes: list[str] = []
        for key in sorted(objects):
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix) :]
            if delimiter and delimiter in rest:
                common = prefix + rest.split(delimiter, 1)[0] + delimiter
                if common not in prefixes:
                    prefixes.append(common)
                continue
            item = objects[key]
            contents.append(
                {
                    "Key": key,
                    "Size": len(item.data),
                    "LastModified": item.modified,
                    "ETag": item.etag,
                }
            )
        entries: list[tuple[str, Any]] = [("CommonPrefixes", {"Prefix": p}) for p in prefixes]
        entries += [("Contents", item) for item in contents]
        if not entries:
            yield {"KeyCount": 0}
        for start in range(0, len(entries), PAGE_SIZE):
            page: dict[str, Any] = {"KeyCount": 0}
            for kind, value in entries[start : start + PAGE_SIZE]:
                page.setdefault(kind, []).append(value)
                page["KeyCount"] += 1
            yield page


class FakeS3Client:
    """The subset of the boto3 S3 client that S3Storage calls."""

    def __init__(self, *buckets: str) -> None:
        self.buckets: dict[str, dict[str, _Object]] = {name: {} for name in buckets or ("bucket",)}
        self.calls: list[str] = []
        self.fail_with: Exception | None = None
        self.fail_times: int | None = None  # None: every call while fail_with is set

    def objects(self, bucket: str, operation: str) -> dict[str, _Object]:
        self.calls.append(operation)
        if self.fail_with is not None and self.fail_times != 0:
            if self.fail_times is not None:
                self.fail_times -= 1
            raise self.fail_with
        if bucket not in self.buckets:
            raise _client_error("NoSuchBucket", operation)
        return self.buckets[bucket]

    def head_object(self, **arguments: Any) -> dict[str, Any]:
        objects = self.objects(arguments["Bucket"], "HeadObject")
        if arguments["Key"] not in objects:
            raise _client_error("404", "HeadObject")
        item = objects[arguments["Key"]]
        return {
            "ContentLength": len(item.data),
            "LastModified": item.modified,
            "ETag": item.etag,
            "ContentType": item.content_type,
            "Metadata": {},
        }

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        return _Paginator(self)

    def upload_file(self, filename: str, bucket: str, key: str, **options: Any) -> None:
        extra = options.get("ExtraArgs") or {}
        self.objects(bucket, "PutObject")[key] = _Object(
            Path(filename).read_bytes(),
            extra.get("ContentType", "binary/octet-stream"),
            datetime.now(timezone.utc),
        )

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        objects = self.objects(bucket, "GetObject")
        if key not in objects:
            raise _client_error("404", "GetObject")
        Path(filename).write_bytes(objects[key].data)

    def delete_object(self, **arguments: Any) -> None:
        self.objects(arguments["Bucket"], "DeleteObject").pop(arguments["Key"], None)

    def copy(self, copy_source: dict[str, str], bucket: str, key: str) -> None:
        source = self.objects(copy_source["Bucket"], "CopyObject")
        if copy_source["Key"] not in source:
            raise _client_error("NoSuchKey", "CopyObject")
        item = source[copy_source["Key"]]
        self.buckets[bucket][key] = _Object(
            item.data, item.content_type, datetime.now(timezone.utc)
        )


_FAILURES = {
    "denied": lambda: _client_error("AccessDenied", "HeadObject"),
    "transient": lambda: _client_error("SlowDown", "HeadObject"),
}


def _breaker(client: FakeS3Client) -> Callable[..., None]:
    def fail(kind: str, times: int = 1) -> None:
        client.fail_with = _FAILURES[kind]()
        client.fail_times = times

    return fail


class TestS3StorageContract(StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        return S3Storage("bucket", client=FakeS3Client())

    @pytest.fixture
    def break_storage(self, backend: StorageBackend) -> Callable[..., None]:
        assert isinstance(backend, S3Storage)
        return _breaker(backend._client)


class TestPrefixedS3StorageContract(TestS3StorageContract):
    @pytest.fixture
    def backend(self) -> StorageBackend:
        client = FakeS3Client()
        client.buckets["bucket"]["other-tenant/keep.txt"] = _Object(
            b"keep", "text/plain", datetime.now(timezone.utc)
        )
        return S3Storage("bucket", client=client, prefix="tenant/a")


@pytest.fixture
def client() -> FakeS3Client:
    return FakeS3Client("bucket", "archive")


@pytest.fixture
def storage(client: FakeS3Client) -> S3Storage:
    return S3Storage("bucket", client=client)


def test_stat_reports_what_head_object_returns(storage: S3Storage) -> None:
    info = storage.write_bytes("reports/q1.json", b"{}")
    assert info.path == "reports/q1.json"
    assert info.size == 2
    assert info.etag == hashlib.md5(b"{}", usedforsecurity=False).hexdigest()  # nosec B324  # nosemgrep  # the digest under test, not a security use
    assert info.content_type == "application/json"
    assert info.version is None
    assert dict(info.metadata) == {}
    assert info.modified_at is not None


def test_a_key_without_a_known_suffix_keeps_the_default_content_type(storage: S3Storage) -> None:
    assert storage.write_bytes("blob", b"x").content_type == "binary/octet-stream"


def test_listing_reads_every_page(storage: S3Storage, client: FakeS3Client) -> None:
    for index in range(7):
        storage.write_bytes(f"dir/{index}.txt", b"x")
    listing = storage.list_dir("dir")
    assert [info.path for info in listing] == [f"dir/{index}.txt" for index in range(7)]
    assert all(info.etag for info in listing)
    assert len(storage.list_dir("", recursive=True)) == 8


def test_a_prefix_confines_the_backend_to_its_keys(client: FakeS3Client) -> None:
    client.buckets["bucket"]["other/keep.txt"] = _Object(
        b"k", "text/plain", datetime.now(timezone.utc)
    )
    tenant = S3Storage("bucket", client=client, prefix="/tenant//a/")
    assert tenant.prefix == "tenant/a"
    tenant.write_bytes("docs/a.txt", b"x")
    assert sorted(client.buckets["bucket"]) == ["other/keep.txt", "tenant/a/docs/a.txt"]
    assert [info.path for info in tenant.list_dir("", recursive=True)] == ["docs", "docs/a.txt"]
    assert tenant.uri_for("docs/a.txt") == "s3://bucket/tenant/a/docs/a.txt"
    tenant.delete("docs", recursive=True)
    assert sorted(client.buckets["bucket"]) == ["other/keep.txt"]


def test_a_folder_placeholder_is_a_directory_not_a_file(
    storage: S3Storage, client: FakeS3Client
) -> None:
    client.buckets["bucket"]["folder/"] = _Object(
        b"", "application/x-directory", datetime.now(timezone.utc)
    )
    assert storage.stat("folder").is_dir is True
    assert storage.list_dir("folder") == []
    assert [(info.path, info.is_dir) for info in storage.list_dir()] == [("folder", True)]
    assert [(info.path, info.is_dir) for info in storage.list_dir("", recursive=True)] == [
        ("folder", True)
    ]
    storage.delete("folder")
    assert client.buckets["bucket"] == {}
    assert storage.exists("folder") is False


def test_copy_within_s3_is_server_side(storage: S3Storage, client: FakeS3Client) -> None:
    storage.write_bytes("a.txt", b"payload")
    client.calls.clear()
    storage.copy_from(storage, "a.txt", "copies/b.txt")
    assert "CopyObject" in client.calls
    assert "GetObject" not in client.calls
    archive = S3Storage("archive", client=client)
    archive.copy_from(storage, "a.txt", "a.txt")
    assert client.buckets["archive"]["a.txt"].data == b"payload"


def test_copy_between_two_clients_goes_through_a_staging_file(storage: S3Storage) -> None:
    other_client = FakeS3Client("bucket")
    other = S3Storage("bucket", client=other_client)
    storage.write_bytes("a.txt", b"payload")
    other.copy_from(storage, "a.txt", "a.txt")
    assert other_client.buckets["bucket"]["a.txt"].data == b"payload"
    assert "CopyObject" not in other_client.calls


@pytest.mark.parametrize(
    "error,expected",
    [
        (_client_error("AccessDenied", "HeadObject"), StoragePermissionException),
        (_client_error("403", "HeadObject"), StoragePermissionException),
        (_client_error("SlowDown", "HeadObject"), StorageTransientException),
        (_client_error("503", "HeadObject"), StorageTransientException),
        (_client_error("InvalidBucketName", "HeadObject"), StorageException),
        (EndpointConnectionError(endpoint_url="https://s3.invalid"), StorageTransientException),
        (NoCredentialsError(), StorageException),
    ],
)
def test_sdk_errors_become_storage_errors(
    storage: S3Storage, client: FakeS3Client, error: Exception, expected: type[Exception]
) -> None:
    client.fail_with = error
    with pytest.raises(expected) as caught:
        storage.stat("a.txt")
    assert caught.value.__cause__ is error
    assert type(caught.value) is expected


def test_a_missing_bucket_is_not_found(client: FakeS3Client) -> None:
    missing = S3Storage("no-such-bucket", client=client)
    assert missing.exists("a.txt") is False
    with pytest.raises(StorageNotFoundException):
        missing.list_dir()


def test_a_bucket_name_is_required() -> None:
    with pytest.raises(StorageURIException):
        S3Storage("")


def test_equality_and_repr(client: FakeS3Client) -> None:
    first, second = S3Storage("bucket", client=client), S3Storage("bucket", client=client)
    assert first == second
    assert S3Storage("bucket", client=client) != S3Storage("archive", client=client)
    assert S3Storage("bucket", client=client) != S3Storage("bucket", client=client, prefix="a")
    assert S3Storage("bucket", client=client) != S3Storage("bucket", client=FakeS3Client())
    assert len({S3Storage("bucket", client=client), S3Storage("bucket", client=client)}) == 1
    assert repr(S3Storage("bucket", client=client, prefix="a")) == "S3Storage('bucket', prefix='a')"
    assert S3Storage("bucket", client=client).bucket == "bucket"
    assert S3Storage("bucket", client=client).uri_for("") == "s3://bucket"


def test_the_shared_client_must_be_initialised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3_instance, "client", None)
    with pytest.raises(StorageUnavailableException, match="later_init"):
        S3Storage("bucket").exists("a.txt")


def test_s3_uris_use_the_shared_client(
    monkeypatch: pytest.MonkeyPatch, client: FakeS3Client, tmp_path: Path
) -> None:
    monkeypatch.setattr(s3_instance, "client", client)
    resolver = StorageResolver()
    report = File("s3://bucket/reports/q1.csv", resolver=resolver)
    report.write(b"a,b\n")
    assert client.buckets["bucket"]["reports/q1.csv"].data == b"a,b\n"
    assert resolver.resolve("s3://bucket/reports/q1.csv") == (S3Storage("bucket"), "reports/q1.csv")
    report.copy_to(tmp_path / "q1.csv")
    assert (tmp_path / "q1.csv").read_bytes() == b"a,b\n"
    File(tmp_path / "q1.csv", resolver=resolver).copy_to("s3://archive/2026/q1.csv")
    assert client.buckets["archive"]["2026/q1.csv"].data == b"a,b\n"
    with pytest.raises(StorageException):
        report.copy_to("s3://bucket//reports/q1.csv/")


def test_an_s3_uri_needs_a_bucket() -> None:
    with pytest.raises(StorageURIException, match="bucket"):
        StorageResolver().resolve("s3:///key-without-bucket")


# ---------------------------------------------------------------------- the real boto3 client


@pytest.fixture
def real_client() -> Any:
    """A real boto3 S3 client that signs nothing; the Stubber answers for the network."""
    return boto3.client("s3", region_name="us-east-1", config=Config(signature_version=UNSIGNED))


def test_requests_and_responses_fit_the_service_model(real_client: Any) -> None:
    """Stubber checks every request against botocore's model of S3, parameter by parameter."""
    storage = S3Storage("bucket", client=real_client)
    modified = datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)
    listing = {
        "KeyCount": 2,
        "IsTruncated": False,
        "CommonPrefixes": [{"Prefix": "dir/sub/"}],
        "Contents": [{"Key": "dir/a.txt", "Size": 3, "LastModified": modified, "ETag": '"abc"'}],
    }
    shallow = {"Bucket": "bucket", "Prefix": "dir/", "Delimiter": "/"}
    with Stubber(real_client) as stub:
        stub.add_response(
            "head_object",
            {
                "ContentLength": 3,
                "LastModified": modified,
                "ETag": '"abc"',
                "ContentType": "text/plain",
                "VersionId": "v1",
                "Metadata": {"owner": "ops"},
            },
            {"Bucket": "bucket", "Key": "dir/a.txt"},
        )
        info = storage.stat("dir/a.txt")
        assert (info.size, info.modified_at, info.etag) == (3, modified, "abc")
        assert (info.content_type, info.version, dict(info.metadata)) == (
            "text/plain",
            "v1",
            {"owner": "ops"},
        )

        stub.add_client_error(
            "head_object",
            service_error_code="404",
            http_status_code=404,
            expected_params={"Bucket": "bucket", "Key": "dir"},
        )
        stub.add_response("list_objects_v2", listing, shallow)
        stub.add_response("list_objects_v2", listing, shallow)
        assert [(entry.path, entry.is_dir, entry.size) for entry in storage.list_dir("dir")] == [
            ("dir/a.txt", False, 3),
            ("dir/sub", True, None),
        ]

        stub.add_response(
            "head_object", {"ContentLength": 3}, {"Bucket": "bucket", "Key": "dir/a.txt"}
        )
        stub.add_response("delete_object", {}, {"Bucket": "bucket", "Key": "dir/a.txt"})
        storage.delete("dir/a.txt")

        stub.add_client_error(
            "head_object", service_error_code="AccessDenied", http_status_code=403
        )
        with pytest.raises(StoragePermissionException):
            storage.stat("secret.txt")
        stub.assert_no_pending_responses()


def test_the_transfer_calls_exist_with_the_arguments_the_adapter_passes(real_client: Any) -> None:
    upload = inspect.signature(real_client.upload_file).parameters
    assert list(upload)[:4] == ["Filename", "Bucket", "Key", "ExtraArgs"]
    assert list(inspect.signature(real_client.download_file).parameters)[:3] == [
        "Bucket",
        "Key",
        "Filename",
    ]
    assert list(inspect.signature(real_client.copy).parameters)[:3] == [
        "CopySource",
        "Bucket",
        "Key",
    ]
    assert real_client.can_paginate("list_objects_v2") is True


def test_two_prefixes_of_one_bucket_do_not_lose_a_file_to_itself(client: FakeS3Client) -> None:
    whole = S3Storage("bucket", client=client)
    tenant = S3Storage("bucket", client=client, prefix="tenant/a")
    tenant.write_bytes("docs/a.txt", b"payload")
    for operation in (whole.move_from, whole.copy_from):
        with pytest.raises(StorageException, match="same file"):
            operation(tenant, "docs/a.txt", "tenant/a/docs/a.txt")
    with pytest.raises(StorageException, match="same file"):
        tenant.move_from(whole, "tenant/a/docs/a.txt", "docs/a.txt")
    assert client.buckets["bucket"]["tenant/a/docs/a.txt"].data == b"payload"
    # Another client's bucket of the same name is another store.
    elsewhere = S3Storage("bucket", client=FakeS3Client())
    elsewhere.copy_from(tenant, "docs/a.txt", "tenant/a/docs/a.txt")
    assert elsewhere.read_bytes("tenant/a/docs/a.txt") == b"payload"
