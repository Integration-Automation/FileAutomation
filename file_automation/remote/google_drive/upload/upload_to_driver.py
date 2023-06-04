from pathlib import Path

from file_automation.remote.google_drive.driver_instance import driver_instance


def upload_to_dir(file_path: str, upload_folder_id: str):
    file_path = Path(file_path)
    if driver_instance.service and file_path.is_file():
        file_metadata = {
            'name': file_path.name,
            'parents': [upload_folder_id]
        }
