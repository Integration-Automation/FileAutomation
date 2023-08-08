import io
from io import BytesIO
from typing import Union

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from automation_file.remote.google_drive.driver_instance import driver_instance
from automation_file.utils.logging.loggin_instance import file_automation_logger


def drive_download_file(file_id: str, file_name: str) -> BytesIO:
    try:
        request = driver_instance.service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            file_automation_logger.info(
                f"Download {file_name} {int(status.progress() * 100)}%."
            )
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None
    with open(file_name, "wb") as output_file:
        output_file.write(file.getbuffer())
    file_automation_logger.info(
        f"Download file: {file_id} with name: {file_name}"
    )
    return file


def drive_download_file_from_folder(folder_name: str) -> Union[dict, None]:
    try:
        files = dict()
        response = driver_instance.service.files().list(
            q=f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}'"
        ).execute()
        folder = response.get("files", [])[0]
        folder_id = folder.get("id")
        response = driver_instance.service.files().list(
            q=f"'{folder_id}' in parents"
        ).execute()
        for file in response.get("files", []):
            drive_download_file(file.get("id"), file.get("name"))
            files.update({file.get("name"): file.get("id")})
        file_automation_logger.info(
            f"Download all file on {folder_name} done."
        )
        return files
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None
