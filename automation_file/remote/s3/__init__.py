"""S3 strategy module (optional; requires ``boto3``).

Users who need S3 should ``pip install automation_file[s3]`` and call
:func:`register_s3_ops` on the shared registry::

    from automation_file import executor
    from automation_file.remote.s3 import register_s3_ops
    register_s3_ops(executor.registry)
"""
from __future__ import annotations

from automation_file.core.action_registry import ActionRegistry
from automation_file.remote.s3 import delete_ops, download_ops, list_ops, upload_ops
from automation_file.remote.s3.client import S3Client, s3_instance


def register_s3_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_s3_*`` command into ``registry``."""
    registry.register_many(
        {
            "FA_s3_later_init": s3_instance.later_init,
            "FA_s3_upload_file": upload_ops.s3_upload_file,
            "FA_s3_upload_dir": upload_ops.s3_upload_dir,
            "FA_s3_download_file": download_ops.s3_download_file,
            "FA_s3_delete_object": delete_ops.s3_delete_object,
            "FA_s3_list_bucket": list_ops.s3_list_bucket,
        }
    )


__all__ = ["S3Client", "s3_instance", "register_s3_ops"]
