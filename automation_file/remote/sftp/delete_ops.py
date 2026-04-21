"""SFTP delete operations."""

from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.sftp.client import sftp_instance


def sftp_delete_path(remote_path: str) -> bool:
    """Delete a remote file. (Directories require a recursive helper.)"""
    sftp = sftp_instance.require_sftp()
    try:
        sftp.remove(remote_path)
        file_automation_logger.info("sftp_delete_path: %s", remote_path)
        return True
    except OSError as error:
        file_automation_logger.error("sftp_delete_path failed: %r", error)
        return False
