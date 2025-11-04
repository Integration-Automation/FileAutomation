import shutil
import sys
from pathlib import Path

# 匯入自訂例外與日誌工具
# Import custom exceptions and logging utility
from automation_file.utils.exception.exceptions import FileNotExistsException, DirNotExistsException
from automation_file.utils.logging.loggin_instance import file_automation_logger


def copy_file(file_path: str, target_path: str, copy_metadata: bool = True) -> bool:
    """
    複製單一檔案
    Copy a single file
    :param file_path: 要複製的檔案路徑 (str)
                      File path to copy (str)
    :param target_path: 複製到的目標路徑 (str)
                        Target path (str)
    :param copy_metadata: 是否複製檔案的中繼資料 (預設 True)
                          Whether to copy file metadata (default True)
    :return: 成功回傳 True，失敗回傳 False
             Return True if success, else False
    """
    file_path = Path(file_path)
    if file_path.is_file() and file_path.exists():
        try:
            if copy_metadata:
                shutil.copy2(file_path, target_path)  # 複製檔案與中繼資料 / Copy file with metadata
            else:
                shutil.copy(file_path, target_path)   # 只複製檔案內容 / Copy file only
            file_automation_logger.info(f"Copy file origin path: {file_path}, target path : {target_path}")
            return True
        except shutil.Error as error:
            file_automation_logger.error(f"Copy file failed: {repr(error)}")
    else:
        file_automation_logger.error(f"Copy file failed: {repr(FileNotExistsException)}")
        return False
    return False


def copy_specify_extension_file(
        file_dir_path: str, target_extension: str, target_path: str, copy_metadata: bool = True) -> bool:
    """
    複製指定副檔名的檔案
    Copy files with a specific extension
    :param file_dir_path: 要搜尋的資料夾路徑 (str)
                          Directory path to search (str)
    :param target_extension: 要搜尋的副檔名 (str)
                             File extension to search (str)
    :param target_path: 複製到的目標路徑 (str)
                        Target path (str)
    :param copy_metadata: 是否複製檔案中繼資料 (bool)
                          Whether to copy metadata (bool)
    :return: 成功回傳 True，失敗回傳 False
             Return True if success, else False
    """
    file_dir_path = Path(file_dir_path)
    if file_dir_path.exists() and file_dir_path.is_dir():
        for file in file_dir_path.glob(f"**/*.{target_extension}"):  # 遞迴搜尋指定副檔名 / Recursively search files
            copy_file(str(file), target_path, copy_metadata=copy_metadata)
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
    將整個資料夾移動到目標資料夾
    Move entire directory into target directory
    :param dir_path: 要移動的資料夾路徑 (str)
                     Directory path to move (str)
    :param target_dir_path: 目標資料夾路徑 (str)
                            Target directory path (str)
    :return: 成功回傳 True，失敗回傳 False
             Return True if success, else False
    """
    dir_path = Path(dir_path)
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir() and target_dir_path.is_dir():
        try:
            shutil.move(str(dir_path), str(target_dir_path))  # 移動資料夾 / Move directory
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
    return False


def rename_file(origin_file_path, target_name: str, file_extension=None) -> bool:
    """
    重新命名資料夾內的檔案
    Rename files inside a directory
    :param origin_file_path: 要搜尋檔案的資料夾路徑 (str)
                             Directory path to search (str)
    :param target_name: 新的檔案名稱 (str)
                        New file name (str)
    :param file_extension: 指定副檔名 (可選) (str)
                           File extension filter (optional) (str)
    :return: 成功回傳 True，失敗回傳 False
             Return True if success, else False
    """
    origin_file_path = Path(origin_file_path)
    if origin_file_path.exists() and origin_file_path.is_dir():
        if file_extension is None:
            file_list = list(origin_file_path.glob("**/*"))  # 全部檔案 / All files
        else:
            file_list = list(origin_file_path.glob(f"**/*.{file_extension}"))  # 指定副檔名 / Specific extension
        try:
            file_index = 0
            for file in file_list:
                file.rename(Path(origin_file_path, target_name))  # 重新命名檔案 / Rename file
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
    return False


def remove_file(file_path: str) -> None:
    """
    刪除檔案
    Remove a file
    :param file_path: 要刪除的檔案路徑 (str)
                      File path to remove (str)
    :return: None
    """
    file_path = Path(file_path)
    if file_path.exists() and file_path.is_file():
        file_path.unlink(missing_ok=True)  # 刪除檔案，若不存在則忽略 / Delete file, ignore if missing
        file_automation_logger.info(f"Remove file, file path: {file_path}")


def create_file(file_path: str, content: str) -> None:
    """
    建立檔案並寫入內容
    Create a file and write content
    :param file_path: 檔案路徑 (str)
                      File path (str)
    :param content: 要寫入的內容 (str)
                    Content to write (str)
    :return: None
    """
    with open(file_path, "w+") as file:  # "w+" 表示寫入模式，若不存在則建立 / "w+" means write mode, create if not exists
        file.write(content)