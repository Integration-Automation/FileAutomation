"""SFTP upload operations."""
from __future__ import annotations

import posixpath
from pathlib import Path

from automation_file.exceptions import DirNotExistsException, FileNotExistsException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.sftp.client import sftp_instance


def _ensure_remote_dir(sftp, remote_dir: str) -> None:
    if not remote_dir or remote_dir == "/":
        return
    parts: list[str] = []
    current = remote_dir
    while current not in ("", "/"):
        parts.append(current)
        current = posixpath.dirname(current)
    for part in reversed(parts):
        try:
            sftp.stat(part)
        except FileNotFoundError:
            sftp.mkdir(part)


def sftp_upload_file(file_path: str, remote_path: str) -> bool:
    """Upload ``file_path`` to ``remote_path`` over SFTP."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotExistsException(str(path))
    sftp = sftp_instance.require_sftp()
    try:
        _ensure_remote_dir(sftp, posixpath.dirname(remote_path))
        sftp.put(str(path), remote_path)
        file_automation_logger.info("sftp_upload_file: %s -> %s", path, remote_path)
        return True
    except OSError as error:
        file_automation_logger.error("sftp_upload_file failed: %r", error)
        return False


def sftp_upload_dir(dir_path: str, remote_prefix: str) -> list[str]:
    """Upload every file under ``dir_path`` to ``remote_prefix``."""
    source = Path(dir_path)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    uploaded: list[str] = []
    prefix = remote_prefix.rstrip("/")
    for entry in source.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(source).as_posix()
        remote = f"{prefix}/{rel}" if prefix else rel
        if sftp_upload_file(str(entry), remote):
            uploaded.append(remote)
    file_automation_logger.info(
        "sftp_upload_dir: %s -> %s (%d files)", source, prefix, len(uploaded),
    )
    return uploaded
