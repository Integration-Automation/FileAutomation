"""S3Storage against an S3-compatible service (S3Mock in CI).

Environment: ``FA_IT_S3_ENDPOINT`` (for example ``http://127.0.0.1:9000``),
``FA_IT_S3_ACCESS_KEY``, ``FA_IT_S3_SECRET_KEY`` and optionally ``FA_IT_S3_REGION``.
"""

# pylint: disable=arguments-differ  # a fixture or a stand-in takes other arguments than the one it replaces
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=ungrouped-imports  # imports follow pytest.importorskip

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.integration.service_env import optional_setting, service_setting, unique_name

ENDPOINT = service_setting("FA_IT_S3_ENDPOINT", "an S3 service")
boto3 = pytest.importorskip("boto3", reason="needs the s3 extra")

# pylint: disable=wrong-import-position  # the two guards above must come first
from automation_file.storage import S3Storage, StorageBackend  # noqa: E402
from tests.storage_contract import StorageContract  # noqa: E402


@pytest.fixture(scope="module")
def client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=service_setting("FA_IT_S3_ACCESS_KEY", "an S3 service"),
        aws_secret_access_key=service_setting("FA_IT_S3_SECRET_KEY", "an S3 service"),
        region_name=optional_setting("FA_IT_S3_REGION", "us-east-1"),
    )


def _empty_and_delete(client: Any, bucket: str) -> None:
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for entry in page.get("Contents", []):
            client.delete_object(Bucket=bucket, Key=entry["Key"])
    client.delete_bucket(Bucket=bucket)


class TestS3ServiceContract(StorageContract):
    @pytest.fixture
    def backend(self, client: Any) -> Iterator[StorageBackend]:
        bucket = unique_name()
        client.create_bucket(Bucket=bucket)
        yield S3Storage(bucket, client=client)
        _empty_and_delete(client, bucket)


class TestPrefixedS3ServiceContract(StorageContract):
    @pytest.fixture
    def backend(self, client: Any) -> Iterator[StorageBackend]:
        bucket = unique_name()
        client.create_bucket(Bucket=bucket)
        client.put_object(Bucket=bucket, Key="other-tenant/keep.txt", Body=b"keep")
        yield S3Storage(bucket, client=client, prefix="tenant/a")
        assert (
            client.get_object(Bucket=bucket, Key="other-tenant/keep.txt")["Body"].read() == b"keep"
        )
        _empty_and_delete(client, bucket)


def test_stat_reports_what_the_service_returns(client: Any) -> None:
    bucket = unique_name()
    client.create_bucket(Bucket=bucket)
    try:
        info = S3Storage(bucket, client=client).write_bytes("reports/q1.json", b"{}")
        assert info.size == 2
        assert info.etag
        assert info.content_type == "application/json"
        assert info.modified_at is not None
    finally:
        _empty_and_delete(client, bucket)
