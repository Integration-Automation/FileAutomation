"""Project scaffolding templates (keyword JSON + Python entry points)."""
from __future__ import annotations

EXECUTOR_ONE_FILE_TEMPLATE: str = '''\
from automation_file import execute_action, read_action_json

execute_action(
    read_action_json(
        r"{keyword_json}"
    )
)
'''

EXECUTOR_FOLDER_TEMPLATE: str = '''\
from automation_file import execute_files, get_dir_files_as_list

execute_files(
    get_dir_files_as_list(
        r"{keyword_dir}"
    )
)
'''

KEYWORD_CREATE_TEMPLATE: list = [
    ["FA_create_dir", {"dir_path": "test_dir"}],
    ["FA_create_file", {"file_path": "test.txt", "content": "test"}],
]

KEYWORD_TEARDOWN_TEMPLATE: list = [
    ["FA_remove_file", {"file_path": "test.txt"}],
    ["FA_remove_dir_tree", {"dir_path": "test_dir"}],
]
