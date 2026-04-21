"""Permission / share operations on Google Drive."""

from __future__ import annotations

from googleapiclient.errors import HttpError

from automation_file.logging_config import file_automation_logger
from automation_file.remote.google_drive.client import driver_instance


def _create_permission(file_id: str, body: dict, description: str) -> dict | None:
    try:
        response = (
            driver_instance.require_service()
            .permissions()
            .create(fileId=file_id, body=body, fields="id")
            .execute()
        )
        file_automation_logger.info("drive_share (%s): file=%s", description, file_id)
        return response
    except HttpError as error:
        file_automation_logger.error("drive_share (%s) failed: %r", description, error)
        return None


def drive_share_file_to_user(file_id: str, user: str, user_role: str = "writer") -> dict | None:
    body = {"type": "user", "role": user_role, "emailAddress": user}
    return _create_permission(file_id, body, f"user={user},role={user_role}")


def drive_share_file_to_anyone(file_id: str, share_role: str = "reader") -> dict | None:
    body = {"type": "anyone", "role": share_role}
    return _create_permission(file_id, body, f"anyone,role={share_role}")


def drive_share_file_to_domain(
    file_id: str, domain: str, domain_role: str = "reader"
) -> dict | None:
    body = {"type": "domain", "role": domain_role, "domain": domain}
    return _create_permission(file_id, body, f"domain={domain},role={domain_role}")
