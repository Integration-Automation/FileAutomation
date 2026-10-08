"""The application layer keeps secrets out of what it returns, and reads form text."""

# The nosec / nosemgrep markers below sit on made-up values and on digests that are the thing
# under test; none is a credential or a security use of a hash.
# pylint: disable=line-too-long  # a marker has to follow the value it is about

# pylint: disable=keyword-arg-before-vararg  # a stand-in keeps the real signature
# pylint: disable=unused-argument  # a fixture is requested for its effect; a stand-in keeps the real signature

from __future__ import annotations

import pytest

from automation_file.app import (
    MASK,
    AppException,
    describe_action,
    format_argument_value,
    mask_secrets,
    mask_text,
    mask_url,
    parse_argument_text,
    parse_json_text,
)
from automation_file.app.masking import is_secret_name, is_url_name
from automation_file.exceptions import FileAutomationException


@pytest.mark.parametrize(
    "name",
    [
        "password",
        "PASSWORD",
        "smtp_password",
        "token",
        "access_token",
        "token_path",
        "api_key",
        "X-Api-Key",
        "Authorization",
        "client_secret",
        "connection_string",
        "aws_secret_access_key",
        "private_key",
    ],
)
def test_names_that_hold_a_secret(name: str) -> None:
    assert is_secret_name(name) is True


@pytest.mark.parametrize(
    "name", ["name", "uri", "target", "idempotency_key", "status", "task", 3, None]
)
def test_names_that_do_not_hold_a_secret(name: object) -> None:
    assert is_secret_name(name) is False


def test_url_names_are_told_from_storage_uris() -> None:
    assert is_url_name("url") is True
    assert is_url_name("webhook_url") is True
    assert is_url_name("webhook") is True
    assert is_url_name("uri") is False
    assert is_url_name("curl_options") is False
    assert is_url_name(None) is False


def test_a_secret_value_is_replaced_whatever_its_type() -> None:
    masked = mask_secrets(
        {"password": "hunter2", "token": {"value": "abc"}, "api_key": 12, "name": "ops"}  # nosec B105
    )
    assert masked == {"password": MASK, "token": MASK, "api_key": MASK, "name": "ops"}


def test_an_empty_secret_stays_empty_so_a_view_can_tell_it_is_unset() -> None:
    assert mask_secrets({"password": "", "token": None}) == {"password": "", "token": None}  # nosec B105


def test_a_webhook_url_keeps_only_its_host() -> None:
    masked = mask_secrets({"webhook_url": "https://hooks.example.com/services/T0/B0/s3cr3t"})
    assert masked == {"webhook_url": f"https://hooks.example.com/{MASK}"}
    assert "s3cr3t" not in str(masked)


def test_a_url_field_without_an_http_url_is_masked_whole() -> None:
    assert mask_url("not a url") == MASK
    assert mask_secrets({"url": "token-only"}) == {"url": MASK}


def test_nested_values_are_walked_and_tuples_become_lists() -> None:
    masked = mask_secrets({"sinks": ({"name": "a", "password": "x"}, {"name": "b"})})  # nosec B105
    assert masked == {"sinks": [{"name": "a", "password": MASK}, {"name": "b"}]}


def test_credentials_inside_ordinary_text_are_removed() -> None:
    text = mask_text("fetch https://user:pw@example.com/x with Bearer abc.def-123")
    assert "user:pw" not in text
    assert "abc.def-123" not in text
    assert f"https://{MASK}@example.com/x" in text
    assert f"Bearer {MASK}" in text


def test_a_storage_uri_is_left_alone() -> None:
    record = {"resource": "s3://reports/2026/q1.csv", "uri": "local:///C:/data/a.csv"}
    assert mask_secrets(record) == record


def test_the_input_is_not_changed() -> None:
    original = {"password": "hunter2", "items": [{"token": "t"}]}  # nosec B105
    mask_secrets(original)
    assert original == {"password": "hunter2", "items": [{"token": "t"}]}  # nosec B105


def test_values_that_are_not_containers_pass_through() -> None:
    assert mask_secrets(12) == 12
    assert mask_secrets(None) is None


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("12", 12),
        ("1.5", 1.5),
        ("true", True),
        ("null", None),
        ('"12"', "12"),
        ('["a", 1]', ["a", 1]),
        ('{"a": 1}', {"a": 1}),
        ("s3://bucket/key", "s3://bucket/key"),
        ("${params.date}", "${params.date}"),
        ("  padded  ", "padded"),
        ("NaN", "NaN"),
        ("", ""),
    ],
)
def test_form_text_is_json_when_it_parses_and_text_otherwise(text: str, value: object) -> None:
    assert parse_argument_text(text) == value


@pytest.mark.parametrize(
    "value",
    [12, 1.5, True, None, "12", "true", "plain text", "s3://b/k", "", " padded ", ["a"], {"a": 1}],
)
def test_a_formatted_value_reads_back_unchanged(value: object) -> None:
    assert parse_argument_text(format_argument_value(value)) == value


def test_a_plain_string_is_shown_without_quotes() -> None:
    assert format_argument_value("s3://bucket/key") == "s3://bucket/key"
    assert format_argument_value("12") == '"12"'


def test_a_value_json_cannot_hold_is_shown_as_its_repr() -> None:
    assert format_argument_value(set) == repr(set)


def test_json_text_of_a_form() -> None:
    assert parse_json_text('{"a": 1}', "params") == {"a": 1}
    assert parse_json_text("   ", "params", empty={}) == {}
    with pytest.raises(AppException, match="params is not valid JSON") as caught:
        parse_json_text("{oops", "params")
    assert "line 1" in str(caught.value)
    assert isinstance(caught.value, FileAutomationException)
    with pytest.raises(AppException, match="not valid JSON"):
        parse_json_text("NaN", "params")


def _sample(source: str, target: str, overwrite: bool = True, *extra: str, **options: int) -> None:
    """Copy something.

    More text.
    """


def test_an_action_is_described_for_a_form() -> None:
    info = describe_action("FA_sample", _sample)
    assert info.known is True
    assert info.signature == "FA_sample(source, target, overwrite=True, *extra, **options)"
    assert info.summary == "Copy something."
    assert [(entry.name, entry.required, entry.default) for entry in info.parameters] == [
        ("source", True, ""),
        ("target", True, ""),
        ("overwrite", False, "true"),
    ]
    assert info.accepts_extra is True
    assert info.to_dict()["parameters"][0] == {"name": "source", "required": True, "default": ""}


def test_an_unknown_action_and_a_builtin_are_described_without_parameters() -> None:
    unknown = describe_action("FA_missing", None)
    assert (unknown.known, unknown.parameters, unknown.signature) == (False, (), "")
    builtin = describe_action("FA_dict", dict)
    assert builtin.known is True
