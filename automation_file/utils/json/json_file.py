import json
from pathlib import Path
from threading import Lock

from automation_file.utils.exception.exception_tags import cant_find_json_error, cant_save_json_error
from automation_file.utils.exception.exceptions import JsonActionException
from automation_file.utils.logging.loggin_instance import file_automation_logger

# 全域鎖，避免多執行緒同時讀寫 JSON 檔案
# Global lock to prevent concurrent read/write on JSON files
_lock = Lock()


def read_action_json(json_file_path: str) -> list:
    """
    讀取 JSON 檔案並回傳內容
    Read a JSON file and return its content

    :param json_file_path: JSON 檔案路徑 (str)
                           Path to JSON file (str)
    :return: JSON 內容 (list)
             JSON content (list)
    """
    _lock.acquire()
    try:
        file_path = Path(json_file_path)
        if file_path.exists() and file_path.is_file():
            file_automation_logger.info(f"Read json file {json_file_path}")
            with open(json_file_path, encoding="utf-8") as read_file:
                return json.load(read_file)
        else:
            # 若檔案不存在，丟出自訂例外
            # Raise custom exception if file not found
            raise JsonActionException(cant_find_json_error)
    except JsonActionException:
        raise
    except Exception as error:
        # 捕捉其他例外並轉換成 JsonActionException
        # Catch other exceptions and raise JsonActionException
        raise JsonActionException(f"{cant_find_json_error}: {repr(error)}")
    finally:
        _lock.release()


def write_action_json(json_save_path: str, action_json: list) -> None:
    """
    將資料寫入 JSON 檔案
    Write data into a JSON file

    :param json_save_path: JSON 檔案儲存路徑 (str)
                           Path to save JSON file (str)
    :param action_json: 要寫入的 JSON 資料 (list)
                        JSON data to write (list)
    :return: None
    """
    _lock.acquire()
    try:
        file_automation_logger.info(f"Write {action_json} as file {json_save_path}")
        with open(json_save_path, "w+", encoding="utf-8") as file_to_write:
            json.dump(action_json, file_to_write, indent=4, ensure_ascii=False)
    except JsonActionException:
        raise
    except Exception as error:
        raise JsonActionException(f"{cant_save_json_error}: {repr(error)}")
    finally:
        _lock.release()