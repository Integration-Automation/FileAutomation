"""OneDrive delete operations."""

from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.onedrive.client import onedrive_instance


def onedrive_delete_item(remote_path: str) -> bool:
    """Delete a file or folder at ``remote_path``."""
    encoded = remote_path.lstrip("/").replace(" ", "%20")
    onedrive_instance.graph_request("DELETE", f"/me/drive/root:/{encoded}")
    file_automation_logger.info("onedrive_delete_item: %s", remote_path)
    return True
