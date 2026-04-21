"""FTP delete operations."""

from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.ftp.client import ftp_instance


def ftp_delete_path(remote_path: str) -> bool:
    """Delete a remote file over FTP / FTPS."""
    ftp = ftp_instance.require_ftp()
    try:
        ftp.delete(remote_path)
        file_automation_logger.info("ftp_delete_path: %s", remote_path)
        return True
    except OSError as error:
        file_automation_logger.error("ftp_delete_path failed: %r", error)
        return False
