"""OneDrive upload operations (Microsoft Graph)."""

from __future__ import annotations

from pathlib import Path

from automation_file.exceptions import FileNotExistsException, OneDriveException
from automation_file.logging_config import file_automation_logger
from automation_file.remote._upload_tree import walk_and_upload
from automation_file.remote.onedrive.client import onedrive_instance

# 4 MB — Graph's documented upper bound for simple PUT uploads.
_SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024


def onedrive_upload_file(file_path: str, remote_path: str) -> bool:
    """Upload a local file to ``remote_path`` under ``/me/drive/root``.

    ``remote_path`` is treated as a posix-style path relative to the drive
    root (e.g. ``Documents/report.pdf``). Parent folders are created lazily
    by Graph when present in the path. Files over 4 MiB are rejected so
    callers don't silently truncate — resumable upload sessions are a
    separate helper that can be added later.
    """
    local = Path(file_path)
    if not local.is_file():
        raise FileNotExistsException(str(local))
    size = local.stat().st_size
    if size > _SIMPLE_UPLOAD_MAX:
        raise OneDriveException(
            f"{local} is {size} bytes; simple upload is capped at {_SIMPLE_UPLOAD_MAX}"
        )
    data = local.read_bytes()
    encoded = remote_path.lstrip("/").replace(" ", "%20")
    onedrive_instance.graph_request(
        "PUT",
        f"/me/drive/root:/{encoded}:/content",
        data=data,
        headers={"Content-Type": "application/octet-stream"},
    )
    file_automation_logger.info("onedrive_upload_file: %s -> %s", local, remote_path)
    return True


def onedrive_upload_dir(dir_path: str, remote_prefix: str = "") -> list[str]:
    """Upload every file under ``dir_path`` to ``remote_prefix``."""
    result = walk_and_upload(
        dir_path,
        remote_prefix,
        lambda prefix, rel: f"{prefix}/{rel}" if prefix else rel,
        lambda local, name: onedrive_upload_file(str(local), name),
    )
    file_automation_logger.info(
        "onedrive_upload_dir: %s -> %s (%d files)",
        result.source,
        result.prefix,
        len(result.uploaded),
    )
    return result.uploaded
