"""OneDrive download operations."""

from __future__ import annotations

from pathlib import Path

from automation_file.logging_config import file_automation_logger
from automation_file.remote.onedrive.client import onedrive_instance


def onedrive_download_file(remote_path: str, target_path: str) -> bool:
    """Download ``remote_path`` to ``target_path`` via Microsoft Graph."""
    encoded = remote_path.lstrip("/").replace(" ", "%20")
    response = onedrive_instance.graph_request(
        "GET", f"/me/drive/root:/{encoded}:/content", timeout=120.0
    )
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    file_automation_logger.info(
        "onedrive_download_file: %s -> %s (%d bytes)", remote_path, target, len(response.content)
    )
    return True
