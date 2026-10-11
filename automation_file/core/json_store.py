"""JSON persistence for action lists.

Reads/writes are serialised through one lock so concurrent callers cannot
interleave writes against the same file (je_action_core's ``ActionJsonFile``).
"""

from __future__ import annotations

import json
from typing import Any

from je_action_core import ActionJsonFile, JsonFileMessages, JsonFileSettings

from automation_file.exceptions import JsonActionException
from automation_file.logging_config import file_automation_logger

_json_file = ActionJsonFile(
    JsonFileSettings(
        error=JsonActionException,
        messages=JsonFileMessages(
            missing="can't read JSON file: {path}",
            unreadable="can't read JSON file: {path}",
            unwritable="can't write JSON file: {path}",
        ),
        read_errors=(OSError, json.JSONDecodeError),
        write_errors=(OSError, TypeError),
        log_info=file_automation_logger.info,
    )
)


def read_action_json(json_file_path: str) -> Any:
    """Return the parsed JSON content at ``json_file_path``."""
    return _json_file.read(json_file_path)


def write_action_json(json_save_path: str, action_json: Any) -> None:
    """Write ``action_json`` to ``json_save_path`` as pretty UTF-8 JSON.

    Data that cannot be serialised leaves the file as it was.
    """
    _json_file.write(json_save_path, action_json)
