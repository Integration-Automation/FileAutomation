from typing import Union

from googleapiclient.errors import HttpError

# 匯入 Google Drive 驅動實例與日誌工具
# Import Google Drive driver instance and logging utility
from automation_file.remote.google_drive.driver_instance import driver_instance
from automation_file.utils.logging.loggin_instance import file_automation_logger


def drive_share_file_to_user(
        file_id: str, user: str, user_role: str = "writer") -> Union[dict, None]:
    """
    分享檔案給指定使用者
    Share a file with a specific user
    :param file_id: 要分享的檔案 ID (str)
                    File ID to share (str)
    :param user: 使用者的 email (str)
                 User email address (str)
    :param user_role: 權限角色 (預設 writer)
                      Permission role (default writer)
    :return: 成功回傳 dict，失敗回傳 None
             Return dict if success, else None
    """
    try:
        service = driver_instance.service
        user_permission = {
            "type": "user",
            "role": user_role,
            "emailAddress": user
        }
        file_automation_logger.info(
            f"Share file: {file_id}, to user: {user}, with user role: {user_role}"
        )
        return service.permissions().create(
            fileId=file_id,
            body=user_permission,
            fields='id',
        ).execute()
    except HttpError as error:
        file_automation_logger.error(
            f"Share file failed, error: {error}"
        )
        return None


def drive_share_file_to_anyone(file_id: str, share_role: str = "reader") -> Union[dict, None]:
    """
    分享檔案給任何人（公開連結）
    Share a file with anyone (public link)
    :param file_id: 要分享的檔案 ID (str)
                    File ID to share (str)
    :param share_role: 權限角色 (預設 reader)
                       Permission role (default reader)
    :return: 成功回傳 dict，失敗回傳 None
             Return dict if success, else None
    """
    try:
        service = driver_instance.service
        user_permission = {
            "type": "anyone",
            "value": "anyone",
            "role": share_role
        }
        file_automation_logger.info(
            f"Share file to anyone, file: {file_id} with role: {share_role}"
        )
        return service.permissions().create(
            fileId=file_id,
            body=user_permission,
            fields='id',
        ).execute()
    except HttpError as error:
        file_automation_logger.error(
            f"Share file failed, error: {error}"
        )
        return None


def drive_share_file_to_domain(
        file_id: str, domain: str, domain_role: str = "reader") -> Union[dict, None]:
    """
    分享檔案給指定網域的所有使用者
    Share a file with all users in a specific domain
    :param file_id: 要分享的檔案 ID (str)
                    File ID to share (str)
    :param domain: 網域名稱 (str)，例如 "example.com"
                   Domain name (str), e.g., "example.com"
    :param domain_role: 權限角色 (預設 reader)
                        Permission role (default reader)
    :return: 成功回傳 dict，失敗回傳 None
             Return dict if success, else None
    """
    try:
        service = driver_instance.service
        domain_permission = {
            "type": "domain",
            "role": domain_role,
            "domain": domain
        }
        file_automation_logger.info(
            f"Share file to domain: {domain}, with domain role: {domain_role}"
        )
        return service.permissions().create(
            fileId=file_id,
            body=domain_permission,
            fields='id',
        ).execute()
    except HttpError as error:
        file_automation_logger.error(
            f"Share file failed, error: {error}"
        )
        return None