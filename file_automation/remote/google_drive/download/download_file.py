import io
from io import BytesIO
from typing import Union

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from file_automation.remote.google_drive.driver_instance import driver_instance


def download_file(file_id: str, file_name: str) -> BytesIO:
    try:
        request = driver_instance.service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            print(f"Download {file_name} {int(status.progress() * 100)}%.")
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None
    with open(file_name, "wb") as output_file:
        output_file.write(file.getbuffer())
    return file


def download_file_from_folder(folder_name: str) -> Union[dict, None]:
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
            download_file(file.get("id"), file.get("name"))
            files.update({file.get("name"): file.get("id")})
        return files
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None
