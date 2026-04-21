"""Dropbox delete operations."""

from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.dropbox_api.client import dropbox_instance


def dropbox_delete_path(remote_path: str) -> bool:
    """Delete a file or folder at ``remote_path``."""
    client = dropbox_instance.require_client()
    try:
        client.files_delete_v2(remote_path)
        file_automation_logger.info("dropbox_delete_path: %s", remote_path)
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("dropbox_delete_path failed: %r", error)
        return False
