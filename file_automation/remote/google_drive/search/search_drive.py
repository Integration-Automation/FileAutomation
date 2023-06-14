from typing import Union

from googleapiclient.errors import HttpError

from file_automation.remote.google_drive.driver_instance import driver_instance
from file_automation.utils.logging.loggin_instance import file_automation_logger


def drive_search_all_file() -> Union[dict, None]:
    try:
        item = dict()
        response = driver_instance.service.files().list().execute()
        for file in response.get("files", []):
            item.update({file.get("name"): file.get("id")})
        file_automation_logger.info(
            f"Search all file on drive"
        )
        return item
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None


def drive_search_file_mimetype(mime_type: str) -> Union[dict, None]:
    try:
        files = dict()
        page_token = None
        while True:
            # pylint: disable=maybe-no-member
            response = driver_instance.service.files().list(
                q=f"mimeType='{mime_type}'",
                fields="nextPageToken, files(id, name)",
                pageToken=page_token).execute()
            for file in response.get("files", []):
                files.update({file.get("name"): file.get("id")})
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        file_automation_logger.info(
            f"Search all {mime_type} file on drive"
        )
        return files
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None


def drive_search_field(field_pattern: str) -> Union[dict, None]:
    try:
        files = dict()
        response = driver_instance.service.files().list(fields=field_pattern).execute()
        for file in response.get("files", []):
            files.update({file.get("name"): file.get("id")})
        file_automation_logger.info(
            f"Search all {field_pattern}"
        )
        return files
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None

