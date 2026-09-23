"""Box listing operations."""

from __future__ import annotations

from typing import Any

from automation_file.exceptions import BoxException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.box.client import box_instance


def _type_name(item_type: Any) -> str:
    """``"file"``, ``"folder"`` or ``"web_link"``: the SDK reports the type as an enum."""
    return str(getattr(item_type, "value", item_type))


def box_list_folder(folder_id: str = "0", limit: int = 100) -> list[dict[str, Any]]:
    """List entries in a Box folder; return basic metadata per entry.

    ``folder_id="0"`` is Box's root. ``limit`` caps how many entries are
    returned — pagination is not followed so callers can stay under a
    reasonable payload size. Each entry is
    ``{"id": str, "name": str, "type": "file"|"folder"}``.
    """
    client = box_instance.require_client()
    try:
        items = client.folders.get_folder_items(folder_id, limit=limit).entries or []
        entries = [
            {
                "id": str(getattr(item, "id", "")),
                "name": getattr(item, "name", "") or "",
                "type": _type_name(getattr(item, "type", "file")),
            }
            for item in items
        ]
    except Exception as error:  # pylint: disable=broad-except
        raise BoxException(f"box_list_folder failed: {error}") from error
    file_automation_logger.info("box_list_folder: %s -> %d entries", folder_id, len(entries))
    return entries
