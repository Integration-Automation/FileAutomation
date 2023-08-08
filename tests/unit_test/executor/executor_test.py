from automation_file import execute_action

test_list = [
    ["FA_drive_later_init", {"token_path": "token.json", "credentials_path": "credentials.json"}],
    ["FA_drive_search_all_file"],
    ["FA_drive_upload_to_drive", {"file_path": "test.txt"}],
    ["FA_drive_add_folder", {"folder_name": "test_folder"}],
    ["FA_drive_search_all_file"]
]

execute_action(test_list)
