from typing import Union

from googleapiclient.errors import HttpError

from file_automation.remote.google_drive.driver_instance import driver_instance
from file_automation.utils.logging.loggin_instance import file_automation_logger


def drive_add_folder(folder_name: str) -> Union[dict, None]:
    try:
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        file = driver_instance.service.files().create(
            body=file_metadata,
            fields="id"
        ).execute()
        file_automation_logger.info(
            f"Add drive folder: {folder_name}"
        )
        return file.get("id")
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None
