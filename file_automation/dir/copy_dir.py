import shutil
from pathlib import Path


def copy_dir(dir_path: str, target_dir_path: str):
    dir_path = Path(dir_path)
    target_dir_path = Path(target_dir_path)
    if dir_path.is_dir() and target_dir_path.is_dir():
        try:
            shutil.copytree(dir_path, target_dir_path, dirs_exist_ok=True)
        except shutil.Error as error:
            print(repr(error))


def remove_dir(dir_path: str):
    dir_path = Path(dir_path)
    if dir_path.is_dir():
        try:
            shutil.rmtree(dir_path)
        except shutil.Error as error:
            print(repr(error))
