"""Python SDK for :class:`~automation_file.server.http_server.HTTPActionServer`.

``HTTPActionClient(base_url, *, shared_secret=None)`` wraps a single
``requests.Session`` and exposes ``execute(actions)`` which POSTs the JSON
action list to ``<base_url>/actions``. The client is intentionally thin:
it handles auth header assembly, response-code checking, and error
translation, but makes no attempt to mirror ``ActionExecutor``'s API
surface — callers pass the same action-list shape they would pass to
``execute_action``.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import requests

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.remote.url_validator import validate_http_url

_DEFAULT_TIMEOUT = 30.0
_ACTIONS_PATH = "/actions"


class HTTPActionClientException(FileAutomationException):
    """Raised when the server rejects a request or the response is malformed."""


class HTTPActionClient:
    """Synchronous SDK for a running :class:`HTTPActionServer`."""

    def __init__(
        self,
        base_url: str,
        *,
        shared_secret: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        verify_loopback: bool = False,
    ) -> None:
        stripped = base_url.rstrip("/")
        if not stripped:
            raise HTTPActionClientException("base_url must be non-empty")
        if verify_loopback:
            validate_http_url(stripped)
        self._base_url = stripped
        self._shared_secret = shared_secret
        self._timeout = float(timeout)
        self._session = requests.Session()

    @property
    def base_url(self) -> str:
        return self._base_url

    def execute(self, actions: list | dict) -> Any:
        """POST ``actions`` to ``/actions`` and return the decoded JSON body."""
        if not isinstance(actions, (list, dict)):
            raise HTTPActionClientException(
                f"actions must be list or dict, got {type(actions).__name__}"
            )
        url = f"{self._base_url}{_ACTIONS_PATH}"
        headers = {"Content-Type": "application/json"}
        if self._shared_secret:
            headers["Authorization"] = f"Bearer {self._shared_secret}"
        try:
            response = self._session.post(
                url,
                json=actions,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=False,
            )
        except requests.RequestException as err:
            raise HTTPActionClientException(f"request to {url} failed: {err}") from err
        return _decode_response(response)

    def ping(self) -> bool:
        """Best-effort reachability probe — returns True if the server responds."""
        url = f"{self._base_url}{_ACTIONS_PATH}"
        try:
            response = self._session.request(
                "OPTIONS", url, timeout=min(self._timeout, 5.0), allow_redirects=False
            )
        except requests.RequestException:
            return False
        # The server only handles POST /actions; OPTIONS yields 501 which
        # still proves it's reachable. 401/403 also prove reachability.
        return response.status_code < 500 or response.status_code == 501

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> HTTPActionClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _decode_response(response: requests.Response) -> Any:
    status = response.status_code
    if status == 401:
        raise HTTPActionClientException("unauthorized: missing or invalid shared secret")
    if status == 403:
        body = _safe_body(response)
        raise HTTPActionClientException(f"forbidden: {body}")
    if status == 404:
        raise HTTPActionClientException("server does not expose /actions")
    if status >= 400:
        body = _safe_body(response)
        raise HTTPActionClientException(f"server returned HTTP {status}: {body}")
    try:
        return response.json()
    except ValueError as err:
        file_automation_logger.error("http_client: bad JSON response: %r", err)
        raise HTTPActionClientException(f"server returned invalid JSON: {err}") from err


def _safe_body(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(data, dict) and "error" in data:
        return str(data["error"])
    return str(data)[:200]
