import shutil
import sys
from pathlib import Path

from automation_file.utils.exception.exceptions import FileNotExistsException, DirNotExistsException
from automation_file.utils.logging.loggin_instance import file_automation_logger


def copy_file(file_path: str, target_path: str) -> bool:
    """
    :param file_path: which file do we want to copy (str path)
    :param target_path: put copy file on target path
    :return: True if success else False
    """
    file_path = Path(file_path)
    if file_path.is_file() and file_path.exists():
        try:
            shutil.copy2(file_path, target_path)
            file_automation_logger.info(f"Copy file origin path: {file_path}, target path : {target_path}")
            return True
        except shutil.Error as error:
            file_automation_logger.error(f"Copy file failed: {repr(error)}")
    else:
        file_automation_logger.error(f"Copy file failed: {repr(FileNotExistsException)}")
        return False


def copy_specify_extension_file(file_dir_path: str, target_extension: str, target_path: str) -> bool:
    """
    :param file_dir_path: which dir do we want to search
    :param target_extension: what extension we will search
    :param target_path: copy file to target path
    :return: True if success else False
    """
    file_dir_path = Path(file_dir_path)
    if file_dir_path.exists() and file_dir_path.is_dir():
        for file in file_dir_path.glob(f"**/*.{target_extension}"):
            copy_file(str(file), target_path)
            file_automation_logger.info(
                f"Copy specify extension file on dir"
                f"origin dir path: {file_dir_path}, target extension: {target_extension}, "
                f"to target path {target_path}")
        return True
    else:
        file_automation_logger.error(
            f"Copy specify extension file failed: {repr(FileNotExistsException)}")
        return False


def copy_all_file_to_dir(dir_path: str, target_dir_path: str) -> bool:
    """
    :param dir_path: copy all file on dir
    :param target_dir_path: put file to target dir
    :return: True if success else False
    """
    dir_path = Path(dir_path)
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir() and target_dir_path.is_dir():
        try:
            shutil.move(str(dir_path), str(target_dir_path))
            file_automation_logger.info(
                f"Copy all file to dir, "
                f"origin dir: {dir_path}, "
                f"target dir: {target_dir_path}"
            )
            return True
        except shutil.Error as error:
            file_automation_logger.error(
                f"Copy all file to dir failed, "
                f"origin dir: {dir_path}, "
                f"target dir: {target_dir_path}, "
                f"error: {repr(error)}"
            )
    else:
        print(repr(DirNotExistsException), file=sys.stderr)
        return False


def rename_file(origin_file_path, target_name: str, file_extension=None) -> bool:
    """
    :param origin_file_path: which dir do we want to search file
    :param target_name: rename file to target name
    :param file_extension: Which extension do we search
    :return: True if success else False
    """
    origin_file_path = Path(origin_file_path)
    if origin_file_path.exists() and origin_file_path.is_dir():
        if file_extension is None:
            file_list = list(origin_file_path.glob("**/*"))
        else:
            file_list = list(origin_file_path.glob(f"**/*.{file_extension}"))
        try:
            file_index = 0
            for file in file_list:
                file.rename(Path(origin_file_path,  target_name))
                file_index = file_index + 1
                file_automation_logger.info(
                    f"Renamed file: origin file path:{origin_file_path}, with new name: {target_name}")
            return True
        except Exception as error:
            file_automation_logger.error(
                f"Rename file failed, "
                f"origin file path: {origin_file_path}, "
                f"target name: {target_name}, "
                f"file_extension: {file_extension}, "
                f"error: {repr(error)}"
            )
    else:
        file_automation_logger.error(
            f"Rename file failed, error: {repr(DirNotExistsException)}")
        return False


def remove_file(file_path: str) -> None:
    """
    :param file_path: which file do we want to remove
    :return: None
    """
    file_path = Path(file_path)
    if file_path.exists() and file_path.is_file():
        file_path.unlink(missing_ok=True)
        file_automation_logger.info(f"Remove file, file path: {file_path}")


def create_file(file_path: str, content: str) -> None:
    """
    :param file_path: create file on path
    :param content: what content will write to file
    :return: None
    """
    with open(file_path, "w+") as file:
        file.write(content)
