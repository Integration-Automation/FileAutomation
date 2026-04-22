"""Template rendering for file content generation.

Supports Jinja2 when installed (richer control flow, filters) and falls back
to :class:`string.Template` for simple ``$var`` substitution. Renders can
target an output path or return the resulting string.
"""

from __future__ import annotations

import os
import string
from pathlib import Path
from typing import Any

from automation_file.exceptions import TemplateException


def render_string(template: str, context: dict[str, Any], *, use_jinja: bool = True) -> str:
    """Render ``template`` against ``context`` and return the string result."""
    if use_jinja:
        rendered = _render_with_jinja(template, context)
        if rendered is not None:
            return rendered
    return _render_with_stdlib(template, context)


def render_file(
    template_path: str | os.PathLike[str],
    context: dict[str, Any],
    output_path: str | os.PathLike[str] | None = None,
    *,
    use_jinja: bool | None = None,
) -> str:
    """Read a template file, render it, optionally write the result.

    ``use_jinja=None`` auto-detects: ``.j2`` / ``.jinja`` / ``.jinja2`` suffixes
    opt in to Jinja2; other extensions use :class:`string.Template`.
    """
    src = Path(template_path)
    if not src.is_file():
        raise TemplateException(f"template not found: {src}")
    try:
        source = src.read_text(encoding="utf-8")
    except OSError as error:
        raise TemplateException(f"cannot read template {src}: {error}") from error
    jinja = _wants_jinja(src) if use_jinja is None else use_jinja
    rendered = render_string(source, context, use_jinja=jinja)
    if output_path is not None:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rendered, encoding="utf-8")
    return rendered


def _wants_jinja(path: Path) -> bool:
    return path.suffix.lower() in {".j2", ".jinja", ".jinja2"}


def _render_with_jinja(template: str, context: dict[str, Any]) -> str | None:
    try:
        from jinja2 import Environment, StrictUndefined
        from jinja2 import TemplateError as JinjaTemplateError
    except ImportError:
        return None
    env = Environment(autoescape=False, undefined=StrictUndefined)
    try:
        return env.from_string(template).render(**context)
    except JinjaTemplateError as error:
        raise TemplateException(f"jinja render failed: {error}") from error


def _render_with_stdlib(template: str, context: dict[str, Any]) -> str:
    try:
        return string.Template(template).substitute(context)
    except (KeyError, ValueError) as error:
        raise TemplateException(f"template render failed: {error}") from error
