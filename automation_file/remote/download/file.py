import requests
from tqdm import tqdm

# 匯入自訂的日誌工具
# Import custom logging utility
from automation_file.utils.logging.loggin_instance import file_automation_logger


def download_file(file_url: str, file_name: str, chunk_size: int = 1024, timeout: int = 10):
    """
    下載檔案並顯示進度條
    Download a file with progress bar
    :param file_url: 檔案下載網址 (str)
                     File download URL (str)
    :param file_name: 儲存檔案名稱 (str)
                      File name to save as (str)
    :param chunk_size: 每次下載的資料塊大小，預設 1024 bytes
                       Size of each download chunk, default 1024 bytes
    :param timeout: 請求逾時時間 (秒)，預設 10
                    Request timeout in seconds, default 10
    :return: None
    """
    try:
        # 發送 HTTP GET 請求，使用串流模式避免一次載入大檔案
        # Send HTTP GET request with streaming to avoid loading large file at once
        response = requests.get(file_url, stream=True, timeout=timeout)
        response.raise_for_status()  # 若狀態碼非 200，則拋出例外 / Raise exception if status code is not 200

        # 從回應標頭取得檔案大小 (若伺服器有提供)
        # Get total file size from response headers (if available)
        total_size = int(response.headers.get('content-length', 0))

        # 以二進位寫入模式開啟檔案
        # Open file in binary write mode
        with open(file_name, 'wb') as file:
            if total_size > 0:
                # 使用 tqdm 顯示下載進度條
                # Use tqdm to show download progress bar
                with tqdm(total=total_size, unit='B', unit_scale=True, desc=file_name) as progress:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:  # 避免空資料塊 / Avoid empty chunks
                            file.write(chunk)
                            progress.update(len(chunk))  # 更新進度條 / Update progress bar
            else:
                # 若無法取得檔案大小，仍逐塊下載
                # If file size is unknown, still download in chunks
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        file.write(chunk)

        file_automation_logger.info(f"File download is complete. Saved as: {file_name}")

    # 錯誤處理區塊 / Error handling
    except requests.exceptions.HTTPError as http_err:
        file_automation_logger.error(f"HTTP error：{http_err}")
    except requests.exceptions.ConnectionError:
        file_automation_logger.error("Connection error. Please check your internet connection.")
    except requests.exceptions.Timeout:
        file_automation_logger.error("Request timed out. The server did not respond.")
    except Exception as err:
        file_automation_logger.error(f"Error：{err}")