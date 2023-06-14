import shutil
import sys
from pathlib import Path

from file_automation.utils.exception.exceptions import DirNotExistsException
from file_automation.utils.logging.loggin_instance import file_automation_logger


def copy_dir(dir_path: str, target_dir_path: str) -> None:
    dir_path = Path(dir_path)
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir():
        try:
            shutil.copytree(dir_path, target_dir_path, dirs_exist_ok=True)
            file_automation_logger.info(f"Copy dir {dir_path}")
        except shutil.Error as error:
            file_automation_logger.error(f"Copy dir {dir_path} failed: {repr(error)}")
    else:
        file_automation_logger.error(f"Copy dir {dir_path} failed: {repr(DirNotExistsException)}")


def remove_dir_tree(dir_path: str) -> None:
    dir_path = Path(dir_path)
    if dir_path.is_dir():
        try:
            shutil.rmtree(dir_path)
            file_automation_logger.info(f"Remove dir tree {dir_path}")
        except shutil.Error as error:
            file_automation_logger.error(f"Remove dir tree {dir_path} error: {repr(error)}")


def rename_dir(origin_dir_path, target_dir: str) -> None:
    origin_dir_path = Path(origin_dir_path)
    if origin_dir_path.exists() and origin_dir_path.is_dir():
        try:
            Path.rename(origin_dir_path, target_dir)
            file_automation_logger.info(
                f"Rename dir origin dir path: {origin_dir_path}, target dir path: {target_dir}")
        except Exception as error:
            file_automation_logger.error(
                f"Rename dir error:  {repr(error)}, "
                f"Rename dir origin dir path: {origin_dir_path}, "
                f"target dir path: {target_dir}")
    else:
        file_automation_logger.error(
            f"Rename dir error:  {repr(DirNotExistsException)}, "
            f"Rename dir origin dir path: {origin_dir_path}, "
            f"target dir path: {target_dir}")


def create_dir(dir_path: str) -> None:
    dir_path = Path(dir_path)
    dir_path.mkdir(exist_ok=True)
    file_automation_logger.info(f"Create dir {dir_path}")
