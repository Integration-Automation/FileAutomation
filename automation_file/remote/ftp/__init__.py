"""FTP / FTPS strategy module.

Actions (``FA_ftp_*``) are registered on the shared default registry
automatically.
"""

from __future__ import annotations

from automation_file.core.action_registry import ActionRegistry
from automation_file.remote.ftp import delete_ops, download_ops, list_ops, upload_ops
from automation_file.remote.ftp.client import (
    FTPClient,
    FTPConnectOptions,
    FTPException,
    ftp_instance,
)


def register_ftp_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_ftp_*`` command into ``registry``."""
    registry.register_many(
        {
            "FA_ftp_later_init": ftp_instance.later_init,
            "FA_ftp_close": ftp_instance.close,
            "FA_ftp_upload_file": upload_ops.ftp_upload_file,
            "FA_ftp_upload_dir": upload_ops.ftp_upload_dir,
            "FA_ftp_download_file": download_ops.ftp_download_file,
            "FA_ftp_delete_path": delete_ops.ftp_delete_path,
            "FA_ftp_list_dir": list_ops.ftp_list_dir,
        }
    )


__all__ = [
    "FTPClient",
    "FTPConnectOptions",
    "FTPException",
    "ftp_instance",
    "register_ftp_ops",
]
