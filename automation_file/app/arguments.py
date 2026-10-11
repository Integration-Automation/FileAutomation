"""Turn what a form holds into action arguments, and describe an action for a form.

A user interface edits arguments as text. :func:`parse_argument_text` reads one
field: JSON when the text is JSON (``12``, ``true``, ``["a", "b"]``, ``"12"``),
otherwise the text itself, so a URI or a ``${params.date}`` placeholder needs
no quotes. :func:`format_argument_value` is the way back. :func:`describe_action`
lists the parameters of a registered action so a form can offer one row each.
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from automation_file.app.errors import AppException

_VARIADIC = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
_NAME_SEPARATORS = re.compile(r"[,\s]+")


@dataclass(frozen=True)
class ActionParameter:
    """One parameter of an action. ``default`` is its default as form text."""

    name: str
    required: bool
    default: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the parameter."""
        return asdict(self)


@dataclass(frozen=True)
class ActionInfo:
    """What a form needs to know about an action.

    ``known`` is false for a name the registry does not have. ``accepts_extra``
    says the action takes ``**kwargs``, so arguments beyond ``parameters`` are
    allowed. ``signature`` is unavailable (empty) for a builtin without one.
    """

    name: str
    known: bool = False
    signature: str = ""
    summary: str = ""
    parameters: tuple[ActionParameter, ...] = ()
    accepts_extra: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the description."""
        return asdict(self)


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON value")


def _loads(text: str) -> Any:
    """Parse strict JSON: ``NaN`` and ``Infinity`` are text, not numbers."""
    return json.loads(text, parse_constant=_no_constant)


def parse_argument_text(text: str) -> Any:
    """Return the value one form field stands for: JSON when it parses, else the text."""
    stripped = text.strip()
    try:
        return _loads(stripped)
    except ValueError:
        return stripped


def format_argument_value(value: Any) -> str:
    """Return ``value`` as form text that :func:`parse_argument_text` reads back unchanged."""
    if isinstance(value, str) and value and value == value.strip():
        try:
            _loads(value)
        except ValueError:
            return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


def split_names(value: Any) -> Any:
    """Return the names in a form field: ``"a, b"`` becomes ``["a", "b"]``; other values pass."""
    if isinstance(value, str):
        return [name for name in _NAME_SEPARATORS.split(value.strip()) if name]
    return value


def parse_json_text(text: str, what: str, *, empty: Any = None) -> Any:
    """Return the JSON document in ``text``, or ``empty`` when the text is blank.

    Raises :class:`AppException` naming ``what`` and the position of the mistake.
    """
    if not text.strip():
        return empty
    try:
        return _loads(text)
    except json.JSONDecodeError as error:
        raise AppException(
            f"{what} is not valid JSON: {error.msg} at line {error.lineno}, column {error.colno}"
        ) from error
    except ValueError as error:
        raise AppException(f"{what} is not valid JSON: {error}") from error


def _summary(command: Callable[..., Any]) -> str:
    lines = (inspect.getdoc(command) or "").strip().splitlines()
    return lines[0] if lines else ""


def _without_annotations(signature: inspect.Signature) -> str:
    """Return ``(name, other=default)``: the parameters as a caller writes them."""
    bare = [
        parameter.replace(annotation=inspect.Parameter.empty)
        for parameter in signature.parameters.values()
    ]
    return str(signature.replace(parameters=bare, return_annotation=inspect.Signature.empty))


def describe_action(name: str, command: Callable[..., Any] | None) -> ActionInfo:
    """Describe the registered action ``name``; ``command`` is ``None`` when it is unknown."""
    if command is None:
        return ActionInfo(name=name)
    try:
        signature = inspect.signature(command)
    except (TypeError, ValueError):
        return ActionInfo(name=name, known=True, summary=_summary(command), accepts_extra=True)
    parameters = tuple(
        ActionParameter(
            name=parameter.name,
            required=parameter.default is inspect.Parameter.empty,
            default=(
                ""
                if parameter.default is inspect.Parameter.empty
                else format_argument_value(parameter.default)
            ),
        )
        for parameter in signature.parameters.values()
        if parameter.kind not in _VARIADIC
    )
    return ActionInfo(
        name=name,
        known=True,
        signature=f"{name}{_without_annotations(signature)}",
        summary=_summary(command),
        parameters=parameters,
        accepts_extra=any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ),
    )
