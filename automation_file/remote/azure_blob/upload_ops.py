"""Azure Blob upload operations."""

from __future__ import annotations

from pathlib import Path

from automation_file.exceptions import DirNotExistsException, FileNotExistsException
from automation_file.logging_config import file_automation_logger
from automation_file.remote._upload_tree import walk_and_upload
from automation_file.remote.azure_blob.client import azure_blob_instance


def azure_blob_upload_file(
    file_path: str,
    container: str,
    blob_name: str,
    overwrite: bool = True,
) -> bool:
    """Upload a single file to ``container/blob_name``."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotExistsException(str(path))
    service = azure_blob_instance.require_service()
    try:
        blob = service.get_blob_client(container=container, blob=blob_name)
        with open(path, "rb") as fp:
            blob.upload_blob(fp, overwrite=overwrite)
        file_automation_logger.info(
            "azure_blob_upload_file: %s -> %s/%s",
            path,
            container,
            blob_name,
        )
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("azure_blob_upload_file failed: %r", error)
        return False


def azure_blob_upload_dir(
    dir_path: str,
    container: str,
    name_prefix: str = "",
) -> list[str]:
    """Upload every file under ``dir_path`` to ``container`` under ``name_prefix``."""
    source = Path(dir_path)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    prefix = name_prefix.rstrip("/")
    uploaded = walk_and_upload(
        source,
        lambda rel: f"{prefix}/{rel}" if prefix else rel,
        lambda local, blob_name: azure_blob_upload_file(str(local), container, blob_name),
    )
    file_automation_logger.info(
        "azure_blob_upload_dir: %s -> %s/%s (%d files)",
        source,
        container,
        prefix,
        len(uploaded),
    )
    return uploaded
