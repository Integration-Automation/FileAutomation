"""Tests for TelegramSink / DiscordSink / TeamsSink / PagerDutySink."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from automation_file.notify import (
    DiscordSink,
    NotificationException,
    PagerDutySink,
    TeamsSink,
    TelegramSink,
)


class _FakeResp:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


def _loaded(post_call) -> dict:
    return json.loads(post_call.kwargs["data"].decode("utf-8"))


def test_telegram_requires_bot_token() -> None:
    with pytest.raises(NotificationException):
        TelegramSink("", chat_id="1")


def test_telegram_requires_chat_id() -> None:
    with pytest.raises(NotificationException):
        TelegramSink("token", chat_id="")


def test_telegram_posts_to_bot_endpoint() -> None:
    sink = TelegramSink("secret-token", chat_id="@channel")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(200)
        sink.send("subj", "body", "error")
    post.assert_called_once()
    args = post.call_args.args
    assert args[0] == "https://api.telegram.org/botsecret-token/sendMessage"
    payload = _loaded(post.call_args)
    assert payload["chat_id"] == "@channel"
    assert payload["text"].startswith("🚨 ")


def test_telegram_repr_hides_token() -> None:
    sink = TelegramSink("secret-token", chat_id="42")
    assert "secret-token" not in repr(sink)


def test_telegram_http_error_raises() -> None:
    sink = TelegramSink("t", chat_id="1")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(500)
        with pytest.raises(NotificationException, match="HTTP 500"):
            sink.send("x", "y")


def test_discord_sends_content_field() -> None:
    sink = DiscordSink("https://discord.com/api/webhooks/1/token")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(204)
        sink.send("alert", "details", "warning")
    payload = _loaded(post.call_args)
    assert "content" in payload
    assert payload["content"].startswith(":warning: **alert**")


def test_discord_trims_oversized_content() -> None:
    sink = DiscordSink("https://discord.com/api/webhooks/1/token")
    big = "x" * 3000
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(204)
        sink.send("subj", big, "info")
    payload = _loaded(post.call_args)
    assert len(payload["content"]) <= 1901


def test_teams_sends_message_card() -> None:
    sink = TeamsSink("https://outlook.office.com/webhook/abc")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(200)
        sink.send("subj", "body", "warning")
    payload = _loaded(post.call_args)
    assert payload["@type"] == "MessageCard"
    assert payload["title"] == "subj"
    assert payload["themeColor"] == "E67E22"


def test_pagerduty_requires_routing_key() -> None:
    with pytest.raises(NotificationException):
        PagerDutySink("")


def test_pagerduty_posts_event_payload() -> None:
    sink = PagerDutySink("rk-secret")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(202)
        sink.send("disk full", "/var is at 99%", "error")
    args = post.call_args.args
    assert args[0] == "https://events.pagerduty.com/v2/enqueue"
    payload = _loaded(post.call_args)
    assert payload["routing_key"] == "rk-secret"
    assert payload["event_action"] == "trigger"
    assert payload["payload"]["severity"] == "error"
    assert payload["payload"]["summary"] == "disk full"
    assert payload["payload"]["custom_details"]["body"] == "/var is at 99%"


def test_pagerduty_http_error_raises() -> None:
    sink = PagerDutySink("rk")
    with patch("automation_file.notify.sinks.requests.post") as post:
        post.return_value = _FakeResp(400)
        with pytest.raises(NotificationException, match="HTTP 400"):
            sink.send("x", "y")


def test_pagerduty_repr_hides_routing_key() -> None:
    sink = PagerDutySink("super-secret-routing-key")
    assert "super-secret-routing-key" not in repr(sink)


def test_new_sinks_surface_via_facade() -> None:
    import automation_file

    assert automation_file.DiscordSink is DiscordSink
    assert automation_file.TeamsSink is TeamsSink
    assert automation_file.TelegramSink is TelegramSink
    assert automation_file.PagerDutySink is PagerDutySink
