"""In-place JSON file editing with dotted-path key access.

Supports ``get`` / ``set`` / ``delete`` operations against any key path
``a.b.c`` where each segment is a mapping key or a list index (numeric).
Writes are atomic — the new content lands in a sibling tempfile that is
``os.replace`` d over the original after ``json.dumps`` succeeds.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import MutableMapping, MutableSequence
from pathlib import Path
from typing import Any

from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger

_MISSING = object()


class JsonEditException(FileAutomationException):
    """Raised when a JSON edit operation cannot be completed."""


def json_get(path: str, key_path: str, default: Any = None) -> Any:
    """Return the value at dotted ``key_path`` in the JSON file, or ``default``."""
    data = _load(path)
    result = _walk(data, _split(key_path))
    return default if result is _MISSING else result


def json_set(path: str, key_path: str, value: Any) -> bool:
    """Set the value at dotted ``key_path``. Creates intermediate dicts."""
    data = _load(path)
    segments = _split(key_path)
    if not segments:
        raise JsonEditException("key_path must not be empty")
    _set_in(data, segments, value)
    _dump(path, data)
    file_automation_logger.info("json_set: %s %s", path, key_path)
    return True


def json_delete(path: str, key_path: str) -> bool:
    """Delete the value at dotted ``key_path``. Returns True if a value was removed."""
    data = _load(path)
    segments = _split(key_path)
    if not segments:
        raise JsonEditException("key_path must not be empty")
    removed = _delete_in(data, segments)
    if removed:
        _dump(path, data)
        file_automation_logger.info("json_delete: %s %s", path, key_path)
    return removed


def _split(key_path: str) -> list[str]:
    if not isinstance(key_path, str):
        raise JsonEditException("key_path must be a string")
    return [segment for segment in key_path.split(".") if segment != ""]


def _load(path: str) -> Any:
    file_path = Path(path)
    if not file_path.is_file():
        raise JsonEditException(f"not a file: {path}")
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise JsonEditException(f"cannot read JSON: {path}: {err}") from err


def _dump(path: str, data: Any) -> None:
    file_path = Path(path)
    directory = file_path.parent
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(directory),
            delete=False,
            suffix=".tmp",
        ) as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            tmp_name = handle.name
    except OSError as err:
        raise JsonEditException(f"cannot write temp file near {path}: {err}") from err
    try:
        os.replace(tmp_name, str(file_path))
    except OSError as err:
        Path(tmp_name).unlink(missing_ok=True)
        raise JsonEditException(f"cannot replace {path}: {err}") from err


def _walk(data: Any, segments: list[str]) -> Any:
    current: Any = data
    for segment in segments:
        try:
            current = _child(current, segment)
        except (KeyError, IndexError, TypeError):
            return _MISSING
    return current


def _child(container: Any, segment: str) -> Any:
    if isinstance(container, MutableMapping):
        return container[segment]
    if isinstance(container, MutableSequence) and segment.lstrip("-").isdigit():
        return container[int(segment)]
    raise TypeError(f"cannot index {type(container).__name__} by {segment!r}")


def _is_int_segment(segment: str) -> bool:
    return segment.lstrip("-").isdigit()


def _descend_for_set(container: Any, segment: str) -> Any:
    if isinstance(container, MutableMapping):
        if segment not in container or not isinstance(
            container[segment], (MutableMapping, MutableSequence)
        ):
            container[segment] = {}
        return container[segment]
    if isinstance(container, MutableSequence) and _is_int_segment(segment):
        return container[int(segment)]
    raise JsonEditException(f"cannot traverse into {segment!r}")


def _assign_into_sequence(container: MutableSequence[Any], last: str, value: Any) -> None:
    idx = int(last)
    if -len(container) <= idx < len(container):
        container[idx] = value
        return
    if idx == len(container):
        container.append(value)
        return
    raise JsonEditException(f"list index out of range: {idx}")


def _set_in(data: Any, segments: list[str], value: Any) -> None:
    container = data
    for segment in segments[:-1]:
        container = _descend_for_set(container, segment)
    last = segments[-1]
    if isinstance(container, MutableMapping):
        container[last] = value
        return
    if isinstance(container, MutableSequence) and _is_int_segment(last):
        _assign_into_sequence(container, last, value)
        return
    raise JsonEditException(f"cannot set into {type(container).__name__}")


def _descend_for_delete(container: Any, segment: str) -> Any:
    if isinstance(container, MutableMapping):
        return container.get(segment, _MISSING)
    if isinstance(container, MutableSequence) and _is_int_segment(segment):
        idx = int(segment)
        if -len(container) <= idx < len(container):
            return container[idx]
    return _MISSING


def _remove_last(container: Any, last: str) -> bool:
    if isinstance(container, MutableMapping):
        if last not in container:
            return False
        del container[last]
        return True
    if isinstance(container, MutableSequence) and _is_int_segment(last):
        idx = int(last)
        if not -len(container) <= idx < len(container):
            return False
        del container[idx]
        return True
    return False


def _delete_in(data: Any, segments: list[str]) -> bool:
    container = data
    for segment in segments[:-1]:
        container = _descend_for_delete(container, segment)
        if container is _MISSING:
            return False
    return _remove_last(container, segments[-1])
