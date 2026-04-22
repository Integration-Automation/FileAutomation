"""Directory-level operations (Strategy module for the executor)."""

from __future__ import annotations

import shutil
from pathlib import Path

from automation_file.exceptions import DirNotExistsException
from automation_file.logging_config import file_automation_logger


def copy_dir(dir_path: str, target_dir_path: str) -> bool:
    """Recursively copy a directory tree. Return True on success."""
    source = Path(dir_path)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    try:
        shutil.copytree(source, Path(target_dir_path), dirs_exist_ok=True)
        file_automation_logger.info("copy_dir: %s -> %s", source, target_dir_path)
        return True
    except OSError as error:
        file_automation_logger.error("copy_dir failed: %r", error)
        return False


def remove_dir_tree(dir_path: str) -> bool:
    """Recursively delete a directory tree."""
    path = Path(dir_path)
    if not path.is_dir():
        return False
    try:
        shutil.rmtree(path)
        file_automation_logger.info("remove_dir_tree: %s", path)
        return True
    except OSError as error:
        file_automation_logger.error("remove_dir_tree failed: %r", error)
        return False


def rename_dir(origin_dir_path: str, target_dir: str) -> bool:
    """Rename (move) a directory."""
    source = Path(origin_dir_path)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    try:
        source.rename(target_dir)
        file_automation_logger.info("rename_dir: %s -> %s", source, target_dir)
        return True
    except OSError as error:
        file_automation_logger.error("rename_dir failed: %r", error)
        return False


def create_dir(dir_path: str) -> bool:
    """Create a directory (no error if it already exists)."""
    path = Path(dir_path)
    path.mkdir(parents=True, exist_ok=True)
    file_automation_logger.info("create_dir: %s", path)
    return True
