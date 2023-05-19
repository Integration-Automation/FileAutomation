from pathlib import Path

from file_automation import copy_dir, remove_dir_tree, rename_dir, create_dir

copy_dir_path = Path(str(Path.cwd()) + "/test_dir")
rename_dir_path = Path(str(Path.cwd()) + "/rename_dir")
first_file_dir = Path(str(Path.cwd()) + "/first_file_dir")
second_file_dir = Path(str(Path.cwd()) + "/second_file_dir")


def test_create_dir():
    create_dir(str(copy_dir_path))


def test_copy_dir():
    copy_dir(str(first_file_dir), str(copy_dir_path))


def test_rename_dir():
    rename_dir(str(copy_dir_path), str(rename_dir_path))


def test_remove_dir_tree():
    remove_dir_tree(str(rename_dir_path))


def test():
    test_copy_dir()
    test_rename_dir()
    test_remove_dir_tree()


if __name__ == "__main__":
    test()
