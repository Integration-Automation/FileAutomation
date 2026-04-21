"""FTP download operations."""

from __future__ import annotations

from pathlib import Path

from automation_file.logging_config import file_automation_logger
from automation_file.remote.ftp.client import ftp_instance


def ftp_download_file(remote_path: str, target_path: str) -> bool:
    """Download ``remote_path`` to ``target_path`` over FTP / FTPS."""
    ftp = ftp_instance.require_ftp()
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("wb") as handle:
            ftp.retrbinary(f"RETR {remote_path}", handle.write)
        file_automation_logger.info("ftp_download_file: %s -> %s", remote_path, target)
        return True
    except OSError as error:
        file_automation_logger.error("ftp_download_file failed: %r", error)
        return False
