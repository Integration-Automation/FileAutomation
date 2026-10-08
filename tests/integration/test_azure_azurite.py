"""AzureStorage against Azure Blob or its emulator (Azurite in CI).

Environment: ``FA_IT_AZURE_CONNECTION_STRING``.
"""

# pylint: disable=arguments-differ  # a fixture or a stand-in takes other arguments than the one it replaces
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=ungrouped-imports  # imports follow pytest.importorskip

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.integration.service_env import service_setting, unique_name

CONNECTION_STRING = service_setting("FA_IT_AZURE_CONNECTION_STRING", "a Blob service")
blob = pytest.importorskip("azure.storage.blob", reason="needs the azure extra")

# pylint: disable=wrong-import-position  # the two guards above must come first
from automation_file.storage import AzureStorage, StorageBackend  # noqa: E402
from tests.storage_contract import StorageContract  # noqa: E402


@pytest.fixture(scope="module")
def service() -> Any:
    return blob.BlobServiceClient.from_connection_string(CONNECTION_STRING)


class TestAzureServiceContract(StorageContract):
    @pytest.fixture
    def backend(self, service: Any) -> Iterator[StorageBackend]:
        container = unique_name()
        service.create_container(container)
        yield AzureStorage(container, service=service)
        service.delete_container(container)


class TestPrefixedAzureServiceContract(StorageContract):
    @pytest.fixture
    def backend(self, service: Any) -> Iterator[StorageBackend]:
        container = unique_name()
        service.create_container(container)
        keep = service.get_blob_client(container=container, blob="other-tenant/keep.txt")
        keep.upload_blob(b"keep")
        yield AzureStorage(container, service=service, prefix="tenant/a")
        assert keep.download_blob().readall() == b"keep"
        service.delete_container(container)


def test_stat_reports_what_the_service_returns(service: Any) -> None:
    container = unique_name()
    service.create_container(container)
    try:
        info = AzureStorage(container, service=service).write_bytes("reports/q1.json", b"{}")
        assert info.size == 2
        assert info.etag
        assert info.content_type == "application/json"
        assert info.modified_at is not None
    finally:
        service.delete_container(container)
