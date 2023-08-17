import shutil
from pathlib import Path

from automation_file.utils.exception.exceptions import DirNotExistsException
from automation_file.utils.logging.loggin_instance import file_automation_logger


def copy_dir(dir_path: str, target_dir_path: str) -> bool:
    """
    Copy dir to target path (path need as dir path)
    :param dir_path: which dir do we want to copy (str path)
    :param target_dir_path: copy dir to this path
    :return: True if success else False
    """
    dir_path = Path(dir_path)
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir():
        try:
            shutil.copytree(dir_path, target_dir_path, dirs_exist_ok=True)
            file_automation_logger.info(f"Copy dir {dir_path}")
            return True
        except shutil.Error as error:
            file_automation_logger.error(f"Copy dir {dir_path} failed: {repr(error)}")
    else:
        file_automation_logger.error(f"Copy dir {dir_path} failed: {repr(DirNotExistsException)}")
        return False


def remove_dir_tree(dir_path: str) -> bool:
    """
    :param dir_path: which dir do we want to remove (str path)
    :return: True if success else False
    """
    dir_path = Path(dir_path)
    if dir_path.is_dir():
        try:
            shutil.rmtree(dir_path)
            file_automation_logger.info(f"Remove dir tree {dir_path}")
            return True
        except shutil.Error as error:
            file_automation_logger.error(f"Remove dir tree {dir_path} error: {repr(error)}")
            return False


def rename_dir(origin_dir_path, target_dir: str) -> bool:
    """
    :param origin_dir_path: which dir do we want to rename (str path)
    :param target_dir: target name as str full path
    :return: True if success else False
    """
    origin_dir_path = Path(origin_dir_path)
    if origin_dir_path.exists() and origin_dir_path.is_dir():
        try:
            Path.rename(origin_dir_path, target_dir)
            file_automation_logger.info(
                f"Rename dir origin dir path: {origin_dir_path}, target dir path: {target_dir}")
            return True
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
        return False


def create_dir(dir_path: str) -> None:
    """
    :param dir_path: create dir on dir_path
    :return: None
    """
    dir_path = Path(dir_path)
    dir_path.mkdir(exist_ok=True)
    file_automation_logger.info(f"Create dir {dir_path}")
