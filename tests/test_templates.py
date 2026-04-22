"""Tests for automation_file.local.templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.exceptions import TemplateException
from automation_file.local.templates import render_file, render_string


def _has_jinja() -> bool:
    try:
        import jinja2  # noqa: F401
    except ImportError:
        return False
    return True


def test_render_string_stdlib_substitution() -> None:
    assert render_string("hello $name", {"name": "world"}, use_jinja=False) == "hello world"


def test_render_string_missing_key_raises() -> None:
    with pytest.raises(TemplateException):
        render_string("$missing", {}, use_jinja=False)


@pytest.mark.skipif(not _has_jinja(), reason="jinja2 not installed")
def test_render_string_jinja_conditional() -> None:
    template = "{% if flag %}ok{% else %}no{% endif %}"
    assert render_string(template, {"flag": True}) == "ok"
    assert render_string(template, {"flag": False}) == "no"


@pytest.mark.skipif(not _has_jinja(), reason="jinja2 not installed")
def test_render_string_jinja_undefined_strict() -> None:
    with pytest.raises(TemplateException):
        render_string("{{ missing }}", {})


def test_render_file_writes_output(tmp_path: Path) -> None:
    tmpl = tmp_path / "tmpl.txt"
    tmpl.write_text("value=$x", encoding="utf-8")
    out = tmp_path / "out" / "result.txt"
    render_file(tmpl, {"x": "42"}, out, use_jinja=False)
    assert out.read_text(encoding="utf-8") == "value=42"


def test_render_file_returns_rendered(tmp_path: Path) -> None:
    tmpl = tmp_path / "a.txt"
    tmpl.write_text("$greeting", encoding="utf-8")
    assert render_file(tmpl, {"greeting": "hi"}, use_jinja=False) == "hi"


def test_render_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(TemplateException):
        render_file(tmp_path / "nope.txt", {})


@pytest.mark.skipif(not _has_jinja(), reason="jinja2 not installed")
def test_render_file_auto_detects_jinja_by_suffix(tmp_path: Path) -> None:
    tmpl = tmp_path / "page.j2"
    tmpl.write_text("{% for v in values %}{{ v }};{% endfor %}", encoding="utf-8")
    assert render_file(tmpl, {"values": [1, 2, 3]}) == "1;2;3;"
