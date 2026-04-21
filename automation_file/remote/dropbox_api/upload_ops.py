"""Dropbox upload operations."""
from __future__ import annotations

from pathlib import Path

from automation_file.exceptions import DirNotExistsException, FileNotExistsException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.dropbox_api.client import dropbox_instance


def _normalise_path(remote_path: str) -> str:
    return remote_path if remote_path.startswith("/") else f"/{remote_path}"


def dropbox_upload_file(file_path: str, remote_path: str) -> bool:
    """Upload a single file to ``remote_path`` (overwrites)."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotExistsException(str(path))
    client = dropbox_instance.require_client()
    try:
        from dropbox import files as dropbox_files  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError(
            "dropbox is required; install `automation_file[dropbox]`"
        ) from error
    try:
        with open(path, "rb") as fp:
            client.files_upload(
                fp.read(), _normalise_path(remote_path), mode=dropbox_files.WriteMode.overwrite,
            )
        file_automation_logger.info(
            "dropbox_upload_file: %s -> %s", path, remote_path,
        )
        return True
    except Exception as error:  # pylint: disable=broad-except
        file_automation_logger.error("dropbox_upload_file failed: %r", error)
        return False


def dropbox_upload_dir(dir_path: str, remote_prefix: str = "/") -> list[str]:
    """Upload every file under ``dir_path`` to Dropbox under ``remote_prefix``."""
    source = Path(dir_path)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    uploaded: list[str] = []
    prefix = remote_prefix.rstrip("/")
    for entry in source.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(source).as_posix()
        remote = f"{prefix}/{rel}" if prefix else f"/{rel}"
        if dropbox_upload_file(str(entry), remote):
            uploaded.append(remote)
    file_automation_logger.info(
        "dropbox_upload_dir: %s -> %s (%d files)", source, prefix, len(uploaded),
    )
    return uploaded
