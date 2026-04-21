"""Azure Blob Storage strategy module (optional; requires ``azure-storage-blob``)."""
from __future__ import annotations

from automation_file.core.action_registry import ActionRegistry
from automation_file.remote.azure_blob import delete_ops, download_ops, list_ops, upload_ops
from automation_file.remote.azure_blob.client import AzureBlobClient, azure_blob_instance


def register_azure_blob_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_azure_blob_*`` command into ``registry``."""
    registry.register_many(
        {
            "FA_azure_blob_later_init": azure_blob_instance.later_init,
            "FA_azure_blob_upload_file": upload_ops.azure_blob_upload_file,
            "FA_azure_blob_upload_dir": upload_ops.azure_blob_upload_dir,
            "FA_azure_blob_download_file": download_ops.azure_blob_download_file,
            "FA_azure_blob_delete_blob": delete_ops.azure_blob_delete_blob,
            "FA_azure_blob_list_container": list_ops.azure_blob_list_container,
        }
    )


__all__ = ["AzureBlobClient", "azure_blob_instance", "register_azure_blob_ops"]
