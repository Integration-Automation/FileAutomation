"""Zip archive operations.

Note: Python's standard ``zipfile`` module does not write encrypted archives.
``set_zip_password`` only sets the read-side password used to extract an
already-encrypted archive.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from shutil import make_archive
from zipfile import ZipInfo

from automation_file.exceptions import ZipInputException
from automation_file.logging_config import file_automation_logger


def zip_dir(dir_we_want_to_zip: str, zip_name: str) -> None:
    """Create ``zip_name.zip`` from the contents of ``dir_we_want_to_zip``."""
    make_archive(root_dir=dir_we_want_to_zip, base_name=zip_name, format="zip")
    file_automation_logger.info("zip_dir: %s -> %s.zip", dir_we_want_to_zip, zip_name)


def zip_file(zip_file_path: str, file: str | list[str]) -> None:
    """Write one or many files into ``zip_file_path``."""
    if isinstance(file, str):
        paths = [file]
    elif isinstance(file, list):
        paths = file
    else:
        raise ZipInputException(f"unsupported type: {type(file).__name__}")
    with zipfile.ZipFile(zip_file_path, mode="w") as archive:
        for path in paths:
            name = Path(path).name
            archive.write(path, name)
            file_automation_logger.info("zip_file: %s -> %s", path, zip_file_path)


def read_zip_file(zip_file_path: str, file_name: str, password: bytes | None = None) -> bytes:
    """Return the raw bytes of ``file_name`` inside the zip."""
    with (
        zipfile.ZipFile(zip_file_path, mode="r") as archive,
        archive.open(name=file_name, mode="r", pwd=password, force_zip64=True) as member,
    ):
        data = member.read()
    file_automation_logger.info("read_zip_file: %s/%s", zip_file_path, file_name)
    return data


def unzip_file(
    zip_file_path: str,
    extract_member: str,
    extract_path: str | None = None,
    password: bytes | None = None,
) -> None:
    """Extract a single member to ``extract_path``."""
    with zipfile.ZipFile(zip_file_path, mode="r") as archive:
        archive.extract(member=extract_member, path=extract_path, pwd=password)
    file_automation_logger.info(
        "unzip_file: %s member=%s to=%s",
        zip_file_path,
        extract_member,
        extract_path,
    )


def unzip_all(
    zip_file_path: str,
    extract_member: list[str] | None = None,
    extract_path: str | None = None,
    password: bytes | None = None,
) -> None:
    """Extract every member (or a subset) to ``extract_path``."""
    with zipfile.ZipFile(zip_file_path, mode="r") as archive:
        archive.extractall(members=extract_member, path=extract_path, pwd=password)
    file_automation_logger.info("unzip_all: %s to=%s", zip_file_path, extract_path)


def zip_info(zip_file_path: str) -> list[ZipInfo]:
    """Return the ``ZipInfo`` list for every member in the archive."""
    with zipfile.ZipFile(zip_file_path, mode="r") as archive:
        info_list = archive.infolist()
    file_automation_logger.info("zip_info: %s", zip_file_path)
    return info_list


def zip_file_info(zip_file_path: str) -> list[str]:
    """Return the member names inside the archive."""
    with zipfile.ZipFile(zip_file_path, mode="r") as archive:
        name_list = archive.namelist()
    file_automation_logger.info("zip_file_info: %s", zip_file_path)
    return name_list


def set_zip_password(zip_file_path: str, password: bytes) -> None:
    """Set the read-side password on an encrypted archive."""
    with zipfile.ZipFile(zip_file_path, mode="r") as archive:
        archive.setpassword(pwd=password)
    file_automation_logger.info("set_zip_password: %s", zip_file_path)
