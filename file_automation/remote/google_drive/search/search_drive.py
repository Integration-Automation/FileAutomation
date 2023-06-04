from file_automation.remote.google_drive.driver_instance import driver_instance


def search_all_file():
    item = dict()
    response = driver_instance.service.files().list().execute()
    for file in response.get("files", []):
        item.update({file.get("name"): file.get("id")})
    return item
