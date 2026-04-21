"""JSON persistence for action lists.

Reads/writes are serialised through a module-level lock so concurrent callers
cannot interleave writes against the same file.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from automation_file.exceptions import JsonActionException
from automation_file.logging_config import file_automation_logger

_lock = Lock()


def read_action_json(json_file_path: str) -> Any:
    """Return the parsed JSON content at ``json_file_path``."""
    with _lock:
        path = Path(json_file_path)
        if not path.is_file():
            raise JsonActionException(f"can't read JSON file: {json_file_path}")
        try:
            with path.open(encoding="utf-8") as read_file:
                data = json.load(read_file)
        except (OSError, json.JSONDecodeError) as error:
            raise JsonActionException(f"can't read JSON file: {json_file_path}") from error
        file_automation_logger.info("read_action_json: %s", json_file_path)
        return data


def write_action_json(json_save_path: str, action_json: Any) -> None:
    """Write ``action_json`` to ``json_save_path`` as pretty UTF-8 JSON."""
    with _lock:
        try:
            with open(json_save_path, "w", encoding="utf-8") as file_to_write:
                json.dump(action_json, file_to_write, indent=4, ensure_ascii=False)
        except (OSError, TypeError) as error:
            raise JsonActionException(f"can't write JSON file: {json_save_path}") from error
        file_automation_logger.info("write_action_json: %s", json_save_path)
