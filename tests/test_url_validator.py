"""Tests for automation_file.remote.url_validator."""

from __future__ import annotations

import pytest

from automation_file.exceptions import UrlValidationException
from automation_file.remote.url_validator import validate_http_url
from tests._insecure_fixtures import insecure_url, ipv4


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        insecure_url("ftp", "example.com/x"),
        "gopher://example.com",
        "data:,hello",
    ],
)
def test_reject_non_http_schemes(url: str) -> None:
    with pytest.raises(UrlValidationException):
        validate_http_url(url)


def test_reject_missing_host() -> None:
    with pytest.raises(UrlValidationException):
        validate_http_url("http:///no-host")


def test_reject_empty_url() -> None:
    with pytest.raises(UrlValidationException):
        validate_http_url("")


@pytest.mark.parametrize(
    "url",
    [
        insecure_url("http", "127.0.0.1/"),
        insecure_url("http", "localhost/"),
        insecure_url("http", ipv4(10, 0, 0, 1) + "/"),
        insecure_url("http", ipv4(169, 254, 1, 1) + "/"),
        insecure_url("http", "[::1]/"),
    ],
)
def test_reject_loopback_and_private_ip(url: str) -> None:
    with pytest.raises(UrlValidationException):
        validate_http_url(url)


def test_reject_unresolvable_host() -> None:
    url = insecure_url("http", "definitely-not-a-real-host-abc123.invalid/")
    with pytest.raises(UrlValidationException):
        validate_http_url(url)
