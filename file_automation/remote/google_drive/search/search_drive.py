from typing import Union

from googleapiclient.errors import HttpError

from file_automation.remote.google_drive.driver_instance import driver_instance


def search_all_file() -> Union[dict, None]:
    try:
        item = dict()
        response = driver_instance.service.files().list().execute()
        for file in response.get("files", []):
            item.update({file.get("name"): file.get("id")})
        return item
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None


def search_file_mimetype(mime_type: str) -> Union[dict, None]:
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
        return files
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None


def search_field(field_pattern: str) -> Union[dict, None]:
    try:
        files = dict()
        response = driver_instance.service.files().list(fields=field_pattern).execute()
        for file in response.get("files", []):
            files.update({file.get("name"): file.get("id")})
        return files
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None

