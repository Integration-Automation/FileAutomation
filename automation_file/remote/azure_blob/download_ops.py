"""Azure Blob download operations."""
from __future__ import annotations

from pathlib import Path

from automation_file.logging_config import file_automation_logger
from automation_file.remote.azure_blob.client import azure_blob_instance


def azure_blob_download_file(container: str, blob_name: str, target_path: str) -> bool:
    """Download a blob to ``target_path``."""
    service = azure_blob_instance.require_service()
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        blob = service.get_blob_client(container=container, blob=blob_name)
        with open(target_path, "wb") as fp:
            fp.write(blob.download_blob().readall())
        file_automation_logger.info(
            "azure_blob_download_file: %s/%s -> %s", container, blob_name, target_path,
        )
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("azure_blob_download_file failed: %r", error)
        return False
