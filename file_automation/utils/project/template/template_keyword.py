template_keyword_1: list = [
    ["FA_create_dir", {"dir_path": "test_dir"}],
    ["FA_create_file", {"file_path": "test.txt", "content": "test"}]
]

template_keyword_2: list = [
    ["FA_remove_file", {"file_path": "text.txt"}],
    ["FA_remove_dir_tree", {"FA_remove_dir_tree": "test_dir"}]
]

bad_template_1 = [
    ["FA_add_package_to_executor", ["os"]],
    ["os_system", ["python --version"]],
    ["os_system", ["python -m pip --version"]],
]
