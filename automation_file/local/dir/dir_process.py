import shutil
from pathlib import Path

# 匯入自訂例外與日誌工具
# Import custom exception and logging utility
from automation_file.utils.exception.exceptions import DirNotExistsException
from automation_file.utils.logging.loggin_instance import file_automation_logger


def copy_dir(dir_path: str, target_dir_path: str) -> bool:
    """
    複製資料夾到目標路徑
    Copy directory to target path
    :param dir_path: 要複製的資料夾路徑 (str)
                     Directory path to copy (str)
    :param target_dir_path: 複製到的目標資料夾路徑 (str)
                            Target directory path (str)
    :return: 成功回傳 True，失敗回傳 False
             Return True if success, else False
    """
    dir_path = Path(dir_path)  # 轉換為 Path 物件 / Convert to Path object
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir():  # 確認來源是否為資料夾 / Check if source is a directory
        try:
            # 複製整個資料夾，若目標已存在則允許覆蓋
            # Copy entire directory, allow overwrite if target exists
            shutil.copytree(dir_path, target_dir_path, dirs_exist_ok=True)
            file_automation_logger.info(f"Copy dir {dir_path}")
            return True
        except shutil.Error as error:
            # 複製失敗時記錄錯誤
            # Log error if copy fails
            file_automation_logger.error(f"Copy dir {dir_path} failed: {repr(error)}")
    else:
        # 若來源資料夾不存在，記錄錯誤
        # Log error if source directory does not exist
        file_automation_logger.error(f"Copy dir {dir_path} failed: {repr(DirNotExistsException)}")
        return False
    return False


def remove_dir_tree(dir_path: str) -> bool:
    """
    刪除整個資料夾樹
    Remove entire directory tree
    :param dir_path: 要刪除的資料夾路徑 (str)
                     Directory path to remove (str)
    :return: 成功回傳 True，失敗回傳 False
             Return True if success, else False
    """
    dir_path = Path(dir_path)
    if dir_path.is_dir():  # 確認是否為資料夾 / Check if directory exists
        try:
            shutil.rmtree(dir_path)  # 遞迴刪除資料夾 / Recursively delete directory
            file_automation_logger.info(f"Remove dir tree {dir_path}")
            return True
        except shutil.Error as error:
            file_automation_logger.error(f"Remove dir tree {dir_path} error: {repr(error)}")
            return False
    return False


def rename_dir(origin_dir_path, target_dir: str) -> bool:
    """
    重新命名資料夾
    Rename directory
    :param origin_dir_path: 原始資料夾路徑 (str)
                            Original directory path (str)
    :param target_dir: 新的完整路徑 (str)
                       Target directory path (str)
    :return: 成功回傳 True，失敗回傳 False
             Return True if success, else False
    """
    origin_dir_path = Path(origin_dir_path)
    if origin_dir_path.exists() and origin_dir_path.is_dir():
        try:
            # 使用 Path.rename 重新命名資料夾
            # Rename directory using Path.rename
            Path.rename(origin_dir_path, target_dir)
            file_automation_logger.info(
                f"Rename dir origin dir path: {origin_dir_path}, target dir path: {target_dir}")
            return True
        except Exception as error:
            # 捕捉所有例外並記錄
            # Catch all exceptions and log
            file_automation_logger.error(
                f"Rename dir error:  {repr(error)}, "
                f"Rename dir origin dir path: {origin_dir_path}, "
                f"target dir path: {target_dir}")
    else:
        # 若來源資料夾不存在，記錄錯誤
        # Log error if source directory does not exist
        file_automation_logger.error(
            f"Rename dir error:  {repr(DirNotExistsException)}, "
            f"Rename dir origin dir path: {origin_dir_path}, "
            f"target dir path: {target_dir}")
        return False
    return False


def create_dir(dir_path: str) -> None:
    """
    建立資料夾
    Create directory
    :param dir_path: 要建立的資料夾路徑 (str)
                     Directory path to create (str)
    :return: None
    """
    dir_path = Path(dir_path)
    # 若資料夾已存在則不會報錯
    # Create directory, no error if already exists
    dir_path.mkdir(exist_ok=True)
    file_automation_logger.info(f"Create dir {dir_path}")