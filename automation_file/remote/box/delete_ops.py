"""Box delete operations."""

from __future__ import annotations

from automation_file.exceptions import BoxException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.box.client import box_instance


def box_delete_file(file_id: str) -> bool:
    """Delete a Box file by id."""
    client = box_instance.require_client()
    try:
        client.file(file_id=file_id).delete()
    except Exception as error:  # pylint: disable=broad-except
        raise BoxException(f"box_delete_file failed: {error}") from error
    file_automation_logger.info("box_delete_file: %s", file_id)
    return True


def box_delete_folder(folder_id: str, recursive: bool = False) -> bool:
    """Delete a Box folder by id (optionally recursive)."""
    client = box_instance.require_client()
    try:
        client.folder(folder_id=folder_id).delete(recursive=recursive)
    except Exception as error:  # pylint: disable=broad-except
        raise BoxException(f"box_delete_folder failed: {error}") from error
    file_automation_logger.info("box_delete_folder: %s (recursive=%s)", folder_id, recursive)
    return True
