template_keyword_1: list = [
    ["create_dir", {"dir_path": "test_dir"}],
    ["create_file", {"file_path": "test.txt", "content": "test"}]
]

template_keyword_2: list = [
    ["remove_file", {"file_path": "text.txt"}],
    ["remove_dir_tree", {"remove_dir_tree": "test_dir"}]
]

bad_template_1 = [
    ["add_package_to_executor", ["os"]],
    ["os_system", ["python --version"]],
    ["os_system", ["python -m pip --version"]],
]
