"""SSRF-guarded HTTP downloader."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

import requests
from tqdm import tqdm

from automation_file.core.checksum import verify_checksum
from automation_file.core.progress import (
    CancelledException,
    ProgressReporter,
    progress_registry,
)
from automation_file.core.retry import retry_on_transient
from automation_file.exceptions import RetryExhaustedException, UrlValidationException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.url_validator import validate_http_url

_DEFAULT_TIMEOUT_SECONDS = 15
_DEFAULT_CHUNK_SIZE = 1024 * 64
_MAX_RESPONSE_BYTES = 20 * 1024 * 1024

_RETRIABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


@retry_on_transient(max_attempts=3, backoff_base=0.5, retriable=_RETRIABLE_EXCEPTIONS)
def _open_stream(
    file_url: str,
    timeout: int,
    start_byte: int = 0,
) -> requests.Response:
    headers = {"Range": f"bytes={start_byte}-"} if start_byte > 0 else None
    response = requests.get(
        file_url,
        stream=True,
        timeout=timeout,
        allow_redirects=False,
        headers=headers,
    )
    response.raise_for_status()
    return response


def _resume_layout(target: Path, resume: bool) -> tuple[Path, int, str]:
    part_path = target.with_suffix(target.suffix + ".part") if resume else target
    start_byte = part_path.stat().st_size if resume and part_path.exists() else 0
    write_mode = "ab" if start_byte > 0 else "wb"
    return part_path, start_byte, write_mode


def _open_stream_logged(file_url: str, timeout: int, start_byte: int) -> requests.Response | None:
    try:
        return _open_stream(file_url, timeout, start_byte=start_byte)
    except RetryExhaustedException as error:
        file_automation_logger.error("download_file retries exhausted: %r", error)
    except requests.exceptions.HTTPError as error:
        file_automation_logger.error("download_file HTTP error: %r", error)
    except requests.exceptions.RequestException as error:
        file_automation_logger.error("download_file request error: %r", error)
    return None


def _stream_to_disk(
    response: requests.Response,
    part_path: Path,
    target: Path,
    *,
    write_mode: str,
    chunk_size: int,
    start_byte: int,
    total_size: int,
    max_bytes: int,
    reporter: ProgressReporter | None,
    token: Any,
) -> int | None:
    """Stream ``response`` into ``part_path``. Returns bytes written, or None on failure."""
    written = start_byte
    with (
        open(part_path, write_mode) as output,
        _progress(total_size, str(target)) as progress,
    ):
        if start_byte > 0:
            progress.update(start_byte)
        for chunk in response.iter_content(chunk_size=chunk_size):
            if token is not None:
                token.raise_if_cancelled()
            if not chunk:
                continue
            written += len(chunk)
            if written > max_bytes:
                file_automation_logger.error(
                    "download_file aborted: stream exceeded %d bytes", max_bytes
                )
                return None
            output.write(chunk)
            progress.update(len(chunk))
            if reporter is not None:
                reporter.update(len(chunk))
    return written


def _verify_and_finalize(
    target: Path,
    expected_sha256: str | None,
    reporter: ProgressReporter | None,
) -> bool:
    if expected_sha256 and not verify_checksum(target, expected_sha256):
        file_automation_logger.error("download_file checksum mismatch for %s; removing", target)
        with contextlib.suppress(OSError):
            target.unlink()
        if reporter is not None:
            reporter.finish(status="checksum_failed")
        return False
    if reporter is not None:
        reporter.finish(status="done")
    return True


def download_file(
    file_url: str,
    file_name: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = _MAX_RESPONSE_BYTES,
    progress_name: str | None = None,
    resume: bool = False,
    expected_sha256: str | None = None,
) -> bool:
    """Download ``file_url`` to ``file_name`` with progress display.

    Validates the URL against SSRF rules, disables redirects, enforces a size
    cap, retries transient network errors up to three times, and uses default
    TLS verification.

    Pass ``progress_name`` to register the transfer with
    :data:`~automation_file.core.progress.progress_registry` so it can be
    polled or cancelled from the GUI. When ``resume=True`` the download
    streams into ``<file_name>.part`` and, if that file already exists from a
    previous interrupted run, sends ``Range: bytes=<existing>-`` to continue
    where it stopped (append mode); the ``.part`` file is atomically renamed
    to ``file_name`` on success. Pass ``expected_sha256`` to verify the
    finished file; a mismatch is logged, the download is removed, and the
    function returns ``False``. Returns True on success.
    """
    try:
        validate_http_url(file_url)
    except UrlValidationException as error:
        file_automation_logger.error("download_file rejected URL: %r", error)
        return False

    target = Path(file_name)
    part_path, start_byte, write_mode = _resume_layout(target, resume)

    response = _open_stream_logged(file_url, timeout, start_byte)
    if response is None:
        return False

    total_size = start_byte + int(response.headers.get("content-length", 0))
    if total_size > max_bytes:
        file_automation_logger.error(
            "download_file rejected: content-length %d > %d", total_size, max_bytes
        )
        return False

    reporter: ProgressReporter | None = None
    token = None
    if progress_name:
        reporter, token = progress_registry.create(progress_name, total=total_size or None)
        if start_byte > 0:
            reporter.update(start_byte)

    try:
        written = _stream_to_disk(
            response,
            part_path,
            target,
            write_mode=write_mode,
            chunk_size=chunk_size,
            start_byte=start_byte,
            total_size=total_size,
            max_bytes=max_bytes,
            reporter=reporter,
            token=token,
        )
    except CancelledException:
        file_automation_logger.warning("download_file cancelled: %s", progress_name)
        if reporter is not None:
            reporter.finish(status="cancelled")
        return False
    except OSError as error:
        file_automation_logger.error("download_file write error: %r", error)
        if reporter is not None:
            reporter.finish(status="error")
        return False

    if written is None:
        if reporter is not None:
            reporter.finish(status="aborted")
        return False

    if resume and part_path != target:
        os.replace(part_path, target)

    if not _verify_and_finalize(target, expected_sha256, reporter):
        return False

    file_automation_logger.info("download_file: %s -> %s (%d bytes)", file_url, target, written)
    return True


class _NullBar:
    def update(self, _n: int) -> None: ...
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _progress(total: int, label: str):
    if total > 0:
        return tqdm(total=total, unit="B", unit_scale=True, desc=label)
    return _NullBar()
