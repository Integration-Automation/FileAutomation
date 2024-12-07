import logging

logging.root.setLevel(logging.DEBUG)
file_automation_logger = logging.getLogger("File Automation")
formatter = logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s')
# File handler
file_handler = logging.FileHandler(filename="FileAutomation.log", mode="w")
file_handler.setFormatter(formatter)
file_automation_logger.addHandler(file_handler)

class FileAutomationLoggingHandler(logging.Handler):

    # redirect logging stderr output to queue

    def __init__(self):
        super().__init__()
        self.formatter = formatter
        self.setLevel(logging.DEBUG)

    def emit(self, record: logging.LogRecord) -> None:
        print(self.format(record))


# Stream handler
file_automation_logger.addHandler(FileAutomationLoggingHandler())


