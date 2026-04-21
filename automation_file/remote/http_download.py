"""SSRF-guarded HTTP downloader."""

from __future__ import annotations

import requests
from tqdm import tqdm

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
) -> requests.Response:
    response = requests.get(
        file_url,
        stream=True,
        timeout=timeout,
        allow_redirects=False,
    )
    response.raise_for_status()
    return response


def download_file(
    file_url: str,
    file_name: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = _MAX_RESPONSE_BYTES,
    progress_name: str | None = None,
) -> bool:
    """Download ``file_url`` to ``file_name`` with progress display.

    Validates the URL against SSRF rules, disables redirects, enforces a size
    cap, retries transient network errors up to three times, and uses default
    TLS verification. Pass ``progress_name`` to register the transfer with
    :data:`~automation_file.core.progress.progress_registry` so it can be
    polled or cancelled from the GUI. Returns True on success.
    """
    try:
        validate_http_url(file_url)
    except UrlValidationException as error:
        file_automation_logger.error("download_file rejected URL: %r", error)
        return False

    try:
        response = _open_stream(file_url, timeout)
    except RetryExhaustedException as error:
        file_automation_logger.error("download_file retries exhausted: %r", error)
        return False
    except requests.exceptions.HTTPError as error:
        file_automation_logger.error("download_file HTTP error: %r", error)
        return False
    except requests.exceptions.RequestException as error:
        file_automation_logger.error("download_file request error: %r", error)
        return False

    total_size = int(response.headers.get("content-length", 0))
    if total_size > max_bytes:
        file_automation_logger.error(
            "download_file rejected: content-length %d > %d",
            total_size,
            max_bytes,
        )
        return False

    reporter: ProgressReporter | None = None
    token = None
    if progress_name:
        reporter, token = progress_registry.create(progress_name, total=total_size or None)

    written = 0
    try:
        with open(file_name, "wb") as output, _progress(total_size, file_name) as progress:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if token is not None:
                    token.raise_if_cancelled()
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    file_automation_logger.error(
                        "download_file aborted: stream exceeded %d bytes",
                        max_bytes,
                    )
                    if reporter is not None:
                        reporter.finish(status="aborted")
                    return False
                output.write(chunk)
                progress.update(len(chunk))
                if reporter is not None:
                    reporter.update(len(chunk))
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

    if reporter is not None:
        reporter.finish(status="done")
    file_automation_logger.info("download_file: %s -> %s (%d bytes)", file_url, file_name, written)
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
