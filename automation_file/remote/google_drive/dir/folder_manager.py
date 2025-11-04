from typing import Union

from googleapiclient.errors import HttpError

# 匯入 Google Drive 驅動實例與日誌工具
# Import Google Drive driver instance and logging utility
from automation_file.remote.google_drive.driver_instance import driver_instance
from automation_file.utils.logging.loggin_instance import file_automation_logger


def drive_add_folder(folder_name: str) -> Union[dict, None]:
    """
    在 Google Drive 建立資料夾
    Create a folder on Google Drive
    :param folder_name: 要建立的資料夾名稱 (str)
                        Folder name to create (str)
    :return: 若成功，回傳資料夾 ID (dict)，否則回傳 None
             Return folder ID (dict) if success, else None
    """
    try:
        # 設定資料夾的中繼資料 (名稱與 MIME 類型)
        # Define folder metadata (name and MIME type)
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }

        # 呼叫 Google Drive API 建立資料夾，並只回傳 id 欄位
        # Call Google Drive API to create folder, return only "id"
        file = driver_instance.service.files().create(
            body=file_metadata,
            fields="id"
        ).execute()

        # 記錄建立成功的訊息
        # Log successful folder creation
        file_automation_logger.info(f"Add drive folder: {folder_name}")

        # 回傳資料夾 ID
        # Return folder ID
        return file.get("id")

    except HttpError as error:
        # 捕捉 Google API 錯誤並記錄
        # Catch Google API error and log it
        file_automation_logger.error(
            f"Add folder failed, error: {error}"
        )
        return None