"""Cross-backend copy — stream a file from one storage backend to another.

``copy_between(source, target)`` resolves each URI to (backend, parameters),
downloads the source to a private temp file, then uploads from that temp
file to the target. Every backend already exposes ``*_download_file`` /
``*_upload_file`` primitives — this module just picks the right pair and
cleans up the intermediate temp file.

Supported URI schemes:

* ``local:/absolute/path`` or a bare filesystem path
* ``s3://bucket/key``
* ``azure://container/blob``
* ``dropbox:/path``
* ``sftp:/remote/path``
* ``ftp:/remote/path``
* ``http://...`` / ``https://...`` (source only)

Callers must have previously initialised every backend they reference
(``s3_instance.later_init``, etc.) — this helper does not manage sessions.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger


class CrossBackendException(FileAutomationException):
    """Raised when a URI is malformed or refers to an unknown backend."""


def copy_between(source: str, target: str) -> bool:
    """Copy the object at ``source`` to ``target`` via a local temp file.

    Returns True when both the download and the upload reported success.
    """
    downloader = _resolve_downloader(source)
    uploader = _resolve_uploader(target)
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        tmp_path = handle.name
    try:
        if not downloader(tmp_path):
            file_automation_logger.error("copy_between: download failed (%s)", source)
            return False
        if not uploader(tmp_path):
            file_automation_logger.error("copy_between: upload failed (%s)", target)
            return False
        file_automation_logger.info("copy_between: %s -> %s", source, target)
        return True
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _resolve_downloader(uri: str) -> Callable[[str], bool]:
    scheme, remainder = _split(uri)
    if scheme in ("local", ""):
        return lambda dest: _local_download(remainder, dest)
    if scheme == "s3":
        bucket, key = _split_bucket(remainder, "s3")
        from automation_file.remote.s3.download_ops import s3_download_file

        return lambda dest: bool(s3_download_file(bucket, key, dest))
    if scheme in ("azure", "az"):
        container, blob = _split_bucket(remainder, "azure")
        from automation_file.remote.azure_blob.download_ops import azure_blob_download_file

        return lambda dest: bool(azure_blob_download_file(container, blob, dest))
    if scheme == "dropbox":
        from automation_file.remote.dropbox_api.download_ops import dropbox_download_file

        return lambda dest: bool(dropbox_download_file(remainder, dest))
    if scheme == "sftp":
        from automation_file.remote.sftp.download_ops import sftp_download_file

        return lambda dest: bool(sftp_download_file(remainder, dest))
    if scheme == "ftp":
        from automation_file.remote.ftp.download_ops import ftp_download_file

        return lambda dest: bool(ftp_download_file(remainder, dest))
    if scheme in ("http", "https"):
        from automation_file.remote.http_download import download_file

        return lambda dest: bool(download_file(uri, dest))
    raise CrossBackendException(f"unknown source backend: {scheme!r}")


def _resolve_uploader(uri: str) -> Callable[[str], bool]:
    scheme, remainder = _split(uri)
    if scheme in ("local", ""):
        return lambda src: _local_upload(src, remainder)
    if scheme == "s3":
        bucket, key = _split_bucket(remainder, "s3")
        from automation_file.remote.s3.upload_ops import s3_upload_file

        return lambda src: bool(s3_upload_file(src, bucket, key))
    if scheme in ("azure", "az"):
        container, blob = _split_bucket(remainder, "azure")
        from automation_file.remote.azure_blob.upload_ops import azure_blob_upload_file

        return lambda src: bool(azure_blob_upload_file(src, container, blob))
    if scheme == "dropbox":
        from automation_file.remote.dropbox_api.upload_ops import dropbox_upload_file

        return lambda src: bool(dropbox_upload_file(src, remainder))
    if scheme == "sftp":
        from automation_file.remote.sftp.upload_ops import sftp_upload_file

        return lambda src: bool(sftp_upload_file(src, remainder))
    if scheme == "ftp":
        from automation_file.remote.ftp.upload_ops import ftp_upload_file

        return lambda src: bool(ftp_upload_file(src, remainder))
    raise CrossBackendException(f"unknown target backend: {scheme!r}")


_KNOWN_SCHEMES = frozenset(
    {"local", "s3", "azure", "az", "dropbox", "sftp", "ftp", "http", "https"}
)


def _split(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    # Treat single-character "schemes" (Windows drive letters) and URIs with
    # no scheme at all as local filesystem paths.
    if len(scheme) <= 1:
        return "", uri
    if scheme not in _KNOWN_SCHEMES:
        raise CrossBackendException(f"unknown backend scheme: {scheme!r}")
    if scheme in ("http", "https"):
        return scheme, uri
    if scheme in ("s3", "azure", "az"):
        if parsed.netloc:
            tail = parsed.path.lstrip("/")
            return scheme, f"{parsed.netloc}/{tail}" if tail else parsed.netloc
        return scheme, parsed.path.lstrip("/")
    if scheme == "local":
        if parsed.netloc:
            return "local", f"{parsed.netloc}{parsed.path}"
        return "local", parsed.path
    # Generic remote path (dropbox, sftp, ftp) — keep the path as given.
    combined = f"{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path
    return scheme, combined.lstrip("/")


def _split_bucket(remainder: str, scheme: str) -> tuple[str, str]:
    if "/" not in remainder:
        raise CrossBackendException(f"{scheme} URI must be <container>/<key>: {remainder!r}")
    bucket, key = remainder.split("/", 1)
    if not bucket or not key:
        raise CrossBackendException(f"{scheme} URI must be <container>/<key>: {remainder!r}")
    return bucket, key


def _local_download(source_path: str, dest_path: str) -> bool:
    src = Path(source_path)
    if not src.is_file():
        file_automation_logger.error("copy_between: local source missing: %s", src)
        return False
    shutil.copyfile(src, dest_path)
    return True


def _local_upload(source_path: str, target_path: str) -> bool:
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target)
    return True
