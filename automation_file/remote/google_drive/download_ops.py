"""Download-side Google Drive operations."""

from __future__ import annotations

import io

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from automation_file.logging_config import file_automation_logger
from automation_file.remote.google_drive.client import driver_instance


def drive_download_file(file_id: str, file_name: str) -> io.BytesIO | None:
    """Download a single file by ID to ``file_name`` on disk.

    Returns the in-memory buffer on success, or ``None`` on failure. The file
    is **only** written after the download completes cleanly, so a failed
    request cannot leave an empty file behind.
    """
    service = driver_instance.require_service()
    buffer = io.BytesIO()
    try:
        request = service.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status is not None:
                file_automation_logger.info(
                    "drive_download_file: %s %d%%",
                    file_name,
                    int(status.progress() * 100),
                )
    except HttpError as error:
        file_automation_logger.error("drive_download_file failed: %r", error)
        return None

    with open(file_name, "wb") as output_file:
        output_file.write(buffer.getbuffer())
    file_automation_logger.info("drive_download_file: %s -> %s", file_id, file_name)
    return buffer


def drive_download_file_from_folder(folder_name: str) -> dict[str, str] | None:
    """Download every file inside the Drive folder named ``folder_name``."""
    service = driver_instance.require_service()
    try:
        folders = (
            service.files()
            .list(q=f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}'")
            .execute()
        )
        folder_list = folders.get("files", [])
        if not folder_list:
            file_automation_logger.error(
                "drive_download_file_from_folder: folder not found: %s",
                folder_name,
            )
            return None
        folder_id = folder_list[0].get("id")
        response = service.files().list(q=f"'{folder_id}' in parents").execute()
    except HttpError as error:
        file_automation_logger.error("drive_download_file_from_folder failed: %r", error)
        return None

    result: dict[str, str] = {}
    for file in response.get("files", []):
        drive_download_file(file.get("id"), file.get("name"))
        result[file.get("name")] = file.get("id")
    file_automation_logger.info(
        "drive_download_file_from_folder: %s (%d files)",
        folder_name,
        len(result),
    )
    return result
