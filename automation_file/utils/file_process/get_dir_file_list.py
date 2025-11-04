from os import getcwd, walk
from os.path import abspath, join
from typing import List


def get_dir_files_as_list(
        dir_path: str = getcwd(),
        default_search_file_extension: str = ".json") -> List[str]:
    """
    遞迴搜尋資料夾下所有符合副檔名的檔案，並回傳完整路徑清單
    Recursively search for files with a specific extension in a directory and return absolute paths

    :param dir_path: 要搜尋的資料夾路徑 (預設為當前工作目錄)
                     Directory path to search (default: current working directory)
    :param default_search_file_extension: 要搜尋的副檔名 (預設為 ".json")
                                          File extension to search (default: ".json")
    :return: 若無符合檔案則回傳空清單，否則回傳檔案完整路徑清單
             [] if no files found, else [file1, file2, ...]
    """
    return [
        abspath(join(root, file))
        for root, dirs, files in walk(dir_path)
        for file in files
        if file.lower().endswith(default_search_file_extension.lower())
    ]