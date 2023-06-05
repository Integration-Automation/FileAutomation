from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from file_automation.remote.google_drive.driver_instance import driver_instance


def upload_to_drive(file_name: str, file_path: str):
    try:
        if Path(file_path).is_file():
            file_metadata = {
                "name": file_name,
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
            return file_id
        return False
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None
