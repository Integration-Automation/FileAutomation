"""Pipeline definitions as documents: the schema, the validator and the file loader.

A definition is a mapping (from YAML, JSON or Python) with ``schema_version: 1``.
:func:`validate_definition` checks one by hand and returns every problem with the
path of the offending entry; :data:`PIPELINE_SCHEMA` describes the same shape as
a JSON Schema document for editors and other tools.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from automation_file import exceptions
from automation_file.pipeline.errors import PipelineDefinitionException
from automation_file.pipeline.graph import dependency_problems, upstream_tasks
from automation_file.pipeline.model import (
    DEFAULT_RETRY_ON,
    ON_SUCCESS,
    WHEN_CHOICES,
    RetryPolicy,
    Task,
)
from automation_file.pipeline.substitution import (
    NAME_PATTERN,
    NAME_RULE,
    action_reference_problems,
    is_name,
    text_problems,
)

SCHEMA_VERSION = 1
_TOP_KEYS = ("schema_version", "name", "description", "max_workers", "schedule", "params", "tasks")
_TASK_KEYS = ("action", "depends_on", "retry", "timeout", "when", "idempotency_key")
_RETRY_KEYS = ("max_attempts", "backoff", "backoff_cap", "on")
_SCHEDULE_KEYS = ("cron", "timezone")
_YAML_SUFFIXES = (".yaml", ".yml")
_JSON_SUFFIX = ".json"
_MAX_YAML_NODES = 200_000
_MAX_ACTION_ITEMS = 2
_MISSING: Any = object()
_JSON_SCALARS = (str, int, float, bool, type(None))
_DEFAULT_RETRY = RetryPolicy()
_CALLABLE_NOT_WRITABLE = "a Python callable cannot be written to a definition"
_YAML_ON_HINT = ' (YAML reads a bare on as true; write "on")'
_TOO_DEEP = "the definition is nested too deeply"


def _retryable_exceptions() -> dict[str, type[BaseException]]:
    found: dict[str, type[BaseException]] = {
        name: member
        for name, member in vars(exceptions).items()
        if isinstance(member, type) and issubclass(member, exceptions.FileAutomationException)
    }
    found.update({kind.__name__: kind for kind in (TimeoutError, ConnectionError, OSError)})
    return dict(sorted(found.items()))


#: The exception classes a definition may name under ``retry.on``, by name.
RETRYABLE_EXCEPTIONS: Mapping[str, type[BaseException]] = MappingProxyType(_retryable_exceptions())


def _schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:automation_file:pipeline:1",
        "title": "automation_file pipeline definition",
        "type": "object",
        "required": ["schema_version", "name", "tasks"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "name": {"type": "string", "pattern": "\\S"},
            "description": {"type": "string"},
            "max_workers": {"type": "integer", "minimum": 1},
            "schedule": {"$ref": "#/$defs/schedule"},
            "params": {"type": "object", "propertyNames": {"pattern": NAME_PATTERN}},
            "tasks": {
                "type": "object",
                "minProperties": 1,
                "propertyNames": {"pattern": NAME_PATTERN},
                "additionalProperties": {"$ref": "#/$defs/task"},
            },
        },
        "$defs": {
            "schedule": {
                "type": "object",
                "required": ["cron"],
                "additionalProperties": False,
                "properties": {
                    "cron": {"type": "string", "pattern": "\\S"},
                    "timezone": {"type": "string", "pattern": "\\S"},
                },
            },
            "action": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_ACTION_ITEMS,
                "prefixItems": [
                    {"type": "string", "minLength": 1},
                    {"type": ["object", "array"]},
                ],
            },
            "retry": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "max_attempts": {"type": "integer", "minimum": 1},
                    "backoff": {"type": "number", "minimum": 0},
                    "backoff_cap": {"type": "number", "minimum": 0},
                    "on": {"type": "array", "items": {"enum": list(RETRYABLE_EXCEPTIONS)}},
                },
            },
            "task": {
                "type": "object",
                "required": ["action"],
                "additionalProperties": False,
                "properties": {
                    "action": {"$ref": "#/$defs/action"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "uniqueItems": True,
                    },
                    "retry": {"$ref": "#/$defs/retry"},
                    "timeout": {"type": "number", "exclusiveMinimum": 0},
                    "when": {"enum": list(WHEN_CHOICES)},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
            },
        },
    }


#: JSON Schema (draft 2020-12) of a ``schema_version: 1`` definition.
PIPELINE_SCHEMA: dict[str, Any] = _schema()


# ---------------------------------------------------------------------- small checks


def _kind(value: Any) -> str:
    return type(value).__name__


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unknown_keys(mapping: Mapping[Any, Any], allowed: tuple[str, ...], prefix: str) -> list[str]:
    return [f"{prefix}{key}: unknown key" for key in mapping if key not in allowed]


def action_problems(action: Any, path: str) -> list[str]:
    """Return what keeps ``action`` from being one of the three action shapes."""
    if not isinstance(action, list) or not action:
        found = "an empty list" if isinstance(action, list) else _kind(action)
        return [f"{path}: expected [name], [name, {{kwargs}}] or [name, [args]], got {found}"]
    problems: list[str] = []
    if not (isinstance(action[0], str) and action[0]):
        problems.append(f"{path}[0]: expected an action name, got {_kind(action[0])}")
    if len(action) > _MAX_ACTION_ITEMS:
        problems.append(f"{path}: expected a name and at most one argument set, got {len(action)}")
    elif len(action) == _MAX_ACTION_ITEMS:
        problems.extend(_arguments_problems(action[1], f"{path}[1]"))
    return problems


def _arguments_problems(arguments: Any, path: str) -> list[str]:
    if isinstance(arguments, list):
        return []
    if not isinstance(arguments, dict):
        return [f"{path}: expected a mapping or a list of arguments, got {_kind(arguments)}"]
    return [
        f"{path}: argument name {key!r} is not a string"
        for key in arguments
        if not isinstance(key, str)
    ]


def _json_problems(value: Any, path: str) -> list[str]:
    """Return the values inside ``value`` that JSON cannot hold, such as an unquoted YAML date."""
    if isinstance(value, _JSON_SCALARS):
        return []
    if isinstance(value, list):
        return [
            problem
            for index, item in enumerate(value)
            for problem in _json_problems(item, f"{path}[{index}]")
        ]
    if isinstance(value, Mapping):
        return [
            problem
            for key, item in value.items()
            for problem in _json_problems(item, f"{path}.{key}")
        ]
    return [f"{path}: expected a JSON value, got {_kind(value)} (quote dates and times in YAML)"]


def depends_on_problems(value: Any, path: str) -> list[str]:
    """Return the shape problems of a ``depends_on`` list (the graph is checked separately)."""
    if not isinstance(value, (list, tuple)):
        return [f"{path}: expected a list of task IDs, got {_kind(value)}"]
    return [
        f"{path}[{index}]: expected a task ID, got {_kind(item)}"
        for index, item in enumerate(value)
        if not isinstance(item, str)
    ]


def timeout_problems(value: Any, path: str) -> list[str]:
    """Return the problem of a ``timeout`` that is not a positive number of seconds."""
    if _is_number(value) and value > 0:
        return []
    return [f"{path}: expected a number of seconds > 0, got {value!r}"]


def when_problems(value: Any, path: str) -> list[str]:
    """Return the problem of a ``when`` that is not one of the named conditions."""
    if isinstance(value, str) and value in WHEN_CHOICES:
        return []
    return [f"{path}: expected one of {', '.join(WHEN_CHOICES)}, got {value!r}"]


def idempotency_key_problems(value: Any, path: str) -> list[str]:
    """Return the problems of an idempotency key: its type and its placeholders."""
    if not (isinstance(value, str) and value):
        return [f"{path}: expected a non-empty string, got {value!r}"]
    return [f"{path}: {problem}" for problem in text_problems(value, None)]


def _retry_problems(value: Any, path: str) -> list[str]:
    if not isinstance(value, Mapping):
        return [f"{path}: expected a mapping, got {_kind(value)}"]
    problems = [
        f"{path}.{key}: unknown key{_YAML_ON_HINT if key is True else ''}"
        for key in value
        if key not in _RETRY_KEYS
    ]
    attempts = value.get("max_attempts", 1)
    if not _is_integer(attempts) or attempts < 1:
        problems.append(f"{path}.max_attempts: expected an integer >= 1, got {attempts!r}")
    for key in ("backoff", "backoff_cap"):
        seconds = value.get(key, 0)
        if not _is_number(seconds) or seconds < 0:
            problems.append(f"{path}.{key}: expected a number of seconds >= 0, got {seconds!r}")
    if "on" in value:
        problems.extend(_retry_on_problems(value["on"], f"{path}.on"))
    return problems


def _retry_on_problems(names: Any, path: str) -> list[str]:
    if not isinstance(names, list):
        return [f"{path}: expected a list of exception names, got {_kind(names)}"]
    return [
        f"{path}[{index}]: unknown exception {name!r}"
        for index, name in enumerate(names)
        if not (isinstance(name, str) and name in RETRYABLE_EXCEPTIONS)
    ]


_TASK_CHECKS: Mapping[str, Callable[[Any, str], list[str]]] = MappingProxyType(
    {
        "action": action_problems,
        "depends_on": depends_on_problems,
        "retry": _retry_problems,
        "timeout": timeout_problems,
        "when": when_problems,
        "idempotency_key": idempotency_key_problems,
    }
)


# ---------------------------------------------------------------------- the document


def _version_problem(document: Mapping[Any, Any]) -> str | None:
    if "schema_version" not in document:
        return f"schema_version: required (supported: {SCHEMA_VERSION})"
    version = document["schema_version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        return f"schema_version: unsupported version {version!r} (supported: {SCHEMA_VERSION})"
    return None


def _cron_problem(cron: Any) -> str | None:
    from automation_file.scheduler.cron import CronException, CronExpression

    if not isinstance(cron, str):
        return f"schedule.cron: expected a cron expression, got {_kind(cron)}"
    try:
        CronExpression.parse(cron)
    except CronException as error:
        return f"schedule.cron: {str(error).removeprefix('cron: ')}"
    return None


def _schedule_problems(schedule: Any) -> list[str]:
    if not isinstance(schedule, Mapping):
        return [f"schedule: expected a mapping, got {_kind(schedule)}"]
    problems = _unknown_keys(schedule, _SCHEDULE_KEYS, "schedule.")
    if "cron" not in schedule:
        problems.append("schedule.cron: required")
    else:
        cron = _cron_problem(schedule["cron"])
        if cron is not None:
            problems.append(cron)
    if "timezone" in schedule and not _is_text(schedule["timezone"]):
        problems.append(
            f"schedule.timezone: expected a time zone name, got {schedule['timezone']!r}"
        )
    return problems


def params_problems(params: Any) -> list[str]:
    """Return the problems of a ``params`` mapping: its type and its names."""
    if not isinstance(params, Mapping):
        return [f"params: expected a mapping, got {_kind(params)}"]
    return [
        f"params.{name}: invalid parameter name, {NAME_RULE}"
        for name in params
        if not is_name(name)
    ]


def _header_problems(document: Mapping[Any, Any]) -> list[str]:
    problems: list[str] = []
    if "name" not in document:
        problems.append("name: required")
    elif not _is_text(document["name"]):
        problems.append(f"name: expected a non-empty string, got {document['name']!r}")
    if not isinstance(document.get("description", ""), str):
        problems.append(f"description: expected a string, got {_kind(document['description'])}")
    workers = document.get("max_workers", 1)
    if not _is_integer(workers) or workers < 1:
        problems.append(f"max_workers: expected an integer >= 1, got {workers!r}")
    if "schedule" in document:
        problems.extend(_schedule_problems(document["schedule"]))
    if "params" in document:
        problems.extend(params_problems(document["params"]))
        if isinstance(document["params"], Mapping):
            problems.extend(_json_problems(document["params"], "params"))
    return problems


def _task_problems(spec: Any, path: str) -> list[str]:
    if not isinstance(spec, Mapping):
        return [f"{path}: expected a mapping, got {_kind(spec)}"]
    problems = _unknown_keys(spec, _TASK_KEYS, f"{path}.")
    if "action" not in spec:
        problems.append(f"{path}.action: required")
    elif isinstance(spec["action"], list):
        problems.extend(_json_problems(spec["action"], f"{path}.action"))
    for key, check in _TASK_CHECKS.items():
        if key in spec:
            problems.extend(check(spec[key], f"{path}.{key}"))
    return problems


def _listed_dependencies(spec: Any) -> list[str]:
    """Return a task's dependencies when they are all task IDs, else nothing to check."""
    wanted = spec.get("depends_on", []) if isinstance(spec, Mapping) else []
    if isinstance(wanted, list) and all(isinstance(item, str) for item in wanted):
        return wanted
    return []


def _reference_problems(tasks: Mapping[Any, Any], dependencies: dict[str, list[str]]) -> list[str]:
    problems: list[str] = []
    for task_id, upstream in upstream_tasks(dependencies).items():
        spec = tasks[task_id]
        action = spec.get("action") if isinstance(spec, Mapping) else None
        if isinstance(action, list):
            problems.extend(action_reference_problems(action, f"tasks.{task_id}.action", upstream))
    return problems


def _tasks_problems(document: Mapping[Any, Any]) -> list[str]:
    tasks = document.get("tasks", _MISSING)
    if tasks is _MISSING:
        return ["tasks: required"]
    if not isinstance(tasks, Mapping):
        return [f"tasks: expected a mapping of task ID to task, got {_kind(tasks)}"]
    if not tasks:
        return ["tasks: at least one task is required"]
    problems: list[str] = []
    dependencies: dict[str, list[str]] = {}
    for task_id, spec in tasks.items():
        if not is_name(task_id):
            problems.append(f"tasks.{task_id}: invalid task ID, {NAME_RULE}")
            continue
        dependencies[task_id] = _listed_dependencies(spec)
        problems.extend(_task_problems(spec, f"tasks.{task_id}"))
    problems.extend(dependency_problems(dependencies))
    problems.extend(_reference_problems(tasks, dependencies))
    return problems


def validate_definition(document: Any) -> list[str]:
    """Return every problem of a definition document; an empty list means it is valid.

    Each problem starts with the path of the entry it is about, for example
    ``tasks.verify.depends_on[0]: unknown task 'x'``. A document without
    ``schema_version``, or with one this version does not know, gets that single
    finding: its other entries cannot be judged.
    """
    if not isinstance(document, Mapping):
        return [f"document: expected a mapping, got {_kind(document)}"]
    version = _version_problem(document)
    if version is not None:
        return [version]
    problems = _unknown_keys(document, _TOP_KEYS, "")
    problems.extend(_header_problems(document))
    problems.extend(_tasks_problems(document))
    return problems


# ---------------------------------------------------------------------- to and from tasks


def retry_from_dict(spec: Mapping[str, Any]) -> RetryPolicy:
    """Build a :class:`RetryPolicy` from the ``retry`` entry of a valid definition."""
    kinds = DEFAULT_RETRY_ON
    if "on" in spec:
        kinds = tuple(RETRYABLE_EXCEPTIONS[name] for name in spec["on"])
    return RetryPolicy(
        max_attempts=spec.get("max_attempts", _DEFAULT_RETRY.max_attempts),
        backoff_base=spec.get("backoff", _DEFAULT_RETRY.backoff_base),
        backoff_cap=spec.get("backoff_cap", _DEFAULT_RETRY.backoff_cap),
        retry_on=kinds,
    )


def _retry_to_dict(policy: RetryPolicy, path: str) -> dict[str, Any]:
    spec: dict[str, Any] = {"max_attempts": policy.max_attempts}
    if policy.backoff_base != _DEFAULT_RETRY.backoff_base:
        spec["backoff"] = policy.backoff_base
    if policy.backoff_cap != _DEFAULT_RETRY.backoff_cap:
        spec["backoff_cap"] = policy.backoff_cap
    if policy.retry_on != DEFAULT_RETRY_ON:
        for kind in policy.retry_on:
            if RETRYABLE_EXCEPTIONS.get(kind.__name__) is not kind:
                raise PipelineDefinitionException(
                    f"{path}.on: {kind.__name__} cannot be named in a definition"
                )
        spec["on"] = [kind.__name__ for kind in policy.retry_on]
    return spec


def _copied(value: Any) -> Any:
    """Copy nested mappings and lists; leave every other value as it is."""
    if isinstance(value, Mapping):
        return {key: _copied(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copied(item) for item in value]
    return value


def task_to_dict(task: Task) -> dict[str, Any]:
    """Return the definition entry of ``task``.

    Raises :class:`PipelineDefinitionException` for what a document cannot hold:
    a Python callable as the work or as ``when``, or a ``retry_on`` class outside
    :data:`RETRYABLE_EXCEPTIONS`.
    """
    path = f"tasks.{task.task_id}"
    if callable(task.work):
        raise PipelineDefinitionException(f"{path}: {_CALLABLE_NOT_WRITABLE}")
    if callable(task.when):
        raise PipelineDefinitionException(f"{path}.when: {_CALLABLE_NOT_WRITABLE}")
    spec: dict[str, Any] = {"action": _copied(task.work)}
    if task.depends_on:
        spec["depends_on"] = list(task.depends_on)
    if task.retry != _DEFAULT_RETRY:
        spec["retry"] = _retry_to_dict(task.retry, f"{path}.retry")
    if task.timeout is not None:
        spec["timeout"] = task.timeout
    if task.when != ON_SUCCESS:
        spec["when"] = task.when
    if task.idempotency_key is not None:
        spec["idempotency_key"] = task.idempotency_key
    return spec


# ---------------------------------------------------------------------- files


def _unique_keys(source: Path) -> Callable[[list[tuple[str, Any]]], dict[str, Any]]:
    def build(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        built: dict[str, Any] = {}
        for key, value in pairs:
            if key in built:
                raise PipelineDefinitionException(f"{source}: duplicate key {key!r}")
            built[key] = value
        return built

    return build


def _parse_json(text: str, source: Path) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_keys(source))
    except json.JSONDecodeError as error:
        raise PipelineDefinitionException(
            f"{source}: invalid JSON: {error.msg} at line {error.lineno}, column {error.colno}"
        ) from error
    except RecursionError as error:
        raise PipelineDefinitionException(f"{source}: {_TOO_DEEP}") from error


def _check_yaml_nodes(root: Any, source: Path) -> None:
    """Refuse a repeated mapping key, and a document that aliases make huge or endless."""
    stack = [] if root is None else [root]
    budget = _MAX_YAML_NODES
    while stack:
        node = stack.pop()
        budget -= 1
        if budget < 0:
            raise PipelineDefinitionException(
                f"{source}: the definition is too large or refers to itself"
            )
        if node.id == "sequence":
            stack.extend(node.value)
        elif node.id == "mapping":
            _reject_repeated_keys(node, source)
            stack.extend(value for _key, value in node.value)


def _reject_repeated_keys(node: Any, source: Path) -> None:
    seen: set[str] = set()
    for key, _value in node.value:
        if key.id != "scalar":
            continue
        if key.value in seen:
            raise PipelineDefinitionException(
                f"{source}: duplicate key {key.value!r} at line {key.start_mark.line + 1}"
            )
        seen.add(key.value)


def _yaml_reason(error: Exception) -> str:
    """Say what the parser objected to and where, without quoting the file's content."""
    parts = [getattr(error, "context", None), getattr(error, "problem", None)]
    reason = " ".join(str(part) for part in parts if part) or "syntax error"
    mark = getattr(error, "problem_mark", None)
    if mark is None:
        return reason
    return f"{reason} at line {mark.line + 1}, column {mark.column + 1}"


def _restore_on_keys(document: Any) -> Any:
    """Give every ``retry`` entry its ``on`` key back: YAML 1.1 reads a bare ``on`` as ``true``."""
    tasks = document.get("tasks") if isinstance(document, dict) else None
    if not isinstance(tasks, dict):
        return document
    for spec in tasks.values():
        retry = spec.get("retry") if isinstance(spec, dict) else None
        if isinstance(retry, dict) and "on" not in retry and any(key is True for key in retry):
            spec["retry"] = {("on" if key is True else key): item for key, item in retry.items()}
    return document


def _parse_yaml(text: str, source: Path) -> Any:
    import yaml

    try:
        _check_yaml_nodes(yaml.compose(text, Loader=yaml.SafeLoader), source)
        return _restore_on_keys(yaml.safe_load(text))
    except yaml.YAMLError as error:
        raise PipelineDefinitionException(
            f"{source}: invalid YAML: {_yaml_reason(error)}"
        ) from error
    except RecursionError as error:
        raise PipelineDefinitionException(f"{source}: {_TOO_DEEP}") from error


def load_definition(path: str | os.PathLike[str]) -> Any:
    """Read a definition document from a ``.yaml`` / ``.yml`` or ``.json`` file.

    The content is returned as parsed, without validation. YAML goes through
    ``yaml.safe_load``; a key repeated in one mapping is an error in both formats,
    so a second task with the same ID cannot silently replace the first. YAML 1.1
    reads a bare ``on`` as ``true``: under ``retry`` that key is given back as ``"on"``.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in (*_YAML_SUFFIXES, _JSON_SUFFIX):
        raise PipelineDefinitionException(f"{source}: expected a .yaml, .yml or .json file")
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PipelineDefinitionException(
            f"{source}: cannot read the definition: {error}"
        ) from error
    return _parse_json(text, source) if suffix == _JSON_SUFFIX else _parse_yaml(text, source)
