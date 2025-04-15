import requests
from tqdm import tqdm

from automation_file.utils.logging.loggin_instance import file_automation_logger


def download_file(file_url: str, file_name: str, chunk_size: int = 1024, timeout: int = 10):
    try:
        response = requests.get(file_url, stream=True, timeout=10)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        with open(file_name, 'wb') as file:
            if total_size > 0:
                with tqdm(
                    total=total_size, unit='B', unit_scale=True, desc=file_name
                ) as progress:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            file.write(chunk)
                            progress.update(len(chunk))
            else:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        file.write(chunk)

        file_automation_logger.info(f"File download is complete. Saved as: {file_name}")
    except requests.exceptions.HTTPError as http_err:
        file_automation_logger.error(f"HTTP error：{http_err}")
    except requests.exceptions.ConnectionError:
        file_automation_logger.error("Connection error. Please check your internet connection.")
    except requests.exceptions.Timeout:
        file_automation_logger.error("Request timed out. The server did not respond.")
    except Exception as err:
        file_automation_logger.error(f"Error：{err}")

