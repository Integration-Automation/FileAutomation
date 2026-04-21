"""Folder (mkdir-equivalent) operations on Google Drive."""
from __future__ import annotations

from googleapiclient.errors import HttpError

from automation_file.logging_config import file_automation_logger
from automation_file.remote.google_drive.client import driver_instance

_FOLDER_MIME = "application/vnd.google-apps.folder"


def drive_add_folder(folder_name: str) -> str | None:
    """Create a folder on Drive. Returns the new folder's ID or None."""
    metadata = {"name": folder_name, "mimeType": _FOLDER_MIME}
    try:
        response = (
            driver_instance.require_service()
            .files()
            .create(body=metadata, fields="id")
            .execute()
        )
        file_automation_logger.info("drive_add_folder: %s", folder_name)
        return response.get("id")
    except HttpError as error:
        file_automation_logger.error("drive_add_folder failed: %r", error)
        return None
