"""Box download operations."""

from __future__ import annotations

from pathlib import Path

from automation_file.exceptions import BoxException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.box.client import box_instance


def box_download_file(file_id: str, target_path: str) -> bool:
    """Download Box file ``file_id`` to ``target_path``."""
    client = box_instance.require_client()
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "wb") as writer:
            client.file(file_id=file_id).download_to(writer)
    except Exception as error:  # pylint: disable=broad-except
        raise BoxException(f"box_download_file failed: {error}") from error
    file_automation_logger.info("box_download_file: %s -> %s", file_id, target)
    return True
