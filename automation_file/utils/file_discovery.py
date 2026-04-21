"""Filesystem discovery helpers."""
from __future__ import annotations

from pathlib import Path

_DEFAULT_EXTENSION = ".json"


def get_dir_files_as_list(
    dir_path: str | None = None,
    default_search_file_extension: str = _DEFAULT_EXTENSION,
) -> list[str]:
    """Recursively collect files under ``dir_path`` matching an extension.

    Returns absolute paths. The extension comparison is case-insensitive.
    """
    root = Path(dir_path) if dir_path is not None else Path.cwd()
    suffix = default_search_file_extension.lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return [
        str(path.absolute())
        for path in root.rglob("*")
        if path.is_file() and path.name.lower().endswith(suffix)
    ]
