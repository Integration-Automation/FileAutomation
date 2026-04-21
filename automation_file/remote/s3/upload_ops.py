"""S3 upload operations."""
from __future__ import annotations

from pathlib import Path

from automation_file.exceptions import DirNotExistsException, FileNotExistsException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.s3.client import s3_instance


def s3_upload_file(file_path: str, bucket: str, key: str) -> bool:
    """Upload a single file to ``s3://bucket/key``."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotExistsException(str(path))
    client = s3_instance.require_client()
    try:
        client.upload_file(str(path), bucket, key)
        file_automation_logger.info("s3_upload_file: %s -> s3://%s/%s", path, bucket, key)
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("s3_upload_file failed: %r", error)
        return False


def s3_upload_dir(dir_path: str, bucket: str, key_prefix: str = "") -> list[str]:
    """Upload every file under ``dir_path`` to ``bucket`` under ``key_prefix``."""
    source = Path(dir_path)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    uploaded: list[str] = []
    prefix = key_prefix.rstrip("/")
    for entry in source.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(source).as_posix()
        key = f"{prefix}/{rel}" if prefix else rel
        if s3_upload_file(str(entry), bucket, key):
            uploaded.append(key)
    file_automation_logger.info(
        "s3_upload_dir: %s -> s3://%s/%s (%d files)",
        source, bucket, prefix, len(uploaded),
    )
    return uploaded
