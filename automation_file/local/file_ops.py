"""File-level operations (Strategy module for the executor)."""
from __future__ import annotations

import shutil
from pathlib import Path

from automation_file.exceptions import DirNotExistsException, FileNotExistsException
from automation_file.logging_config import file_automation_logger


def copy_file(file_path: str, target_path: str, copy_metadata: bool = True) -> bool:
    """Copy a single file. Return True on success."""
    source = Path(file_path)
    if not source.is_file():
        file_automation_logger.error("copy_file: source not found: %s", source)
        raise FileNotExistsException(str(source))
    try:
        if copy_metadata:
            shutil.copy2(source, target_path)
        else:
            shutil.copy(source, target_path)
        file_automation_logger.info("copy_file: %s -> %s", source, target_path)
        return True
    except (OSError, shutil.Error) as error:
        file_automation_logger.error("copy_file failed: %r", error)
        return False


def copy_specify_extension_file(
    file_dir_path: str,
    target_extension: str,
    target_path: str,
    copy_metadata: bool = True,
) -> bool:
    """Copy every file under ``file_dir_path`` whose extension matches."""
    source_dir = Path(file_dir_path)
    if not source_dir.is_dir():
        file_automation_logger.error("copy_specify_extension_file: dir not found: %s", source_dir)
        raise DirNotExistsException(str(source_dir))
    extension = target_extension.lstrip(".")
    copied = 0
    for file in source_dir.glob(f"**/*.{extension}"):
        if copy_file(str(file), target_path, copy_metadata=copy_metadata):
            copied += 1
    file_automation_logger.info(
        "copy_specify_extension_file: copied %d *.%s from %s to %s",
        copied, extension, source_dir, target_path,
    )
    return True


def copy_all_file_to_dir(dir_path: str, target_dir_path: str) -> bool:
    """Move a directory into another directory."""
    source = Path(dir_path)
    destination = Path(target_dir_path)
    if not source.is_dir():
        raise DirNotExistsException(str(source))
    if not destination.is_dir():
        raise DirNotExistsException(str(destination))
    try:
        shutil.move(str(source), str(destination))
        file_automation_logger.info("copy_all_file_to_dir: %s -> %s", source, destination)
        return True
    except (OSError, shutil.Error) as error:
        file_automation_logger.error("copy_all_file_to_dir failed: %r", error)
        return False


def rename_file(
    origin_file_path: str,
    target_name: str,
    file_extension: str | None = None,
) -> bool:
    """Rename every matching file under ``origin_file_path`` to ``target_name_{i}``.

    The original implementation renamed every match to the same name, which
    silently overwrote previous renames. Each file now gets a unique suffix.
    """
    source_dir = Path(origin_file_path)
    if not source_dir.is_dir():
        raise DirNotExistsException(str(source_dir))

    pattern = "**/*" if file_extension is None else f"**/*.{file_extension.lstrip('.')}"
    matches = [p for p in source_dir.glob(pattern) if p.is_file()]

    try:
        for index, file in enumerate(matches):
            new_path = file.with_name(f"{target_name}_{index}{file.suffix}")
            file.rename(new_path)
            file_automation_logger.info("rename_file: %s -> %s", file, new_path)
        return True
    except OSError as error:
        file_automation_logger.error(
            "rename_file failed: source=%s target=%s ext=%s error=%r",
            source_dir, target_name, file_extension, error,
        )
        return False


def remove_file(file_path: str) -> bool:
    """Delete a file if it exists. Return True when a file was removed."""
    path = Path(file_path)
    if not path.is_file():
        return False
    path.unlink(missing_ok=True)
    file_automation_logger.info("remove_file: %s", path)
    return True


def create_file(file_path: str, content: str = "", encoding: str = "utf-8") -> None:
    """Create a file with the given text content (overwrites existing file)."""
    with open(file_path, "w", encoding=encoding) as file:
        file.write(content)
    file_automation_logger.info("create_file: %s (%d bytes)", file_path, len(content))
