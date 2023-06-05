from googleapiclient.errors import HttpError

from file_automation.remote.google_drive.driver_instance import driver_instance


def share_file_to_user(
        file_id: str, user: str, user_role: str = "writer"):
    try:
        service = driver_instance.service
        user_permission = {
            "type": "user",
            "role": user_role,
            "emailAddress": user
        }
        return service.permissions().create(
            fileId=file_id,
            body=user_permission,
            fields='id', ).execute()
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None


def share_file_to_anyone(file_id: str, share_role: str = "reader"):
    try:
        service = driver_instance.service
        user_permission = {
            "type": "anyone",
            "value": "anyone",
            "role": share_role
        }
        return service.permissions().create(
            fileId=file_id,
            body=user_permission,
            fields='id', ).execute()
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None


def share_file_to_domain(
        file_id: str, domain: str, domain_role: str = "reader"):
    try:
        service = driver_instance.service
        domain_permission = {
            "type": "domain",
            "role": domain_role,
            "domain": domain
        }
        return service.permissions().create(
            fileId=file_id,
            body=domain_permission,
            fields='id', ).execute()
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None
