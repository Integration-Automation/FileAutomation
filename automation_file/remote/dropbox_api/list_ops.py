"""Dropbox listing operations."""
from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.dropbox_api.client import dropbox_instance


def dropbox_list_folder(remote_path: str = "", recursive: bool = False) -> list[str]:
    """Return every path under ``remote_path``."""
    client = dropbox_instance.require_client()
    names: list[str] = []
    try:
        result = client.files_list_folder(remote_path, recursive=recursive)
        names.extend(entry.path_display for entry in result.entries)
        while getattr(result, "has_more", False):
            result = client.files_list_folder_continue(result.cursor)
            names.extend(entry.path_display for entry in result.entries)
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("dropbox_list_folder failed: %r", error)
        return []
    file_automation_logger.info(
        "dropbox_list_folder: %s (%d entries)", remote_path, len(names),
    )
    return names
