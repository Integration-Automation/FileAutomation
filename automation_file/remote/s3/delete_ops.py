"""S3 delete operations."""
from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.s3.client import s3_instance


def s3_delete_object(bucket: str, key: str) -> bool:
    """Delete ``s3://bucket/key``. Returns True on success."""
    client = s3_instance.require_client()
    try:
        client.delete_object(Bucket=bucket, Key=key)
        file_automation_logger.info("s3_delete_object: s3://%s/%s", bucket, key)
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("s3_delete_object failed: %r", error)
        return False
