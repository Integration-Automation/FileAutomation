"""Azure Blob delete operations."""

from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.azure_blob.client import azure_blob_instance


def azure_blob_delete_blob(container: str, blob_name: str) -> bool:
    """Delete a blob. Returns True on success."""
    service = azure_blob_instance.require_service()
    try:
        service.get_blob_client(container=container, blob=blob_name).delete_blob()
        file_automation_logger.info(
            "azure_blob_delete_blob: %s/%s",
            container,
            blob_name,
        )
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("azure_blob_delete_blob failed: %r", error)
        return False
