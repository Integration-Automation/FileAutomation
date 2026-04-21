"""Concrete notification sinks.

Every sink inherits :class:`NotificationSink` and implements ``send``.
The sinks themselves do no deduplication — that lives in
:class:`~automation_file.notify.manager.NotificationManager` — so each
sink can be used standalone from a caller that has already handled
policy elsewhere.
"""

from __future__ import annotations

import json
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any, ClassVar

import requests

from automation_file.exceptions import FileAutomationException
from automation_file.remote.url_validator import validate_http_url

LEVELS = frozenset({"info", "warning", "error"})
_DEFAULT_TIMEOUT = 10.0
_MAX_BODY_BYTES = 64 * 1024


class NotificationException(FileAutomationException):
    """Raised for misconfigured or failing notification sinks."""


class NotificationSink(ABC):
    """Contract for a single delivery channel."""

    name: str

    @abstractmethod
    def send(self, subject: str, body: str, level: str = "info") -> None:
        """Deliver one message. Raise :class:`NotificationException` on failure."""

    @staticmethod
    def _check_level(level: str) -> str:
        if level not in LEVELS:
            raise NotificationException(f"level must be one of {sorted(LEVELS)}, got {level!r}")
        return level

    @staticmethod
    def _truncate(body: str) -> str:
        encoded = body.encode("utf-8", errors="replace")
        if len(encoded) <= _MAX_BODY_BYTES:
            return body
        return encoded[:_MAX_BODY_BYTES].decode("utf-8", errors="replace") + "…[truncated]"


class WebhookSink(NotificationSink):
    """Generic JSON webhook sink — POSTs ``{subject, body, level}`` to ``url``."""

    def __init__(
        self,
        url: str,
        *,
        name: str = "webhook",
        timeout: float = _DEFAULT_TIMEOUT,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        validate_http_url(url)
        self.url = url
        self.name = name
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self._check_level(level)
        payload = {"subject": subject, "body": self._truncate(body), "level": level}
        headers = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)
        try:
            response = requests.post(
                self.url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as err:
            raise NotificationException(f"webhook {self.name!r} post failed: {err}") from err
        if response.status_code >= 400:
            raise NotificationException(
                f"webhook {self.name!r} returned HTTP {response.status_code}"
            )


class SlackSink(NotificationSink):
    """Slack incoming-webhook sink.

    ``webhook_url`` is the full ``https://hooks.slack.com/services/...`` URL
    and is treated as a secret — it is not logged. The level controls a
    plain-text prefix (:warning:, :rotating_light:) prepended to the body.
    """

    _LEVEL_PREFIX: ClassVar[dict[str, str]] = {
        "info": "",
        "warning": ":warning: ",
        "error": ":rotating_light: ",
    }

    def __init__(
        self,
        webhook_url: str,
        *,
        name: str = "slack",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        validate_http_url(webhook_url)
        self._url = webhook_url
        self.name = name
        self.timeout = timeout

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self._check_level(level)
        prefix = self._LEVEL_PREFIX[level]
        text = f"{prefix}*{subject}*\n{self._truncate(body)}"
        payload = {"text": text}
        try:
            response = requests.post(
                self._url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as err:
            raise NotificationException(f"slack sink {self.name!r} post failed: {err}") from err
        if response.status_code >= 400:
            raise NotificationException(
                f"slack sink {self.name!r} returned HTTP {response.status_code}"
            )


class EmailSink(NotificationSink):
    """SMTP sink.

    Credentials never appear in the sink's ``repr``; the password is only
    held as an instance attribute and used once per ``send``.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        recipients: list[str],
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        name: str = "email",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not recipients:
            raise NotificationException("email sink requires at least one recipient")
        self.host = host
        self.port = int(port)
        self.sender = sender
        self.recipients = list(recipients)
        self._username = username
        self._password = password
        self.use_tls = bool(use_tls)
        self.name = name
        self.timeout = timeout

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self._check_level(level)
        message = EmailMessage()
        message["Subject"] = f"[{level.upper()}] {subject}"
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(self._truncate(body))
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as client:
                if self.use_tls:
                    client.starttls()
                if self._username and self._password:
                    client.login(self._username, self._password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as err:
            raise NotificationException(f"email sink {self.name!r} send failed: {err}") from err

    def __repr__(self) -> str:
        return (
            f"EmailSink(name={self.name!r}, host={self.host!r}, port={self.port}, "
            f"sender={self.sender!r}, recipients={self.recipients!r}, "
            f"use_tls={self.use_tls})"
        )


def _describe(sink: NotificationSink) -> dict[str, Any]:
    info: dict[str, Any] = {"name": sink.name, "type": type(sink).__name__}
    if isinstance(sink, WebhookSink):
        info["url_host"] = _host_of(sink.url)
    elif isinstance(sink, EmailSink):
        info["host"] = sink.host
        info["port"] = sink.port
        info["recipients"] = sink.recipients
    return info


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""
