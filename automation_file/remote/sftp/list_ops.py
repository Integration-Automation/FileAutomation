"""SFTP listing operations."""
from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.sftp.client import sftp_instance


def sftp_list_dir(remote_path: str = ".") -> list[str]:
    """Return the non-recursive file listing of ``remote_path``."""
    sftp = sftp_instance.require_sftp()
    try:
        names = sftp.listdir(remote_path)
    except OSError as error:
        file_automation_logger.error("sftp_list_dir failed: %r", error)
        return []
    file_automation_logger.info(
        "sftp_list_dir: %s (%d entries)", remote_path, len(names),
    )
    return list(names)
