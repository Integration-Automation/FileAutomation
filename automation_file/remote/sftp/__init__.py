"""SFTP strategy module.

Actions (``FA_sftp_*``) are registered on the shared default registry
automatically.
"""

from __future__ import annotations

from automation_file.core.action_registry import ActionRegistry
from automation_file.remote.sftp import delete_ops, download_ops, list_ops, upload_ops
from automation_file.remote.sftp.client import SFTPClient, sftp_instance


def register_sftp_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_sftp_*`` command into ``registry``."""
    registry.register_many(
        {
            "FA_sftp_later_init": sftp_instance.later_init,
            "FA_sftp_close": sftp_instance.close,
            "FA_sftp_upload_file": upload_ops.sftp_upload_file,
            "FA_sftp_upload_dir": upload_ops.sftp_upload_dir,
            "FA_sftp_download_file": download_ops.sftp_download_file,
            "FA_sftp_delete_path": delete_ops.sftp_delete_path,
            "FA_sftp_list_dir": list_ops.sftp_list_dir,
        }
    )


__all__ = ["SFTPClient", "register_sftp_ops", "sftp_instance"]
