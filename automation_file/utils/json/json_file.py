import json
from pathlib import Path
from threading import Lock

from automation_file.utils.exception.exception_tags import cant_find_json_error, cant_save_json_error
from automation_file.utils.exception.exceptions import JsonActionException
from automation_file.utils.logging.loggin_instance import file_automation_logger

_lock = Lock()


def read_action_json(json_file_path: str) -> list:
    """
    use to read action file
    :param json_file_path json file's path to read
    """
    _lock.acquire()
    try:
        file_path = Path(json_file_path)
        if file_path.exists() and file_path.is_file():
            file_automation_logger.info(
                f"Read json file {json_file_path}"
            )
            with open(json_file_path) as read_file:
                return json.loads(read_file.read())
    except JsonActionException:
        raise JsonActionException(cant_find_json_error)
    finally:
        _lock.release()


def write_action_json(json_save_path: str, action_json: list) -> None:
    """
    use to save action file
    :param json_save_path  json save path
    :param action_json the json str include action to write
    """
    _lock.acquire()
    try:
        file_automation_logger.info(
            f"Write {action_json} as file {json_save_path}"
        )
        with open(json_save_path, "w+") as file_to_write:
            file_to_write.write(json.dumps(action_json, indent=4))
    except JsonActionException:
        raise JsonActionException(cant_save_json_error)
    finally:
        _lock.release()
