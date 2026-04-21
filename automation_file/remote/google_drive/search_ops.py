"""Search-side Google Drive operations."""
from __future__ import annotations

from googleapiclient.errors import HttpError

from automation_file.logging_config import file_automation_logger
from automation_file.remote.google_drive.client import driver_instance


def drive_search_all_file() -> dict[str, str] | None:
    """Return ``{name: id}`` for every file visible to the current token."""
    try:
        response = driver_instance.require_service().files().list().execute()
    except HttpError as error:
        file_automation_logger.error("drive_search_all_file failed: %r", error)
        return None
    result = {file.get("name"): file.get("id") for file in response.get("files", [])}
    file_automation_logger.info("drive_search_all_file: %d results", len(result))
    return result


def drive_search_file_mimetype(mime_type: str) -> dict[str, str] | None:
    """Return ``{name: id}`` for files matching ``mime_type`` (all pages)."""
    results: dict[str, str] = {}
    page_token: str | None = None
    service = driver_instance.require_service()
    try:
        while True:
            response = (
                service.files()
                .list(
                    q=f"mimeType='{mime_type}'",
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                )
                .execute()
            )
            for file in response.get("files", []):
                results[file.get("name")] = file.get("id")
            page_token = response.get("nextPageToken")
            if page_token is None:
                break
    except HttpError as error:
        file_automation_logger.error("drive_search_file_mimetype failed: %r", error)
        return None
    file_automation_logger.info(
        "drive_search_file_mimetype: mime=%s %d results", mime_type, len(results)
    )
    return results


def drive_search_field(field_pattern: str) -> dict[str, str] | None:
    """Return ``{name: id}`` for a list call with a custom ``fields=`` pattern."""
    try:
        response = (
            driver_instance.require_service()
            .files()
            .list(fields=field_pattern)
            .execute()
        )
    except HttpError as error:
        file_automation_logger.error("drive_search_field failed: %r", error)
        return None
    result = {file.get("name"): file.get("id") for file in response.get("files", [])}
    file_automation_logger.info("drive_search_field: %d results", len(result))
    return result
