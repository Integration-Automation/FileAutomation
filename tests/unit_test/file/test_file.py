from pathlib import Path

from file_automation import copy_file, copy_specify_extension_file, copy_all_file_to_dir, rename_file, remove_file

first_file_dir = Path(str(Path.cwd()) + "/first_file_dir")
second_file_dir = Path(str(Path.cwd()) + "/second_file_dir")
test_file_dir = Path(str(Path.cwd()) + "/test_file")
test_file_path = Path(str(Path.cwd()) + "/test_file/test_file")

with open(str(test_file_path), "w+") as file:
    file.write("test")

with open(str(test_file_path) + ".test", "w+") as file:
    file.write("test")

with open(str(test_file_path) + ".txt", "w+") as file:
    file.write("test")


def test_copy_file():
    copy_file(str(test_file_path), str(first_file_dir))


def test_copy_specify_extension_file():
    copy_specify_extension_file(str(test_file_dir), "txt", str(second_file_dir))


def test_copy_all_file_to_dir():
    copy_all_file_to_dir(str(test_file_dir), str(first_file_dir))


def test_rename_file():
    rename_file(str(test_file_dir), "rename", file_extension="txt")


def test_remove_file():
    remove_file(str(Path(test_file_dir, "rename")))


def test():
    test_copy_file()
    test_copy_specify_extension_file()
    test_copy_all_file_to_dir()
    test_rename_file()
    test_remove_file()


if __name__ == "__main__":
    test()
