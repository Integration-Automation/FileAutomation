"""Dropbox download operations."""
from __future__ import annotations

from pathlib import Path

from automation_file.logging_config import file_automation_logger
from automation_file.remote.dropbox_api.client import dropbox_instance


def dropbox_download_file(remote_path: str, target_path: str) -> bool:
    """Download ``remote_path`` to ``target_path``."""
    client = dropbox_instance.require_client()
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        client.files_download_to_file(target_path, remote_path)
        file_automation_logger.info(
            "dropbox_download_file: %s -> %s", remote_path, target_path,
        )
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("dropbox_download_file failed: %r", error)
        return False
