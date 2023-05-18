import os
import shutil
import sys
from pathlib import Path

from file_automation.utils.exception.exceptions import DirNotExistsException


def copy_dir(dir_path: str, target_dir_path: str):
    dir_path = Path(dir_path)
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir() and target_dir_path.is_dir():
        try:
            shutil.copytree(dir_path, target_dir_path, dirs_exist_ok=True)
        except shutil.Error as error:
            print(repr(error))


def remove_dir_tree(dir_path: str):
    dir_path = Path(dir_path)
    if dir_path.is_dir():
        try:
            shutil.rmtree(dir_path)
        except shutil.Error as error:
            print(repr(error))


def rename_dir(origin_file_path, target_dir: str):
    origin_file_path = Path(origin_file_path)
    if origin_file_path.exists() and origin_file_path.is_dir():
        try:
            os.rename(origin_file_path, target_dir)
        except shutil.Error as error:
            print(repr(error))
    else:
        print(repr(DirNotExistsException), file=sys.stderr)

# TODO Path.mkdir, Path.rmdir Path.samefile
