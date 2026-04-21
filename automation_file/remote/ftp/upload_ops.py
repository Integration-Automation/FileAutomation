"""FTP upload operations."""

from __future__ import annotations

import posixpath
from ftplib import error_perm
from pathlib import Path

from automation_file.exceptions import FileNotExistsException
from automation_file.logging_config import file_automation_logger
from automation_file.remote._upload_tree import walk_and_upload
from automation_file.remote.ftp.client import ftp_instance


def _ensure_remote_dir(ftp, remote_dir: str) -> None:
    if not remote_dir or remote_dir in (".", "/"):
        return
    parts: list[str] = []
    current = remote_dir
    while current and current not in (".", "/"):
        parts.append(current)
        parent = posixpath.dirname(current)
        if parent == current:
            break
        current = parent
    for part in reversed(parts):
        try:
            ftp.mkd(part)
        except error_perm:
            continue


def ftp_upload_file(file_path: str, remote_path: str) -> bool:
    """Upload ``file_path`` to ``remote_path`` over FTP / FTPS."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotExistsException(str(path))
    ftp = ftp_instance.require_ftp()
    try:
        _ensure_remote_dir(ftp, posixpath.dirname(remote_path))
        with path.open("rb") as handle:
            ftp.storbinary(f"STOR {remote_path}", handle)
        file_automation_logger.info("ftp_upload_file: %s -> %s", path, remote_path)
        return True
    except OSError as error:
        file_automation_logger.error("ftp_upload_file failed: %r", error)
        return False


def ftp_upload_dir(dir_path: str, remote_prefix: str) -> list[str]:
    """Upload every file under ``dir_path`` to ``remote_prefix``."""
    result = walk_and_upload(
        dir_path,
        remote_prefix,
        lambda prefix, rel: f"{prefix}/{rel}" if prefix else rel,
        lambda local, remote: ftp_upload_file(str(local), remote),
    )
    file_automation_logger.info(
        "ftp_upload_dir: %s -> %s (%d files)",
        result.source,
        result.prefix,
        len(result.uploaded),
    )
    return result.uploaded
