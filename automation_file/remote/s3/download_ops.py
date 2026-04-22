"""S3 download operations."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from automation_file.core.progress import (
    CancelledException,
    progress_registry,
)
from automation_file.logging_config import file_automation_logger
from automation_file.remote.s3.client import s3_instance


def s3_download_file(
    bucket: str,
    key: str,
    target_path: str,
    progress_name: str | None = None,
) -> bool:
    """Download ``s3://bucket/key`` to ``target_path``.

    Pass ``progress_name`` to register the transfer with the shared progress
    registry so it can be polled or cancelled mid-flight.
    """
    client = s3_instance.require_client()
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    callback: Callable[[int], None] | None = None
    reporter = None
    token = None
    if progress_name:
        total: int | None = None
        try:
            head = client.head_object(Bucket=bucket, Key=key)
            total = int(head.get("ContentLength", 0)) or None
        except Exception:  # pylint: disable=broad-except
            total = None
        reporter, token = progress_registry.create(progress_name, total=total)
        _reporter = reporter
        _token = token

        def _progress_callback(bytes_transferred: int) -> None:
            _token.raise_if_cancelled()
            _reporter.update(bytes_transferred)

        callback = _progress_callback

    try:
        client.download_file(bucket, key, target_path, Callback=callback)
        if reporter is not None:
            reporter.finish(status="done")
        file_automation_logger.info(
            "s3_download_file: s3://%s/%s -> %s",
            bucket,
            key,
            target_path,
        )
        return True
    except CancelledException:
        file_automation_logger.warning("s3_download_file cancelled: %s", progress_name)
        if reporter is not None:
            reporter.finish(status="cancelled")
        return False
    except Exception as error:  # pylint: disable=broad-except
        if reporter is not None:
            reporter.finish(status="error")
        file_automation_logger.error("s3_download_file failed: %r", error)
        return False
