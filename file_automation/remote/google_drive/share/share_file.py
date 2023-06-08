from typing import Union

from googleapiclient.errors import HttpError

from file_automation.remote.google_drive.driver_instance import driver_instance
from file_automation.utils.logging.loggin_instance import file_automation_logger


def share_file_to_user(
        file_id: str, user: str, user_role: str = "writer") -> Union[dict, None]:
    try:
        service = driver_instance.service
        user_permission = {
            "type": "user",
            "role": user_role,
            "emailAddress": user
        }
        file_automation_logger.info(
            f"Share file: {file_id}, "
            f"to user: {user}, "
            f"with user role: {user_role}"
        )
        return service.permissions().create(
            fileId=file_id,
            body=user_permission,
            fields='id', ).execute()
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None


def share_file_to_anyone(file_id: str, share_role: str = "reader") -> Union[dict, None]:
    try:
        service = driver_instance.service
        user_permission = {
            "type": "anyone",
            "value": "anyone",
            "role": share_role
        }
        file_automation_logger.info(
            f"Share file to anyone file: {file_id} with role: {share_role}"
        )
        return service.permissions().create(
            fileId=file_id,
            body=user_permission,
            fields='id', ).execute()
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None


def share_file_to_domain(
        file_id: str, domain: str, domain_role: str = "reader") -> Union[dict, None]:
    try:
        service = driver_instance.service
        domain_permission = {
            "type": "domain",
            "role": domain_role,
            "domain": domain
        }
        file_automation_logger.info(
            f"Share file to domain: {domain}, "
            f"with domain role: {domain_role}"
        )
        return service.permissions().create(
            fileId=file_id,
            body=domain_permission,
            fields='id', ).execute()
    except HttpError as error:
        file_automation_logger.error(
            f"Delete file failed,"
            f"error: {error}"
        )
        return None
