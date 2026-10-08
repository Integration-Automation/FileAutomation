"""How an integration test module finds the service it runs against.

Each module reads ``FA_IT_*`` environment variables. Without them the module is
skipped, so the ordinary test run is unaffected. In CI ``FA_IT_REQUIRED`` is
set, and a missing variable is then an error: a job that skipped every test
would look green without having touched the service.
"""

from __future__ import annotations

import os
import uuid

import pytest

_REQUIRED = "FA_IT_REQUIRED"


def service_setting(name: str, service: str) -> str:
    """Return the variable ``name``; skip the calling module (or fail in CI) when it is unset."""
    value = os.environ.get(name, "")
    if value:
        return value
    message = f"set {name} to run against {service}"
    if os.environ.get(_REQUIRED):
        pytest.fail(f"{_REQUIRED} is set, but {name} is not: {message}", pytrace=False)
    pytest.skip(message, allow_module_level=True)


def optional_setting(name: str, default: str) -> str:
    """Return the variable ``name``, or ``default`` when it is unset or empty."""
    return os.environ.get(name, "") or default


def unique_name() -> str:
    """Return a name no other test run uses, for a bucket, a container or a directory."""
    return f"fa-it-{uuid.uuid4().hex[:16]}"
