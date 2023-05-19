import os
import shutil
import sys
from pathlib import Path

from file_automation.utils.exception.exceptions import DirNotExistsException


def copy_dir(dir_path: str, target_dir_path: str):
    dir_path = Path(dir_path)
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir():
        try:
            shutil.copytree(dir_path, target_dir_path, dirs_exist_ok=True)
        except shutil.Error as error:
            print(repr(error))
    else:
        print(repr(DirNotExistsException), file=sys.stderr)


def remove_dir_tree(dir_path: str):
    dir_path = Path(dir_path)
    if dir_path.is_dir():
        try:
            shutil.rmtree(dir_path)
        except shutil.Error as error:
            print(repr(error))


def rename_dir(origin_dir_path, target_dir: str):
    origin_dir_path = Path(origin_dir_path)
    if origin_dir_path.exists() and origin_dir_path.is_dir():
        try:
            Path.rename(origin_dir_path, target_dir)
        except Exception as error:
            print(repr(error))
    else:
        print(repr(DirNotExistsException), file=sys.stderr)


def create_dir(dir_path: str):
    dir_path = Path(dir_path)
    dir_path.mkdir(exist_ok=True)
