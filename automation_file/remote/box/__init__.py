"""Box strategy module.

Actions (``FA_box_*``) are registered on the shared default registry
automatically by :func:`build_default_registry`. :func:`register_box_ops`
is exposed for callers that build their own :class:`ActionRegistry`.
"""

from __future__ import annotations

from automation_file.core.action_registry import ActionRegistry
from automation_file.remote.box import delete_ops, download_ops, list_ops, upload_ops
from automation_file.remote.box.client import BoxClient, box_instance


def register_box_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_box_*`` command into ``registry``."""
    registry.register_many(
        {
            "FA_box_later_init": box_instance.later_init,
            "FA_box_upload_file": upload_ops.box_upload_file,
            "FA_box_upload_dir": upload_ops.box_upload_dir,
            "FA_box_download_file": download_ops.box_download_file,
            "FA_box_delete_file": delete_ops.box_delete_file,
            "FA_box_delete_folder": delete_ops.box_delete_folder,
            "FA_box_list_folder": list_ops.box_list_folder,
        }
    )


__all__ = ["BoxClient", "box_instance", "register_box_ops"]
