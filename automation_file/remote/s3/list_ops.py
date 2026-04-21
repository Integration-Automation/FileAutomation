"""S3 listing operations."""
from __future__ import annotations

from automation_file.logging_config import file_automation_logger
from automation_file.remote.s3.client import s3_instance


def s3_list_bucket(bucket: str, prefix: str = "") -> list[str]:
    """Return every key under ``bucket``/``prefix`` (paginated)."""
    client = s3_instance.require_client()
    keys: list[str] = []
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for entry in page.get("Contents", []):
                keys.append(entry["Key"])
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("s3_list_bucket failed: %r", error)
        return []
    file_automation_logger.info(
        "s3_list_bucket: s3://%s/%s (%d keys)", bucket, prefix, len(keys),
    )
    return keys
