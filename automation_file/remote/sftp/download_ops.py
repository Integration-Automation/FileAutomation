"""SFTP download operations."""

from __future__ import annotations

from pathlib import Path

from automation_file.logging_config import file_automation_logger
from automation_file.remote.sftp.client import sftp_instance


def sftp_download_file(remote_path: str, target_path: str) -> bool:
    """Download ``remote_path`` to ``target_path``."""
    sftp = sftp_instance.require_sftp()
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        sftp.get(remote_path, target_path)
        file_automation_logger.info(
            "sftp_download_file: %s -> %s",
            remote_path,
            target_path,
        )
        return True
    except OSError as error:
        file_automation_logger.error("sftp_download_file failed: %r", error)
        return False
