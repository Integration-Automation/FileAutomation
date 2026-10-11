"""The deprecation helpers: the wording, the warning category, and where the warning points."""

from __future__ import annotations

import logging
import warnings

import pytest

from automation_file.core.deprecation import deprecated, deprecation_message, warn_deprecated
from automation_file.logging_config import file_automation_logger


def test_message_names_the_versions_and_the_replacement() -> None:
    assert (
        deprecation_message("old()", since="1.1", removal="2.0", replacement="new()")
        == "old() is deprecated since 1.1 and will be removed in 2.0; use new() instead"
    )
    assert (
        deprecation_message("old()", since="1.1", removal="2.0", replacement=None)
        == "old() is deprecated since 1.1 and will be removed in 2.0"
    )


def test_a_deprecated_function_warns_and_still_works() -> None:
    @deprecated(since="1.1", removal="2.0", replacement="add_many")
    def add(left: int, right: int = 1) -> int:
        """Add two numbers."""
        return left + right

    with pytest.warns(DeprecationWarning, match="add is deprecated since 1.1") as caught:
        assert add(2, right=3) == 5
    assert caught[0].filename == __file__
    assert "use add_many instead" in str(caught[0].message)
    assert add.__name__ == "add"
    assert add.__doc__ == "Add two numbers."
    assert "removed in 2.0" in add.__deprecated__  # type: ignore[attr-defined]


def test_a_deprecated_method_warns_at_the_call_site() -> None:
    class Thing:
        @deprecated(since="1.2", removal="2.0")
        def old(self) -> str:
            return "ok"

    with pytest.warns(DeprecationWarning) as caught:
        assert Thing().old() == "ok"
    assert caught[0].filename == __file__
    assert "Thing.old is deprecated since 1.2" in str(caught[0].message)


def test_warn_deprecated_points_at_the_caller_of_the_deprecated_code() -> None:
    def library_function() -> None:
        warn_deprecated("the 'manager=' argument", since="1.1", removal="2.0")

    with pytest.warns(DeprecationWarning, match="the 'manager=' argument") as caught:
        library_function()
    assert caught[0].filename == __file__


def test_nothing_warns_until_the_function_is_called() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")

        @deprecated(since="1.1", removal="2.0")
        def unused() -> None:
            return None

    assert callable(unused)


def test_a_message_is_logged_once_per_process(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=file_automation_logger.name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        for _ in range(3):
            warn_deprecated("logged_once()", since="1.4", removal="2.0", replacement="newer()")
    logged = [record.getMessage() for record in caplog.records if "logged_once()" in record.message]
    assert logged == [
        "logged_once() is deprecated since 1.4 and will be removed in 2.0; use newer() instead"
    ]
