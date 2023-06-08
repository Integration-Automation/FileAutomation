from pathlib import Path
from typing import List, Union, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from file_automation.remote.google_drive.driver_instance import driver_instance
from file_automation.utils.logging.loggin_instance import file_automation_logger


def upload_to_drive(file_path: str, file_name: str = None) -> Union[dict, None]:
    try:
        file_path = Path(file_path)
        if file_path.is_file():
            file_metadata = {
                "name": file_path.name if file_name is None else file_name,
                "mimeType": "*/*"
            }
            media = MediaFileUpload(
                file_path,
                mimetype="*/*",
                resumable=True
            )
            file_id = driver_instance.service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
            ).execute()
            file_automation_logger.info(
                f"Upload file to drive file: {file_path}, "
                f"with name: {file_name}"
            )
            return file_id
        else:
            file_automation_logger.error(
                FileNotFoundError
            )
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None


def upload_to_folder(folder_id: str, file_path: str, file_name: str = None) -> Union[dict, None]:
    try:
        file_path = Path(file_path)
        if file_path.is_file():
            file_metadata = {
                "name": file_path.name if file_name is None else file_name,
                "mimeType": "*/*",
                "parents": [f"{folder_id}"]
            }
            media = MediaFileUpload(
                file_path,
                mimetype="*/*",
                resumable=True
            )
            file_id = driver_instance.service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
            ).execute()
            file_automation_logger.info(
                f"Upload file to folder: {folder_id},"
                f"file_path: {file_path}, "
                f"with name: {file_name}"
            )
            return file_id
        else:
            file_automation_logger.error(
                FileNotFoundError
            )
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None


def upload_dir_to_drive(dir_path: str) -> List[Optional[set]]:
    dir_path = Path(dir_path)
    ids = list()
    if dir_path.is_dir():
        path_list = dir_path.iterdir()
        for path in path_list:
            if path.is_file():
                ids.append(upload_to_drive(str(path.absolute()), path.name))
        file_automation_logger.info(
            f"Upload all file on dir: {dir_path} to drive"
        )
        return ids
    else:
        file_automation_logger.error(
            FileNotFoundError
        )


def upload_dir_to_folder(folder_id: str, dir_path: str) -> List[Optional[set]]:
    dir_path = Path(dir_path)
    ids = list()
    if dir_path.is_dir():
        path_list = dir_path.iterdir()
        for path in path_list:
            if path.is_file():
                ids.append(upload_to_folder(folder_id, str(path.absolute()), path.name))
        file_automation_logger.info(
            f"Upload all file on dir: {dir_path} to folder: {folder_id}"
        )
        return ids
    else:
        file_automation_logger.error(
            FileNotFoundError
        )
