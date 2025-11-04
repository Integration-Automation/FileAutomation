from typing import Union

from googleapiclient.errors import HttpError

# 匯入 Google Drive 驅動實例與日誌工具
# Import Google Drive driver instance and logging utility
from automation_file.remote.google_drive.driver_instance import driver_instance
from automation_file.utils.logging.loggin_instance import file_automation_logger


def drive_search_all_file() -> Union[dict, None]:
    """
    搜尋 Google Drive 上的所有檔案
    Search all files on Google Drive
    :return: 檔案名稱與 ID 的字典，或 None
             Dictionary of file names and IDs, or None
    """
    try:
        item = dict()
        # 呼叫 Google Drive API 取得所有檔案
        # Call Google Drive API to list all files
        response = driver_instance.service.files().list().execute()
        for file in response.get("files", []):
            item.update({file.get("name"): file.get("id")})

        file_automation_logger.info("Search all file on drive")
        return item

    except HttpError as error:
        file_automation_logger.error(
            f"Search file failed, error: {error}"
        )
        return None


def drive_search_file_mimetype(mime_type: str) -> Union[dict, None]:
    """
    搜尋 Google Drive 上指定 MIME 類型的檔案
    Search all files with a specific MIME type on Google Drive
    :param mime_type: MIME 類型 (str)
                      MIME type (str)
    :return: 檔案名稱與 ID 的字典，或 None
             Dictionary of file names and IDs, or None
    """
    try:
        files = dict()
        page_token = None
        while True:
            # 呼叫 Google Drive API，依 MIME 類型搜尋檔案
            # Call Google Drive API to search files by MIME type
            response = driver_instance.service.files().list(
                q=f"mimeType='{mime_type}'",
                fields="nextPageToken, files(id, name)",
                pageToken=page_token
            ).execute()

            for file in response.get("files", []):
                files.update({file.get("name"): file.get("id")})

            # 處理分頁結果
            # Handle pagination
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break

        file_automation_logger.info(f"Search all {mime_type} file on drive")
        return files

    except HttpError as error:
        file_automation_logger.error(
            f"Search file failed, error: {error}"
        )
        return None


def drive_search_field(field_pattern: str) -> Union[dict, None]:
    """
    使用自訂欄位模式搜尋檔案
    Search files with a custom field pattern
    :param field_pattern: 欄位模式 (str)
                          Field pattern (str)
    :return: 檔案名稱與 ID 的字典，或 None
             Dictionary of file names and IDs, or None
    """
    try:
        files = dict()
        # 呼叫 Google Drive API，依指定欄位模式搜尋
        # Call Google Drive API with custom field pattern
        response = driver_instance.service.files().list(fields=field_pattern).execute()

        for file in response.get("files", []):
            files.update({file.get("name"): file.get("id")})

        file_automation_logger.info(f"Search all {field_pattern}")
        return files

    except HttpError as error:
        file_automation_logger.error(
            f"Search file failed, error: {error}"
        )
        return None