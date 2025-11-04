import logging

# 設定 root logger 的等級為 DEBUG
# Set root logger level to DEBUG
logging.root.setLevel(logging.DEBUG)

# 建立一個專用 logger
# Create a dedicated logger
file_automation_logger = logging.getLogger("File Automation")

# 設定 log 格式
# Define log format
formatter = logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s')

# === File handler ===
# 將 log 輸出到檔案 FileAutomation.log
# Write logs to file FileAutomation.log
file_handler = logging.FileHandler(filename="FileAutomation.log", mode="w", encoding="utf-8")
file_handler.setFormatter(formatter)
file_automation_logger.addHandler(file_handler)


class FileAutomationLoggingHandler(logging.Handler):
    """
    自訂 logging handler，將 log 訊息輸出到標準輸出 (print)
    Custom logging handler to redirect logs to stdout (print)
    """

    def __init__(self):
        super().__init__()
        self.formatter = formatter
        self.setLevel(logging.DEBUG)

    def emit(self, record: logging.LogRecord) -> None:
        # 將 log 訊息格式化後輸出到 console
        # Print formatted log message to console
        print(self.format(record))


# === Stream handler ===
# 將 log 輸出到 console
# Add custom stream handler to logger
file_automation_logger.addHandler(FileAutomationLoggingHandler())