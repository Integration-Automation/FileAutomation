import os
import shutil
import sys
from pathlib import Path

from file_automation.utils.exception.exceptions import FileNotExistsException, DirNotExistsException


def copy_file(file_path: str, target_path: str):
    file_path = Path(file_path)
    if file_path.is_file() and file_path.exists():
        try:
            shutil.copy2(file_path, target_path)
        except shutil.Error as error:
            print(repr(error))
    else:
        print(repr(FileNotExistsException), file=sys.stderr)


def copy_specify_extension_file(file_dir_path: str, target_extension: str, target_path: str):
    file_dir_path = Path(file_dir_path)
    if file_dir_path.exists() and file_dir_path.is_dir():
        for file in file_dir_path.glob(f"**/*.{target_extension}"):
            copy_file(str(file), target_path)
    else:
        print(repr(DirNotExistsException), file=sys.stderr)


def copy_all_file_t_dir(dir_path: str, target_dir_path: str):
    dir_path = Path(dir_path)
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir() and target_dir_path.is_dir():
        try:
            shutil.move(str(dir_path), str(target_dir_path))
        except shutil.Error as error:
            print(repr(error), file=sys.stderr)
    else:
        print(repr(DirNotExistsException), file=sys.stderr)


def rename_file(origin_file_path, target_name: str, file_extension=None):
    origin_file_path = Path(origin_file_path)
    if origin_file_path.exists() and origin_file_path.is_file():
        if file_extension is None:
            file_list = origin_file_path.glob("**/*")
        else:
            file_list = origin_file_path.glob(f"**/*.{file_extension}")
        try:
            file_index = 0
            for file in file_list:
                os.rename(file, target_name + str(file_index))
                file_index = file_index + 1
        except shutil.Error as error:
            print(repr(error))
    else:
        print(repr(FileNotExistsException), file=sys.stderr)


def remove_file(file_path: str):
    file_path = Path(file_path)
    if file_path.exists() and file_path.is_file():
        file_path.unlink(missing_ok=True)
