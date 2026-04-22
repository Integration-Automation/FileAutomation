"""S3 upload operations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from automation_file.core.progress import (
    CancelledException,
    progress_registry,
)
from automation_file.exceptions import FileNotExistsException
from automation_file.logging_config import file_automation_logger
from automation_file.remote._upload_tree import walk_and_upload
from automation_file.remote.s3.client import s3_instance


def s3_upload_file(
    file_path: str,
    bucket: str,
    key: str,
    progress_name: str | None = None,
) -> bool:
    """Upload a single file to ``s3://bucket/key``.

    Pass ``progress_name`` to register the transfer with the shared progress
    registry so it can be polled or cancelled mid-flight.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotExistsException(str(path))
    client = s3_instance.require_client()
    callback: Callable[[int], None] | None = None
    reporter = None
    token = None
    if progress_name:
        reporter, token = progress_registry.create(progress_name, total=path.stat().st_size)
        _reporter = reporter
        _token = token

        def _progress_callback(bytes_transferred: int) -> None:
            _token.raise_if_cancelled()
            _reporter.update(bytes_transferred)

        callback = _progress_callback

    try:
        client.upload_file(str(path), bucket, key, Callback=callback)
        if reporter is not None:
            reporter.finish(status="done")
        file_automation_logger.info("s3_upload_file: %s -> s3://%s/%s", path, bucket, key)
        return True
    except CancelledException:
        file_automation_logger.warning("s3_upload_file cancelled: %s", progress_name)
        if reporter is not None:
            reporter.finish(status="cancelled")
        return False
    except Exception as error:  # pylint: disable=broad-except
        if reporter is not None:
            reporter.finish(status="error")
        file_automation_logger.error("s3_upload_file failed: %r", error)
        return False


def s3_upload_dir(dir_path: str, bucket: str, key_prefix: str = "") -> list[str]:
    """Upload every file under ``dir_path`` to ``bucket`` under ``key_prefix``."""
    result = walk_and_upload(
        dir_path,
        key_prefix,
        lambda prefix, rel: f"{prefix}/{rel}" if prefix else rel,
        lambda local, key: s3_upload_file(str(local), bucket, key),
    )
    file_automation_logger.info(
        "s3_upload_dir: %s -> s3://%s/%s (%d files)",
        result.source,
        bucket,
        result.prefix,
        len(result.uploaded),
    )
    return result.uploaded
