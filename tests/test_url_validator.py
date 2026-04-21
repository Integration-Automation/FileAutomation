"""Tests for automation_file.remote.url_validator."""

from __future__ import annotations

import pytest

from automation_file.exceptions import UrlValidationException
from automation_file.remote.url_validator import validate_http_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",  # NOSONAR: literal insecure URL required to verify rejection
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
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.1/",  # NOSONAR: literal private IP required to verify SSRF rejection
        "http://169.254.1.1/",  # NOSONAR: literal link-local IP required to verify SSRF rejection
        "http://[::1]/",  # NOSONAR: literal loopback IPv6 required to verify SSRF rejection
    ],
)
def test_reject_loopback_and_private_ip(url: str) -> None:
    with pytest.raises(UrlValidationException):
        validate_http_url(url)


def test_reject_unresolvable_host() -> None:
    url = "http://definitely-not-a-real-host-abc123.invalid/"  # NOSONAR: literal unresolvable URL required to verify rejection
    with pytest.raises(UrlValidationException):
        validate_http_url(url)
