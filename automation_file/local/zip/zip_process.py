import zipfile
from pathlib import Path
from shutil import make_archive
from typing import List
from zipfile import ZipInfo

from automation_file.utils.exception.exceptions import ZIPGetWrongFileException
from automation_file.utils.logging.loggin_instance import file_automation_logger


def zip_dir(dir_we_want_to_zip: str, zip_name: str) -> None:
    """
    :param dir_we_want_to_zip: dir str path
    :param zip_name: zip file name
    :return: None
    """
    make_archive(root_dir=dir_we_want_to_zip, base_name=zip_name, format="zip")
    file_automation_logger.info(f"Dir to zip: {dir_we_want_to_zip}, zip file name: {zip_name}")


def zip_file(zip_file_path: str, file: [str, List[str]]) -> None:
    """
    :param zip_file_path: add file to zip file
    :param file: single file path or list of file path (str) to add into zip
    :return: None
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="w")
    if isinstance(file, str):
        file_name = Path(file)
        current_zip.write(file, file_name.name)
        file_automation_logger.info(
            f"Write file: {file_name} to zip: {current_zip}"
        )
    else:
        if isinstance(file, list):
            for writeable in file:
                file_name = Path(writeable)
                current_zip.write(writeable, file_name.name)
                file_automation_logger.info(
                    f"Write file: {writeable} to zip: {current_zip}"
                )
        else:
            file_automation_logger.error(
                repr(ZIPGetWrongFileException))
    current_zip.close()


def read_zip_file(zip_file_path: str, file_name: str, password: [str, None] = None) -> bytes:
    """
    :param zip_file_path: which zip do we want to read
    :param file_name: which file on zip do we want to read
    :param password: if zip have password use this password to unzip zip file
    :return:
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    with current_zip.open(name=file_name, mode="r", pwd=password, force_zip64=True) as read_file:
        data = read_file.read()
    current_zip.close()
    file_automation_logger.info(
        f"Read zip file: {zip_file_path}"
    )
    return data


def unzip_file(
        zip_file_path: str, extract_member, extract_path: [str, None] = None, password: [str, None] = None) -> None:
    """
    :param zip_file_path: which zip we want to unzip
    :param extract_member: which member we want to unzip
    :param extract_path: extract member to path
    :param password: if zip have password use this password to unzip zip file
    :return: None
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    current_zip.extract(member=extract_member, path=extract_path, pwd=password)
    file_automation_logger.info(
        f"Unzip file: {zip_file_path}, "
        f"extract member: {extract_member}, "
        f"extract path: {extract_path}, "
        f"password: {password}"
    )
    current_zip.close()


def unzip_all(
        zip_file_path: str, extract_member: [str, None] = None,
        extract_path: [str, None] = None, password: [str, None] = None) -> None:
    """
    :param zip_file_path: which zip do we want to unzip
    :param extract_member: which member do we want to unzip
    :param extract_path: extract to path
    :param password: if zip have password use this password to unzip zip file
    :return: None
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    current_zip.extractall(members=extract_member, path=extract_path, pwd=password)
    file_automation_logger.info(
        f"Unzip file: {zip_file_path}, "
        f"extract member: {extract_member}, "
        f"extract path: {extract_path}, "
        f"password: {password}"
    )
    current_zip.close()


def zip_info(zip_file_path: str) -> List[ZipInfo]:
    """
    :param zip_file_path: read zip file info
    :return: List[ZipInfo]
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    info_list = current_zip.infolist()
    current_zip.close()
    file_automation_logger.info(
        f"Show zip info: {zip_file_path}"
    )
    return info_list


def zip_file_info(zip_file_path: str) -> List[str]:
    """
    :param zip_file_path: read inside zip file info
    :return: List[str]
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    name_list = current_zip.namelist()
    current_zip.close()
    file_automation_logger.info(
        f"Show zip file info: {zip_file_path}"
    )
    return name_list


def set_zip_password(zip_file_path: str, password: bytes) -> None:
    """
    :param zip_file_path: which zip do we want to set password
    :param password: password will be set
    :return: None
    """
    current_zip = zipfile.ZipFile(zip_file_path)
    current_zip.setpassword(pwd=password)
    current_zip.close()
    file_automation_logger.info(
        f"Set zip file password, "
        f"zip file: {zip_file_path}, "
        f"zip password: {password}"
    )
