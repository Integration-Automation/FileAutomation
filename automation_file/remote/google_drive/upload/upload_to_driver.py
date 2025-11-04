from pathlib import Path
from typing import List, Union, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# 匯入 Google Drive 驅動實例與日誌工具
# Import Google Drive driver instance and logging utility
from automation_file.remote.google_drive.driver_instance import driver_instance
from automation_file.utils.logging.loggin_instance import file_automation_logger


def drive_upload_to_drive(file_path: str, file_name: str = None) -> Union[dict, None]:
    """
    上傳單一檔案到 Google Drive 根目錄
    Upload a single file to Google Drive root
    :param file_path: 要上傳的檔案路徑 (str)
                      File path to upload (str)
    :param file_name: 在 Google Drive 上的檔案名稱 (可選)
                      File name on Google Drive (optional)
    :return: 成功回傳 dict (包含檔案 ID)，失敗回傳 None
             Return dict (with file ID) if success, else None
    """
    try:
        file_path = Path(file_path)
        if file_path.is_file():
            file_metadata = {
                "name": file_path.name if file_name is None else file_name,
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
            file_automation_logger.info(
                f"Upload file to drive file: {file_path}, with name: {file_name}"
            )
            return file_id
        else:
            # 若檔案不存在，記錄錯誤
            # Log error if file does not exist
            file_automation_logger.error(FileNotFoundError)
    except HttpError as error:
        # ⚠️ 原本寫成 Delete file failed，應改為 Upload file failed
        file_automation_logger.error(
            f"Upload file failed, error: {error}"
        )
        return None


def drive_upload_to_folder(folder_id: str, file_path: str, file_name: str = None) -> Union[dict, None]:
    """
    上傳單一檔案到 Google Drive 指定資料夾
    Upload a single file into a specific Google Drive folder
    :param folder_id: 目標資料夾 ID (str)
                      Target folder ID (str)
    :param file_path: 要上傳的檔案路徑 (str)
                      File path to upload (str)
    :param file_name: 在 Google Drive 上的檔案名稱 (可選)
                      File name on Google Drive (optional)
    :return: 成功回傳 dict (包含檔案 ID)，失敗回傳 None
             Return dict (with file ID) if success, else None
    """
    try:
        file_path = Path(file_path)
        if file_path.is_file():
            file_metadata = {
                "name": file_path.name if file_name is None else file_name,
                "mimeType": "*/*",
                "parents": [f"{folder_id}"]
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
            file_automation_logger.info(
                f"Upload file to folder: {folder_id}, file_path: {file_path}, with name: {file_name}"
            )
            return file_id
        else:
            file_automation_logger.error(FileNotFoundError)
    except HttpError as error:
        file_automation_logger.error(
            f"Upload file failed, error: {error}"
        )
        return None


def drive_upload_dir_to_drive(dir_path: str) -> List[Optional[dict]] | None:
    """
    上傳整個資料夾中的所有檔案到 Google Drive 根目錄
    Upload all files from a local directory to Google Drive root
    :param dir_path: 要上傳的資料夾路徑 (str)
                     Directory path to upload (str)
    :return: 檔案 ID 清單 (List[dict])，或空清單
             List of file IDs (List[dict]) or empty list
    """
    dir_path = Path(dir_path)
    ids = list()
    if dir_path.is_dir():
        path_list = dir_path.iterdir()
        for path in path_list:
            if path.is_file():
                ids.append(drive_upload_to_drive(str(path.absolute()), path.name))
        file_automation_logger.info(
            f"Upload all file on dir: {dir_path} to drive"
        )
        return ids
    else:
        file_automation_logger.error(FileNotFoundError)
        return None


def drive_upload_dir_to_folder(folder_id: str, dir_path: str) -> List[Optional[dict]] | None:
    """
    上傳整個資料夾中的所有檔案到 Google Drive 指定資料夾
    Upload all files from a local directory into a specific Google Drive folder

    :param folder_id: 目標 Google Drive 資料夾 ID (str)
                      Target Google Drive folder ID (str)
    :param dir_path: 本地端要上傳的資料夾路徑 (str)
                     Local directory path to upload (str)
    :return: 檔案 ID 清單 (List[dict])，或 None
             List of file IDs (List[dict]) or None
    """
    dir_path = Path(dir_path)
    ids: List[Optional[dict]] = []

    if dir_path.is_dir():
        path_list = dir_path.iterdir()
        for path in path_list:
            if path.is_file():
                # 呼叫單檔上傳函式 (drive_upload_to_folder)，並收集回傳的檔案 ID
                # Call single-file upload function and collect returned file ID
                ids.append(drive_upload_to_folder(folder_id, str(path.absolute()), path.name))

        file_automation_logger.info(
            f"Upload all files in dir: {dir_path} to folder: {folder_id}"
        )
        return ids
    else:
        # 若資料夾不存在，記錄錯誤
        # Log error if directory does not exist
        file_automation_logger.error(FileNotFoundError)

    return None

