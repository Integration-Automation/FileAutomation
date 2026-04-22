"""Tests for automation_file.notify."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from automation_file.exceptions import UrlValidationException
from automation_file.notify import (
    EmailSink,
    NotificationException,
    NotificationManager,
    NotificationSink,
    SlackSink,
    WebhookSink,
    notification_manager,
)


@pytest.fixture(autouse=True)
def _reset_manager() -> Iterator[None]:
    notification_manager.unregister_all()
    yield
    notification_manager.unregister_all()


class _FakeResp:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


def test_webhook_posts_json() -> None:
    sink = WebhookSink("https://example.com/hook", name="hook-a")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(200)
        sink.send("hello", "body here", "info")
    post.assert_called_once()
    kwargs = post.call_args.kwargs
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == pytest.approx(10.0)
    import json

    body = json.loads(kwargs["data"].decode("utf-8"))
    assert body == {"subject": "hello", "body": "body here", "level": "info"}


def test_webhook_rejects_loopback_url() -> None:
    with pytest.raises(UrlValidationException):
        WebhookSink("http://127.0.0.1/hook")


def test_webhook_rejects_bad_level() -> None:
    sink = WebhookSink("https://example.com/hook")
    with pytest.raises(NotificationException, match="level"):
        sink.send("x", "y", "debug")


def test_webhook_http_error_raises() -> None:
    sink = WebhookSink("https://example.com/hook")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(500)
        with pytest.raises(NotificationException, match="HTTP 500"):
            sink.send("x", "y")


def test_slack_prepends_level_prefix() -> None:
    sink = SlackSink("https://hooks.slack.com/services/T/B/X")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(200)
        sink.send("alert", "disk full", "error")
    kwargs = post.call_args.kwargs
    import json

    body = json.loads(kwargs["data"].decode("utf-8"))
    assert body["text"].startswith(":rotating_light: *alert*\n")


def test_slack_repr_never_reveals_url() -> None:
    sink = SlackSink("https://hooks.slack.com/services/T/B/SECRET-TOKEN")
    assert "SECRET-TOKEN" not in repr(sink)


def test_email_send_uses_smtp_context_manager() -> None:
    sink = EmailSink(
        host="smtp.example.com",
        port=587,
        sender="me@example.com",
        recipients=["you@example.com"],
        username="me",
        password="pw",  # NOSONAR test fixture — not a real credential
        use_tls=True,
    )
    with patch("automation_file.notify.sinks.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        sink.send("subj", "body", "warning")
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("me", "pw")
    smtp.send_message.assert_called_once()
    message = smtp.send_message.call_args[0][0]
    assert message["Subject"] == "[WARNING] subj"


def test_email_repr_hides_password() -> None:
    sink = EmailSink(
        host="smtp.example.com",
        port=587,
        sender="me@example.com",
        recipients=["you@example.com"],
        username="me",
        password="secret-pw",  # NOSONAR test fixture — repr-hiding assertion
    )
    assert "secret-pw" not in repr(sink)


def test_email_requires_recipients() -> None:
    with pytest.raises(NotificationException, match="recipient"):
        EmailSink(
            host="smtp.example.com",
            port=25,
            sender="me@example.com",
            recipients=[],
        )


def test_manager_fans_out_to_all_sinks() -> None:
    calls: list[tuple[str, str, str]] = []

    class _Recorder(NotificationSink):
        name = "rec"

        def send(self, subject: str, body: str, level: str = "info") -> None:
            calls.append((subject, body, level))

    manager = NotificationManager(dedup_seconds=0.0)
    manager.register(_Recorder())
    result = manager.notify("s", "b", "info")
    assert result == {"rec": "sent"}
    assert calls == [("s", "b", "info")]


def test_manager_dedups_identical_messages() -> None:
    class _Recorder(NotificationSink):
        name = "rec"
        count = 0

        def send(self, subject: str, body: str, level: str = "info") -> None:
            _Recorder.count += 1

    manager = NotificationManager(dedup_seconds=60.0)
    manager.register(_Recorder())
    manager.notify("s", "b", "info")
    result = manager.notify("s", "b", "info")
    assert result == {"rec": "dedup"}
    assert _Recorder.count == 1


def test_manager_distinct_messages_both_sent() -> None:
    class _Recorder(NotificationSink):
        name = "rec"
        count = 0

        def send(self, subject: str, body: str, level: str = "info") -> None:
            _Recorder.count += 1

    manager = NotificationManager(dedup_seconds=60.0)
    manager.register(_Recorder())
    manager.notify("s1", "b", "info")
    manager.notify("s2", "b", "info")
    assert _Recorder.count == 2


def test_manager_isolates_failing_sink() -> None:
    class _Boom(NotificationSink):
        name = "boom"

        def send(self, subject: str, body: str, level: str = "info") -> None:
            raise NotificationException("always broken")

    class _Good(NotificationSink):
        name = "good"
        sent = 0

        def send(self, subject: str, body: str, level: str = "info") -> None:
            _Good.sent += 1

    manager = NotificationManager(dedup_seconds=0.0)
    manager.register(_Boom())
    manager.register(_Good())
    result = manager.notify("s", "b", "info")
    assert result["good"] == "sent"
    assert "always broken" in result["boom"]
    assert _Good.sent == 1


def test_manager_unregister() -> None:
    class _Recorder(NotificationSink):
        name = "rec"

        def send(self, subject: str, body: str, level: str = "info") -> None:
            """No-op sink — the test only checks manager register/unregister."""

    manager = NotificationManager(dedup_seconds=0.0)
    manager.register(_Recorder())
    assert manager.unregister("rec") is True
    assert manager.unregister("rec") is False


def test_notify_send_uses_shared_manager() -> None:
    from automation_file import notify_send

    class _Recorder(NotificationSink):
        name = "rec"
        last: tuple[str, str, str] | None = None

        def send(self, subject: str, body: str, level: str = "info") -> None:
            _Recorder.last = (subject, body, level)

    notification_manager.register(_Recorder())
    notify_send("subject", "body", "error")
    assert _Recorder.last == ("subject", "body", "error")


def test_notify_actions_registered() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    assert "FA_notify_send" in registry
    assert "FA_notify_list" in registry


def test_notify_on_failure_no_op_without_sinks() -> None:
    from automation_file.notify.manager import notify_on_failure

    # No sinks registered — must not raise.
    notify_on_failure("ctx", RuntimeError("boom"))


def test_notify_on_failure_sends_error_level() -> None:
    from automation_file.notify.manager import notify_on_failure

    captured: list[tuple[str, str, str]] = []

    class _Recorder(NotificationSink):
        name = "rec"

        def send(self, subject: str, body: str, level: str = "info") -> None:
            captured.append((subject, body, level))

    notification_manager.register(_Recorder())
    notify_on_failure("scheduler[nightly]", RuntimeError("disk full"))
    assert len(captured) == 1
    subject, body, level = captured[0]
    assert level == "error"
    assert "scheduler[nightly]" in subject
    assert "disk full" in body


def test_long_body_is_truncated() -> None:
    sink = WebhookSink("https://example.com/hook")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(200)
        sink.send("s", "x" * (65 * 1024), "info")
    kwargs = post.call_args.kwargs
    import json

    body = json.loads(kwargs["data"].decode("utf-8"))
    assert body["body"].endswith("…[truncated]")


def test_manager_list_describes_sinks() -> None:
    manager = NotificationManager(dedup_seconds=0.0)
    manager.register(WebhookSink("https://example.com/hook", name="hook-a"))
    manager.register(
        EmailSink(
            host="smtp.example.com",
            port=587,
            sender="me@example.com",
            recipients=["a@example.com"],
        )
    )
    descriptions = manager.list()
    assert {d["name"] for d in descriptions} == {"hook-a", "email"}
    webhook_desc = next(d for d in descriptions if d["name"] == "hook-a")
    assert webhook_desc["type"] == "WebhookSink"
    assert webhook_desc["url_host"] == "example.com"
