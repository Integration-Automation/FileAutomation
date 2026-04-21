"""Azure Blob listing operations."""
from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.azure_blob.client import azure_blob_instance


def azure_blob_list_container(container: str, name_prefix: str = "") -> list[str]:
    """Return every blob name under ``container``/``name_prefix``."""
    service = azure_blob_instance.require_service()
    names: list[str] = []
    try:
        container_client = service.get_container_client(container)
        iterator = container_client.list_blobs(name_starts_with=name_prefix or None)
        names = [blob.name for blob in iterator]
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("azure_blob_list_container failed: %r", error)
        return []
    file_automation_logger.info(
        "azure_blob_list_container: %s/%s (%d blobs)", container, name_prefix, len(names),
    )
    return names
