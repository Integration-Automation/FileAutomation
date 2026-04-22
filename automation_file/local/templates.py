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


def render_string(
    template: str,
    context: dict[str, Any],
    *,
    use_jinja: bool = True,
    autoescape: bool = True,
) -> str:
    """Render ``template`` against ``context`` and return the string result.

    ``autoescape=True`` (the default) HTML-escapes substituted values when the
    Jinja2 engine is used; pass ``autoescape=False`` only when the output is
    known to target a non-HTML format.
    """
    if use_jinja:
        rendered = _render_with_jinja(template, context, autoescape=autoescape)
        if rendered is not None:
            return rendered
    return _render_with_stdlib(template, context)


def render_file(
    template_path: str | os.PathLike[str],
    context: dict[str, Any],
    output_path: str | os.PathLike[str] | None = None,
    *,
    use_jinja: bool | None = None,
    autoescape: bool | None = None,
) -> str:
    """Read a template file, render it, optionally write the result.

    ``use_jinja=None`` auto-detects: ``.j2`` / ``.jinja`` / ``.jinja2`` suffixes
    opt in to Jinja2; other extensions use :class:`string.Template`.

    ``autoescape=None`` auto-detects based on the output path suffix — HTML /
    XML targets enable escaping, others disable it. Pass a bool to override.
    """
    src = Path(template_path)
    if not src.is_file():
        raise TemplateException(f"template not found: {src}")
    try:
        source = src.read_text(encoding="utf-8")
    except OSError as error:
        raise TemplateException(f"cannot read template {src}: {error}") from error
    jinja = _wants_jinja(src) if use_jinja is None else use_jinja
    escape = _wants_autoescape(output_path, src) if autoescape is None else autoescape
    rendered = render_string(source, context, use_jinja=jinja, autoescape=escape)
    if output_path is not None:
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rendered, encoding="utf-8")
    return rendered


_HTML_SUFFIXES = frozenset({".html", ".htm", ".xhtml", ".xml"})


def _wants_jinja(path: Path) -> bool:
    return path.suffix.lower() in {".j2", ".jinja", ".jinja2"}


def _wants_autoescape(
    output_path: str | os.PathLike[str] | None,
    template_path: Path,
) -> bool:
    target = Path(output_path) if output_path is not None else template_path
    suffix = target.suffix.lower()
    if suffix in {".j2", ".jinja", ".jinja2"}:
        suffix = target.with_suffix("").suffix.lower()
    return suffix in _HTML_SUFFIXES


def _render_with_jinja(
    template: str,
    context: dict[str, Any],
    *,
    autoescape: bool,
) -> str | None:
    try:
        from jinja2 import StrictUndefined
        from jinja2 import TemplateError as JinjaTemplateError
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        from markupsafe import Markup
    except ImportError:
        return None
    # ImmutableSandboxedEnvironment blocks access to Python internals
    # (__class__, __globals__, __mro__, mutation of passed collections, …) so
    # that a caller passing a user-supplied template cannot escape the sandbox
    # — the standard Jinja2 mitigation for server-side template injection.
    # autoescape=True is kept unconditional; callers opt out by pre-wrapping
    # their string values in markupsafe.Markup, which Jinja renders verbatim.
    env = ImmutableSandboxedEnvironment(autoescape=True, undefined=StrictUndefined)
    if not autoescape:
        context = {
            key: Markup(value) if isinstance(value, str) else value
            for key, value in context.items()
        }
    try:
        return env.from_string(template).render(**context)
    except JinjaTemplateError as error:
        raise TemplateException(f"jinja render failed: {error}") from error


def _render_with_stdlib(template: str, context: dict[str, Any]) -> str:
    try:
        return string.Template(template).substitute(context)
    except (KeyError, ValueError) as error:
        raise TemplateException(f"template render failed: {error}") from error
