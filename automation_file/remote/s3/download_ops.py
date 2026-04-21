"""S3 download operations."""

from __future__ import annotations

from pathlib import Path

from automation_file.logging_config import file_automation_logger
from automation_file.remote.s3.client import s3_instance


def s3_download_file(bucket: str, key: str, target_path: str) -> bool:
    """Download ``s3://bucket/key`` to ``target_path``."""
    client = s3_instance.require_client()
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(bucket, key, target_path)
        file_automation_logger.info(
            "s3_download_file: s3://%s/%s -> %s",
            bucket,
            key,
            target_path,
        )
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("s3_download_file failed: %r", error)
        return False
