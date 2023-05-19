import time
from pathlib import Path

from file_automation import zip_dir, zip_file, read_zip_file, unzip_file, unzip_all, zip_info, zip_file_info, \
    set_zip_password

zip_file_path = Path(Path.cwd(), "test.zip")
dir_to_zip = Path(Path.cwd(), "dir_to_zip")
file_to_zip = Path(Path.cwd(), "file_to_zip.txt")


def test_zip_dir():
    zip_dir(dir_we_want_to_zip=str(dir_to_zip), zip_name="test_generate")


def test_zip_file():
    zip_file(str(zip_file_path), str(file_to_zip))


def test_read_zip_file():
    print(read_zip_file(str(zip_file_path), str(file_to_zip.name)))


def test_unzip_file():
    unzip_file(str(zip_file_path), str(file_to_zip.name))


def test_unzip_all():
    unzip_all(str(zip_file_path))


def test_zip_info():
    print(zip_info(str(zip_file_path)))


def test_zip_file_info():
    print(zip_file_info(str(zip_file_path)))


def test_set_zip_password():
    set_zip_password(str(zip_file_path), b"12345678")


def test():
    test_zip_dir()
    test_zip_file()
    test_read_zip_file()
    test_unzip_file()
    test_unzip_all()
    test_zip_file_info()
    test_set_zip_password()


if __name__ == "__main__":
    test()
