from googleapiclient.errors import HttpError

from file_automation.remote.google_drive.driver_instance import driver_instance


def add_folder(folder_name: str):
    try:
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        file = driver_instance.service.files().create(
            body=file_metadata,
            fields="id"
        ).execute()
        return file.get("id")
    except HttpError as error:
        print(F'An error occurred: {error}')
        return None
