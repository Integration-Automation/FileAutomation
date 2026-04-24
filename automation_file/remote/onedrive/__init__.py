"""OneDrive strategy module (Microsoft Graph via MSAL).

Actions (``FA_onedrive_*``) are registered on the shared default registry
automatically by :func:`build_default_registry`. :func:`register_onedrive_ops`
is exposed for callers that build their own :class:`ActionRegistry`.
"""

from __future__ import annotations

from automation_file.core.action_registry import ActionRegistry
from automation_file.remote.onedrive import delete_ops, download_ops, list_ops, upload_ops
from automation_file.remote.onedrive.client import OneDriveClient, onedrive_instance


def register_onedrive_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_onedrive_*`` command into ``registry``."""
    registry.register_many(
        {
            "FA_onedrive_later_init": onedrive_instance.later_init,
            "FA_onedrive_device_code_login": onedrive_instance.device_code_login,
            "FA_onedrive_upload_file": upload_ops.onedrive_upload_file,
            "FA_onedrive_upload_dir": upload_ops.onedrive_upload_dir,
            "FA_onedrive_download_file": download_ops.onedrive_download_file,
            "FA_onedrive_delete_item": delete_ops.onedrive_delete_item,
            "FA_onedrive_list_folder": list_ops.onedrive_list_folder,
            "FA_onedrive_close": onedrive_instance.close,
        }
    )


__all__ = ["OneDriveClient", "onedrive_instance", "register_onedrive_ops"]
