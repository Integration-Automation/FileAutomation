import zipfile
from pathlib import Path
from shutil import make_archive
from typing import List, Dict, Union
from zipfile import ZipInfo

# 匯入自訂例外與日誌工具
# Import custom exception and logging utility
from automation_file.utils.exception.exceptions import ZIPGetWrongFileException
from automation_file.utils.logging.loggin_instance import file_automation_logger


def zip_dir(dir_we_want_to_zip: str, zip_name: str) -> None:
    """
    壓縮整個資料夾成 zip 檔
    Zip an entire directory
    :param dir_we_want_to_zip: 要壓縮的資料夾路徑 (str)
                               Directory path to zip (str)
    :param zip_name: 壓縮檔名稱 (str)
                     Zip file name (str)
    :return: None
    """
    make_archive(root_dir=dir_we_want_to_zip, base_name=zip_name, format="zip")
    file_automation_logger.info(f"Dir to zip: {dir_we_want_to_zip}, zip file name: {zip_name}")


def zip_file(zip_file_path: str, file: Union[str, List[str]]) -> None:
    """
    將單一檔案或多個檔案加入 zip
    Add single or multiple files into a zip
    :param zip_file_path: zip 檔路徑 (str)
                          Zip file path (str)
    :param file: 檔案路徑或檔案路徑清單 (str 或 List[str])
                 File path or list of file paths
    :return: None
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="w")
    if isinstance(file, str):
        file_name = Path(file)
        current_zip.write(file, file_name.name)  # 寫入單一檔案 / Write single file
        file_automation_logger.info(f"Write file: {file_name} to zip: {current_zip}")
    else:
        if isinstance(file, list):
            for writeable in file:
                file_name = Path(writeable)
                current_zip.write(writeable, file_name.name)  # 寫入多個檔案 / Write multiple files
                file_automation_logger.info(f"Write file: {writeable} to zip: {current_zip}")
        else:
            file_automation_logger.error(repr(ZIPGetWrongFileException))
    current_zip.close()


def read_zip_file(zip_file_path: str, file_name: str, password: Union[str, None] = None) -> bytes:
    """
    讀取 zip 檔中的指定檔案
    Read a specific file inside a zip
    :param zip_file_path: zip 檔路徑 (str)
                          Zip file path (str)
    :param file_name: zip 中的檔案名稱 (str)
                      File name inside zip (str)
    :param password: 若 zip 有密碼，需提供 (str 或 None)
                     Password if zip is protected
    :return: 檔案內容 (bytes)
             File content (bytes)
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    with current_zip.open(name=file_name, mode="r", pwd=password, force_zip64=True) as read_file:
        data = read_file.read()
    current_zip.close()
    file_automation_logger.info(f"Read zip file: {zip_file_path}")
    return data


def unzip_file(zip_file_path: str, extract_member, extract_path: Union[str, None] = None,
               password: Union[str, None] = None) -> None:
    """
    解壓縮 zip 中的單一檔案
    Extract a single file from a zip
    :param zip_file_path: zip 檔路徑 (str)
                          Zip file path (str)
    :param extract_member: 要解壓縮的檔案名稱 (str)
                           File name to extract
    :param extract_path: 解壓縮到的路徑 (str 或 None)
                         Path to extract to
    :param password: 若 zip 有密碼，需提供 (str 或 None)
                     Password if zip is protected
    :return: None
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    current_zip.extract(member=extract_member, path=extract_path, pwd=password)
    file_automation_logger.info(
        f"Unzip file: {zip_file_path}, extract member: {extract_member}, extract path: {extract_path}, password: {password}"
    )
    current_zip.close()


def unzip_all(zip_file_path: str, extract_member: Union[str, None] = None,
              extract_path: Union[str, None] = None, password: Union[str, None] = None) -> None:
    """
    解壓縮 zip 中的所有檔案
    Extract all files from a zip
    :param zip_file_path: zip 檔路徑 (str)
                          Zip file path (str)
    :param extract_member: 指定要解壓縮的檔案 (可選) (str 或 None)
                           Specific members to extract (optional)
    :param extract_path: 解壓縮到的路徑 (str 或 None)
                         Path to extract to
    :param password: 若 zip 有密碼，需提供 (str 或 None)
                     Password if zip is protected
    :return: None
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    current_zip.extractall(members=extract_member, path=extract_path, pwd=password)
    file_automation_logger.info(
        f"Unzip file: {zip_file_path}, extract member: {extract_member}, extract path: {extract_path}, password: {password}"
    )
    current_zip.close()


def zip_info(zip_file_path: str) -> List[ZipInfo]:
    """
    取得 zip 檔案的詳細資訊 (ZipInfo 物件)
    Get detailed info of a zip file (ZipInfo objects)
    :param zip_file_path: zip 檔路徑 (str)
                          Zip file path (str)
    :return: List[ZipInfo]
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    info_list = current_zip.infolist()  # 回傳 ZipInfo 物件清單 / Return list of ZipInfo objects
    current_zip.close()
    file_automation_logger.info(f"Show zip info: {zip_file_path}")
    return info_list


def zip_file_info(zip_file_path: str) -> List[str]:
    """
    取得 zip 檔案內所有檔案名稱
    Get list of file names inside a zip
    :param zip_file_path: zip 檔路徑 (str)
                          Zip file path (str)
    :return: List[str]
    """
    current_zip = zipfile.ZipFile(zip_file_path, mode="r")
    name_list = current_zip.namelist()  # 回傳檔案名稱清單 / Return list of file names
    current_zip.close()
    file_automation_logger.info(f"Show zip file info: {zip_file_path}")
    return name_list


def set_zip_password(zip_file_path: str, password: bytes) -> None:
    """
    設定 zip 檔案的密碼 (注意：標準 zipfile 僅支援讀取密碼，不支援加密寫入)
    Set password for a zip file (Note: standard zipfile only supports reading with password, not writing encrypted zips)
    :param zip_file_path: zip 檔路徑 (str)
                          Zip file path (str)
    :param password: 密碼 (bytes)
                     Password (bytes)
    :return: None
    """
    current_zip = zipfile.ZipFile(zip_file_path)
    current_zip.setpassword(pwd=password)  # 設定解壓縮時的密碼 / Set password for extraction
    current_zip.close()
    file_automation_logger.info(f"Set zip file password, zip file: {zip_file_path}, zip password: {password}")