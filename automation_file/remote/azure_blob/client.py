"""Azure Blob Storage client (Singleton Facade)."""

from __future__ import annotations

from typing import Any

from automation_file.logging_config import file_automation_logger


def _import_blob_service_client() -> Any:
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as error:
        raise RuntimeError(
            "azure-storage-blob import failed — reinstall `automation_file` to restore"
            " the Azure Blob backend"
        ) from error
    return BlobServiceClient


class AzureBlobClient:
    """Lazy wrapper around :class:`azure.storage.blob.BlobServiceClient`."""

    def __init__(self) -> None:
        self.service: Any = None

    def later_init(
        self,
        connection_string: str | None = None,
        account_url: str | None = None,
        credential: Any = None,
    ) -> Any:
        """Build a BlobServiceClient. Prefer ``connection_string`` when set."""
        service_cls = _import_blob_service_client()
        if connection_string:
            self.service = service_cls.from_connection_string(connection_string)
        elif account_url:
            self.service = service_cls(account_url=account_url, credential=credential)
        else:
            raise ValueError("provide connection_string or account_url")
        file_automation_logger.info("AzureBlobClient: service ready")
        return self.service

    def require_service(self) -> Any:
        if self.service is None:
            raise RuntimeError("AzureBlobClient not initialised; call later_init() first")
        return self.service


azure_blob_instance: AzureBlobClient = AzureBlobClient()
