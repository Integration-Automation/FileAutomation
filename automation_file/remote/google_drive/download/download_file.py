import io
from io import BytesIO
from typing import Union

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

# 匯入 Google Drive 驅動實例與日誌工具
# Import Google Drive driver instance and logging utility
from automation_file.remote.google_drive.driver_instance import driver_instance
from automation_file.utils.logging.loggin_instance import file_automation_logger


def drive_download_file(file_id: str, file_name: str) -> Union[BytesIO, None]:
    """
    從 Google Drive 下載單一檔案
    Download a single file from Google Drive
    :param file_id: Google Drive 檔案 ID (str)
                    Google Drive file ID (str)
    :param file_name: 本地端儲存檔案名稱 (str)
                      Local file name to save as (str)
    :return: BytesIO 物件 (檔案內容) 或 None
             BytesIO object (file content) or None
    """
    try:
        # 建立下載請求
        # Create download request
        request = driver_instance.service.files().get_media(fileId=file_id)

        # 使用 BytesIO 暫存檔案內容
        # Use BytesIO to temporarily store file content
        file = io.BytesIO()

        # 建立下載器
        # Create downloader
        downloader = MediaIoBaseDownload(file, request)
        done = False

        # 逐區塊下載檔案，直到完成
        # Download file in chunks until done
        while done is False:
            status, done = downloader.next_chunk()
            file_automation_logger.info(
                f"Download {file_name} {int(status.progress() * 100)}%."
            )

    except HttpError as error:
        file_automation_logger.error(
            f"Download file failed, error: {error}"
        )
        return None

    # 將下載完成的檔案寫入本地端
    # Save downloaded file to local storage
    with open(file_name, "wb") as output_file:
        output_file.write(file.getbuffer())

    file_automation_logger.info(
        f"Download file: {file_id} with name: {file_name}"
    )
    return file


def drive_download_file_from_folder(folder_name: str) -> Union[dict, None]:
    """
    從 Google Drive 指定資料夾下載所有檔案
    Download all files from a specific Google Drive folder
    :param folder_name: 資料夾名稱 (str)
                        Folder name (str)
    :return: 檔案名稱與 ID 的字典，或 None
             Dictionary of file names and IDs, or None
    """
    try:
        files = dict()

        # 先找到指定名稱的資料夾
        # Find the folder by name
        response = driver_instance.service.files().list(
            q=f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}'"
        ).execute()

        folder = response.get("files", [])[0]
        folder_id = folder.get("id")

        # 列出該資料夾下的所有檔案
        # List all files inside the folder
        response = driver_instance.service.files().list(
            q=f"'{folder_id}' in parents"
        ).execute()

        # 逐一下載檔案
        # Download each file
        for file in response.get("files", []):
            drive_download_file(file.get("id"), file.get("name"))
            files.update({file.get("name"): file.get("id")})

        file_automation_logger.info(
            f"Download all file on {folder_name} done."
        )
        return files

    except HttpError as error:
        file_automation_logger.error(
            f"Download file failed, error: {error}"
        )
        return None