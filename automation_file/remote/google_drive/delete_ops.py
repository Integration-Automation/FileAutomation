"""Delete-side Google Drive operations."""
from __future__ import annotations

from typing import Any

from googleapiclient.errors import HttpError

from automation_file.logging_config import file_automation_logger
from automation_file.remote.google_drive.client import driver_instance


def drive_delete_file(file_id: str) -> Any | None:
    """Delete a file by Drive ID. Returns the API response or None."""
    try:
        result = driver_instance.require_service().files().delete(fileId=file_id).execute()
        file_automation_logger.info("drive_delete_file: %s", file_id)
        return result
    except HttpError as error:
        file_automation_logger.error("drive_delete_file failed: %r", error)
        return None
