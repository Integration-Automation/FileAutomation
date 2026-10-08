"""``${params.<name>}`` and ``${tasks.<id>.result}`` in action arguments.

There is no expression language and nothing is evaluated: a placeholder names
one run parameter or the result of one upstream task.

* ``${params.<name>}`` may stand anywhere in a string and is replaced by the
  parameter as text. A string that is exactly one such placeholder becomes the
  parameter itself, so a number stays a number.
* ``${tasks.<id>.result}`` must be the whole string and is replaced by the result
  object of that upstream task (``None`` when the task did not succeed).

Any other ``${...}`` text is left alone.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from automation_file.pipeline.errors import PipelineException

#: What a task ID or a parameter name looks like (a regular expression, also used by the schema).
NAME_PATTERN = r"^[^\s.${}]+$"
NAME_RULE = "expected a non-empty string without whitespace, '.', '$', '{' or '}'"
_NAME = re.compile(NAME_PATTERN)
_PLACEHOLDER = re.compile(r"\$\{(params|tasks)\.([^}]*)\}")
_TASKS = "tasks"
_RESULT_SUFFIX = ".result"
_SYNTAX = "use ${params.<name>} or ${tasks.<id>.result}"


def is_name(value: object) -> bool:
    """Return whether ``value`` can be a task ID or a parameter name."""
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


@dataclass(frozen=True)
class Reference:
    """One placeholder found in a string."""

    kind: str  # "params" or "tasks"
    name: str | None  # the parameter name or task ID; ``None`` when the placeholder is malformed
    text: str  # the placeholder as written
    whole: bool  # whether the placeholder is the entire string


def _reference(match: re.Match[str], whole: bool) -> Reference:
    kind, body = match.group(1), match.group(2)
    if kind == _TASKS:
        body = body[: -len(_RESULT_SUFFIX)] if body.endswith(_RESULT_SUFFIX) else ""
    return Reference(kind, body if is_name(body) else None, match.group(0), whole)


def references(text: str) -> list[Reference]:
    """Return the pipeline placeholders of ``text``, in order."""
    matches = list(_PLACEHOLDER.finditer(text))
    whole = len(matches) == 1 and matches[0].span() == (0, len(text))
    return [_reference(match, whole) for match in matches]


def _task_reference_problem(reference: Reference, upstream: Collection[str] | None) -> str | None:
    if upstream is None:
        return f"{reference.text}: only ${{params.<name>}} can be used here"
    if not reference.whole:
        return f"{reference.text} must be the whole string"
    if reference.name not in upstream:
        return f"{reference.text}: {reference.name!r} is not an upstream task (see depends_on)"
    return None


def text_problems(
    text: str,
    upstream: Collection[str] | None,
    params: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return what is wrong with the placeholders of ``text``.

    ``upstream`` holds the task IDs whose result may be used; ``None`` forbids
    task results altogether (an idempotency key). With ``params``, a parameter
    the run was not given is a problem too.
    """
    problems: list[str] = []
    for reference in references(text):
        problem: str | None = None
        if reference.name is None:
            problem = f"malformed placeholder {reference.text} ({_SYNTAX})"
        elif reference.kind == _TASKS:
            problem = _task_reference_problem(reference, upstream)
        elif params is not None and reference.name not in params:
            problem = f"unknown parameter {reference.name!r}"
        if problem is not None:
            problems.append(problem)
    return problems


def walk_strings(value: Any, path: str) -> Iterator[tuple[str, str]]:
    """Yield ``(path, text)`` for every string inside nested mappings and lists."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from walk_strings(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from walk_strings(item, f"{path}[{index}]")


def action_reference_problems(
    action: Sequence[Any],
    path: str,
    upstream: Collection[str],
    params: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return the placeholder problems of an action's arguments, each with its path."""
    problems: list[str] = []
    for index, payload in enumerate(action[1:], start=1):
        for where, text in walk_strings(payload, f"{path}[{index}]"):
            problems.extend(
                f"{where}: {problem}" for problem in text_problems(text, upstream, params)
            )
    return problems


def _resolve(reference: Reference, params: Mapping[str, Any], results: Mapping[str, Any]) -> Any:
    if reference.name is None:
        raise PipelineException(f"malformed placeholder {reference.text} ({_SYNTAX})")
    if reference.kind == _TASKS:
        return results.get(reference.name)
    if reference.name not in params:
        raise PipelineException(f"unknown parameter {reference.name!r} in {reference.text}")
    return params[reference.name]


def _render_text(text: str, params: Mapping[str, Any], results: Mapping[str, Any]) -> Any:
    found = references(text)
    if not found:
        return text
    if found[0].whole:
        return _resolve(found[0], params, results)
    return _PLACEHOLDER.sub(
        lambda match: str(_resolve(_reference(match, False), params, results)), text
    )


def render(value: Any, params: Mapping[str, Any], results: Mapping[str, Any]) -> Any:
    """Return a copy of ``value`` with every placeholder replaced.

    Mappings and lists are walked; mapping keys and non-string values are kept.
    An unknown parameter raises :class:`PipelineException`.
    """
    if isinstance(value, str):
        return _render_text(value, params, results)
    if isinstance(value, Mapping):
        return {key: render(item, params, results) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, params, results) for item in value]
    return value


def render_key(key: str, params: Mapping[str, Any]) -> str:
    """Return an idempotency key with its ``${params.<name>}`` placeholders filled in."""
    return str(render(key, params, {}))
