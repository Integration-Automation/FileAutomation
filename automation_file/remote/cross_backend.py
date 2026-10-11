"""Cross-backend copy: one file from a storage location to another.

``copy_between(source, target)`` is the older spelling of
``File(source).copy_to(target)``. It resolves both locations to a storage
backend and lets the storage layer do the transfer, so the copy is native where
two backends can do it between themselves, is reported to the storage
observers, and shows up in the audit trail.

Locations it accepts:

* any storage URI (``s3://bucket/key``, ``azure://container/blob``,
  ``gdrive:///path``, ``sftp://host/absolute/path``, ``memory://name/path``,
  a mounted prefix, ...), see :mod:`automation_file.storage`;
* a bare filesystem path, ``local:<path>`` or ``local:/absolute/path``;
* ``s3:bucket/key`` and ``azure:container/blob`` without the slashes;
* ``dropbox:/path``;
* ``sftp:/path`` and ``ftp:/path`` with one slash or none: the path is taken
  relative to the directory the session logged in to, as it always was. With
  two slashes (``sftp://host/path``) the URI names a host and an absolute path;
* ``http://...`` / ``https://...`` as a source only, fetched with
  :func:`automation_file.remote.http_download.download_file` and its SSRF guard.

Every backend involved must have been initialised (``s3_instance.later_init``,
...). The function returns ``False`` when the transfer itself fails (a missing
source, a refused write), and raises for a location it cannot make sense of
(:class:`CrossBackendException`) or a backend that is not initialised.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from automation_file.exceptions import (
    FileAutomationException,
    StorageUnavailableException,
    StorageURIException,
)
from automation_file.logging_config import file_automation_logger

if TYPE_CHECKING:
    from automation_file.storage.backend import StorageBackend

_LOCAL = "local"
_SFTP = "sftp"
_HTTP_SCHEMES = ("http", "https")
_BUCKET_SCHEMES = ("s3", "azure", "az")
_SESSION_SCHEMES = (_SFTP, "ftp")
_STAGED_NAME = "download"
_AUTHORITY_MARK = "//"
_KNOWN_SCHEMES = frozenset({_LOCAL, *_BUCKET_SCHEMES, "dropbox", *_SESSION_SCHEMES, *_HTTP_SCHEMES})


class CrossBackendException(FileAutomationException):
    """Raised when a location is malformed or names an unknown backend."""


def copy_between(source: str, target: str) -> bool:
    """Copy the file at ``source`` to ``target`` and return whether it was transferred.

    A file already at ``target`` is replaced. ``False`` means the transfer failed
    and the reason was logged.
    """
    if _scheme_of(target) in _HTTP_SCHEMES:
        raise CrossBackendException(f"unknown target backend: {_scheme_of(target)!r}")
    try:
        destination, path = _locate(target, "target")
        if _scheme_of(source) in _HTTP_SCHEMES:
            transferred = _fetch_into(source, destination, path)
        else:
            origin, origin_path = _locate(source, "source")
            destination.copy_from(origin, origin_path, path)
            transferred = True
    except (CrossBackendException, StorageUnavailableException):
        raise
    except FileAutomationException as error:
        file_automation_logger.error(
            "copy_between: %s -> %s failed: %s: %s", source, target, type(error).__name__, error
        )
        return False
    if transferred:
        file_automation_logger.info("copy_between: %s -> %s", source, target)
    return transferred


def _fetch_into(url: str, destination: StorageBackend, path: str) -> bool:
    """Download ``url`` to a staging file and store it at ``path``."""
    from automation_file.remote.http_download import download_file

    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / _STAGED_NAME
        if not download_file(url, str(staged)):
            file_automation_logger.error("copy_between: download failed (%s)", url)
            return False
        destination.upload(staged, path)
    return True


def _scheme_of(uri: str) -> str:
    """Return the lower-cased scheme of ``uri``; a drive letter or no scheme is ``""``."""
    scheme = urlparse(uri).scheme.lower()
    return scheme if len(scheme) > 1 else ""


def _locate(uri: str, role: str) -> tuple[StorageBackend, str]:
    """Return the backend and the path of ``uri``, which is the ``role`` of a copy."""
    scheme = _scheme_of(uri)
    if scheme and scheme not in _KNOWN_SCHEMES:
        return _resolve(uri, role)
    if scheme in _SESSION_SCHEMES and uri[len(scheme) + 1 :].startswith(_AUTHORITY_MARK):
        return _resolve(uri, role)
    scheme, remainder = _split(uri)
    if scheme in ("", _LOCAL):
        # abspath folds the '..' segments a storage URI may not contain.
        return _resolve(os.path.abspath(remainder), role)
    if scheme in _BUCKET_SCHEMES:
        container, key = _split_bucket(remainder, scheme)
        return _resolve(f"{scheme}://{container}/{key}", role)
    if scheme in _SESSION_SCHEMES:
        return _in_login_directory(scheme), remainder
    return _resolve(f"{scheme}:///{remainder}", role)


def _resolve(uri: str, role: str) -> tuple[StorageBackend, str]:
    from automation_file.storage.resolver import default_resolver

    try:
        return default_resolver.resolve(uri)
    except StorageURIException as error:
        raise CrossBackendException(f"unknown {role} backend: {error}") from error


def _in_login_directory(scheme: str) -> StorageBackend:
    """Return a backend rooted where the open session logged in.

    ``sftp:/path`` and ``ftp:/path`` have always been sent to the server without
    their leading slash, which a server resolves against the login directory.
    """
    if scheme == _SFTP:
        from automation_file.remote.sftp.client import sftp_instance
        from automation_file.storage.sftp_storage import SFTPStorage

        try:
            return SFTPStorage(root=sftp_instance.require_sftp().normalize("."))
        except RuntimeError as error:
            raise StorageUnavailableException(str(error)) from error
    from automation_file.remote.ftp.client import FTPException, ftp_instance
    from automation_file.storage.ftp_storage import FTPStorage

    try:
        return FTPStorage(root=ftp_instance.require_ftp().pwd())
    except FTPException as error:
        raise StorageUnavailableException(str(error)) from error


def _split(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    # Treat single-character "schemes" (Windows drive letters) and URIs with
    # no scheme at all as local filesystem paths.
    if len(scheme) <= 1:
        return "", uri
    if scheme not in _KNOWN_SCHEMES:
        raise CrossBackendException(f"unknown backend scheme: {scheme!r}")
    if scheme in _HTTP_SCHEMES:
        return scheme, uri
    if scheme in _BUCKET_SCHEMES:
        if parsed.netloc:
            tail = parsed.path.lstrip("/")
            return scheme, f"{parsed.netloc}/{tail}" if tail else parsed.netloc
        return scheme, parsed.path.lstrip("/")
    if scheme == _LOCAL:
        if parsed.netloc:
            return _LOCAL, f"{parsed.netloc}{parsed.path}"
        return _LOCAL, parsed.path
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
