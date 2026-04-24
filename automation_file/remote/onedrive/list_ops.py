"""OneDrive listing operations."""

from __future__ import annotations

from typing import Any

from automation_file.logging_config import file_automation_logger
from automation_file.remote.onedrive.client import onedrive_instance


def onedrive_list_folder(remote_path: str = "") -> list[dict[str, Any]]:
    """List a folder under ``remote_path`` (root if empty). Returns a list of entries.

    Each entry is a minimal view: ``{"name": str, "type": "file"|"folder", "size": int}``.
    Graph's pagination ``@odata.nextLink`` is followed until exhausted so
    large folders return in one call.
    """
    encoded = remote_path.lstrip("/").replace(" ", "%20")
    path = f"/me/drive/root:/{encoded}:/children" if encoded else "/me/drive/root/children"
    entries: list[dict[str, Any]] = []
    cursor: str | None = path
    while cursor:
        response = onedrive_instance.graph_request("GET", cursor)
        payload = response.json()
        for item in payload.get("value", []):
            entries.append(
                {
                    "name": item.get("name", ""),
                    "type": "folder" if "folder" in item else "file",
                    "size": int(item.get("size", 0)),
                }
            )
        cursor = payload.get("@odata.nextLink")
    file_automation_logger.info(
        "onedrive_list_folder: %s -> %d entries", remote_path or "/", len(entries)
    )
    return entries
