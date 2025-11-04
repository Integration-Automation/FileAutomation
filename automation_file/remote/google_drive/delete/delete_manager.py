from typing import Union, Dict

from googleapiclient.errors import HttpError

# 匯入 Google Drive 驅動實例與日誌工具
# Import Google Drive driver instance and logging utility
from automation_file.remote.google_drive.driver_instance import driver_instance
from automation_file.utils.logging.loggin_instance import file_automation_logger


def drive_delete_file(file_id: str) -> Union[Dict[str, str], None]:
    """
    刪除 Google Drive 上的檔案
    Delete a file from Google Drive
    :param file_id: Google Drive 檔案 ID (str)
                    Google Drive file ID (str)
    :return: 若成功，回傳刪除結果 (Dict)，否則回傳 None
             Return deletion result (Dict) if success, else None
    """
    try:
        # 呼叫 Google Drive API 刪除檔案
        # Call Google Drive API to delete file
        file = driver_instance.service.files().delete(fileId=file_id).execute()

        # 記錄刪除成功的訊息
        # Log successful deletion
        file_automation_logger.info(f"Delete drive file: {file_id}")
        return file

    except HttpError as error:
        # 捕捉 Google API 錯誤並記錄
        # Catch Google API error and log it
        file_automation_logger.error(
            f"Delete file failed, error: {error}"
        )
        return None