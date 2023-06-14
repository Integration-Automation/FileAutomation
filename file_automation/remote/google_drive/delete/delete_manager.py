from typing import Union

from googleapiclient.errors import HttpError

from file_automation.remote.google_drive.driver_instance import driver_instance
from file_automation.utils.logging.loggin_instance import file_automation_logger


def drive_delete_file(file_id: str) -> Union[dict, None]:
    try:
        file = driver_instance.service.files().delete(fileId=file_id).execute()
        file_automation_logger.info(f"Delete drive file: {file_id}")
        return file
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None
