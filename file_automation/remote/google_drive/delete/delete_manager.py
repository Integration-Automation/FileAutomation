from googleapiclient.errors import HttpError

from file_automation.remote.google_drive.driver_instance import driver_instance


def delete_file(file_id: str):
    try:
        file = driver_instance.service.files().delete(fileId=file_id).execute()
        return file
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None
