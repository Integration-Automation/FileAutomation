"""FTP listing operations."""

from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.ftp.client import ftp_instance


def ftp_list_dir(remote_path: str = ".") -> list[str]:
    """Return the non-recursive listing of ``remote_path``."""
    ftp = ftp_instance.require_ftp()
    try:
        names = ftp.nlst(remote_path)
    except OSError as error:
        file_automation_logger.error("ftp_list_dir failed: %r", error)
        return []
    file_automation_logger.info("ftp_list_dir: %s (%d entries)", remote_path, len(names))
    return list(names)
