import io

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from file_automation.remote.google_drive.driver_instance import driver_instance


def download_file(file_id: str, file_name: str):
    try:
        request = driver_instance.service.files().get_media(fileId=file_id)
        file = io.BytesIO()
        downloader = MediaIoBaseDownload(file, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            print(F'Download {int(status.progress() * 100)}.')
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None
    with open(file_name, "wb") as output_file:
        output_file.write(file.getbuffer())
    return file
