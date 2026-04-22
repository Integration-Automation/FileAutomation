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
_JSON_HEADERS: dict[str, str] = {"Content-Type": "application/json"}


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
        headers = dict(_JSON_HEADERS)
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
                headers=_JSON_HEADERS,
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


class TelegramSink(NotificationSink):
    """Telegram Bot API sink.

    ``bot_token`` is a secret — it's combined into the request URL and never
    logged. ``chat_id`` identifies the target channel or user.
    """

    _LEVEL_PREFIX: ClassVar[dict[str, str]] = {
        "info": "",
        "warning": "⚠️ ",
        "error": "🚨 ",
    }
    _API_HOST: ClassVar[str] = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: str,
        chat_id: str | int,
        *,
        name: str = "telegram",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not bot_token:
            raise NotificationException("telegram sink requires a bot_token")
        if chat_id in (None, ""):
            raise NotificationException("telegram sink requires a chat_id")
        self._bot_token = bot_token
        self.chat_id = chat_id
        self.name = name
        self.timeout = timeout
        self._url = f"{self._API_HOST}/bot{bot_token}/sendMessage"
        validate_http_url(self._url)

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self._check_level(level)
        prefix = self._LEVEL_PREFIX[level]
        text = f"{prefix}{subject}\n{self._truncate(body)}"
        payload = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        try:
            response = requests.post(
                self._url,
                data=json.dumps(payload).encode("utf-8"),
                headers=_JSON_HEADERS,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as err:
            raise NotificationException(f"telegram sink {self.name!r} post failed: {err}") from err
        if response.status_code >= 400:
            raise NotificationException(
                f"telegram sink {self.name!r} returned HTTP {response.status_code}"
            )

    def __repr__(self) -> str:
        return f"TelegramSink(name={self.name!r}, chat_id={self.chat_id!r})"


class DiscordSink(NotificationSink):
    """Discord incoming-webhook sink — POSTs ``{content}`` to the webhook URL."""

    _LEVEL_PREFIX: ClassVar[dict[str, str]] = {
        "info": "",
        "warning": ":warning: ",
        "error": ":rotating_light: ",
    }
    # Discord caps message content at 2000 characters.
    _MAX_CONTENT: ClassVar[int] = 1900

    def __init__(
        self,
        webhook_url: str,
        *,
        name: str = "discord",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        validate_http_url(webhook_url)
        self._url = webhook_url
        self.name = name
        self.timeout = timeout

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self._check_level(level)
        prefix = self._LEVEL_PREFIX[level]
        content = f"{prefix}**{subject}**\n{self._truncate(body)}"
        if len(content) > self._MAX_CONTENT:
            content = content[: self._MAX_CONTENT] + "…"
        try:
            response = requests.post(
                self._url,
                data=json.dumps({"content": content}).encode("utf-8"),
                headers=_JSON_HEADERS,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as err:
            raise NotificationException(f"discord sink {self.name!r} post failed: {err}") from err
        if response.status_code >= 400:
            raise NotificationException(
                f"discord sink {self.name!r} returned HTTP {response.status_code}"
            )


class TeamsSink(NotificationSink):
    """Microsoft Teams incoming-webhook sink using the legacy MessageCard schema."""

    _LEVEL_COLOR: ClassVar[dict[str, str]] = {
        "info": "2E86DE",
        "warning": "E67E22",
        "error": "C0392B",
    }

    def __init__(
        self,
        webhook_url: str,
        *,
        name: str = "teams",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        validate_http_url(webhook_url)
        self._url = webhook_url
        self.name = name
        self.timeout = timeout

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self._check_level(level)
        payload = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": subject,
            "themeColor": self._LEVEL_COLOR[level],
            "title": subject,
            "text": self._truncate(body),
        }
        try:
            response = requests.post(
                self._url,
                data=json.dumps(payload).encode("utf-8"),
                headers=_JSON_HEADERS,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as err:
            raise NotificationException(f"teams sink {self.name!r} post failed: {err}") from err
        if response.status_code >= 400:
            raise NotificationException(
                f"teams sink {self.name!r} returned HTTP {response.status_code}"
            )


class PagerDutySink(NotificationSink):
    """PagerDuty Events API v2 sink.

    ``routing_key`` is the integration key for a PagerDuty service and is
    treated as a secret. Each ``send`` enqueues a ``trigger`` event unless
    the level is explicitly ``info``, in which case it sends ``acknowledge``
    semantics via ``event_action='trigger'`` + ``severity='info'``.
    """

    _ENQUEUE_URL: ClassVar[str] = "https://events.pagerduty.com/v2/enqueue"
    _LEVEL_SEVERITY: ClassVar[dict[str, str]] = {
        "info": "info",
        "warning": "warning",
        "error": "error",
    }

    def __init__(
        self,
        routing_key: str,
        *,
        source: str = "automation_file",
        name: str = "pagerduty",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not routing_key:
            raise NotificationException("pagerduty sink requires a routing_key")
        self._routing_key = routing_key
        self.source = source
        self.name = name
        self.timeout = timeout
        validate_http_url(self._ENQUEUE_URL)

    def send(self, subject: str, body: str, level: str = "info") -> None:
        self._check_level(level)
        payload = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": subject,
                "source": self.source,
                "severity": self._LEVEL_SEVERITY[level],
                "custom_details": {"body": self._truncate(body)},
            },
        }
        try:
            response = requests.post(
                self._ENQUEUE_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers=_JSON_HEADERS,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as err:
            raise NotificationException(f"pagerduty sink {self.name!r} post failed: {err}") from err
        if response.status_code >= 400:
            raise NotificationException(
                f"pagerduty sink {self.name!r} returned HTTP {response.status_code}"
            )

    def __repr__(self) -> str:
        return f"PagerDutySink(name={self.name!r}, source={self.source!r})"


def _describe(sink: NotificationSink) -> dict[str, Any]:
    info: dict[str, Any] = {"name": sink.name, "type": type(sink).__name__}
    if isinstance(sink, WebhookSink):
        info["url_host"] = _host_of(sink.url)
    elif isinstance(sink, EmailSink):
        info["host"] = sink.host
        info["port"] = sink.port
        info["recipients"] = sink.recipients
    elif isinstance(sink, TelegramSink):
        info["chat_id"] = sink.chat_id
    elif isinstance(sink, PagerDutySink):
        info["source"] = sink.source
    return info


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""
