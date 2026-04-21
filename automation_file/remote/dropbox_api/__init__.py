"""Dropbox strategy module (optional; requires ``dropbox``).

Named ``dropbox_api`` to avoid shadowing the ``dropbox`` PyPI package inside
``automation_file.remote``.
"""
from __future__ import annotations

from automation_file.core.action_registry import ActionRegistry
from automation_file.remote.dropbox_api import delete_ops, download_ops, list_ops, upload_ops
from automation_file.remote.dropbox_api.client import DropboxClient, dropbox_instance


def register_dropbox_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_dropbox_*`` command into ``registry``."""
    registry.register_many(
        {
            "FA_dropbox_later_init": dropbox_instance.later_init,
            "FA_dropbox_upload_file": upload_ops.dropbox_upload_file,
            "FA_dropbox_upload_dir": upload_ops.dropbox_upload_dir,
            "FA_dropbox_download_file": download_ops.dropbox_download_file,
            "FA_dropbox_delete_path": delete_ops.dropbox_delete_path,
            "FA_dropbox_list_folder": list_ops.dropbox_list_folder,
        }
    )


__all__ = ["DropboxClient", "dropbox_instance", "register_dropbox_ops"]
