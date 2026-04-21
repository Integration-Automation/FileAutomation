"""Upload-side Google Drive operations."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from automation_file.exceptions import FileNotExistsException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.google_drive.client import driver_instance


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def _upload(path: Path, metadata: dict, description: str) -> dict | None:
    try:
        media = MediaFileUpload(str(path), mimetype=_guess_mime(path), resumable=True)
        response = (
            driver_instance.require_service()
            .files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        file_automation_logger.info("drive_upload (%s): %s", description, path)
        return response
    except HttpError as error:
        file_automation_logger.error("drive_upload (%s) failed: %r", description, error)
        return None


def drive_upload_to_drive(file_path: str, file_name: str | None = None) -> dict | None:
    """Upload a single file to the Drive root."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotExistsException(str(path))
    metadata = {"name": file_name or path.name, "mimeType": _guess_mime(path)}
    return _upload(path, metadata, f"root,name={metadata['name']}")


def drive_upload_to_folder(
    folder_id: str, file_path: str, file_name: str | None = None
) -> dict | None:
    """Upload a single file into a specific Drive folder."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotExistsException(str(path))
    metadata = {
        "name": file_name or path.name,
        "mimeType": _guess_mime(path),
        "parents": [folder_id],
    }
    return _upload(path, metadata, f"folder={folder_id},name={metadata['name']}")


def drive_upload_dir_to_drive(dir_path: str) -> list[dict | None]:
    """Upload every file in ``dir_path`` (non-recursive) to the Drive root."""
    source = Path(dir_path)
    if not source.is_dir():
        return []
    results: list[dict | None] = []
    for entry in source.iterdir():
        if entry.is_file():
            results.append(drive_upload_to_drive(str(entry.absolute()), entry.name))
    file_automation_logger.info("drive_upload_dir_to_drive: %s (%d files)", source, len(results))
    return results


def drive_upload_dir_to_folder(folder_id: str, dir_path: str) -> list[dict | None]:
    """Upload every file in ``dir_path`` (non-recursive) to a Drive folder."""
    source = Path(dir_path)
    if not source.is_dir():
        return []
    results: list[dict | None] = []
    for entry in source.iterdir():
        if entry.is_file():
            results.append(drive_upload_to_folder(folder_id, str(entry.absolute()), entry.name))
    file_automation_logger.info(
        "drive_upload_dir_to_folder: %s -> %s (%d files)",
        source,
        folder_id,
        len(results),
    )
    return results
