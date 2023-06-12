import logging
import sys

file_automation_logger = logging.getLogger("File Automation")
file_automation_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(name)s | %(levelname)s | %(message)s')
# Stream handler
stream_handler = logging.StreamHandler(stream=sys.stderr)
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.WARNING)
file_automation_logger.addHandler(stream_handler)
# File handler
file_handler = logging.FileHandler(filename="FileAutomation.log", mode="w+")
file_handler.setFormatter(formatter)
file_automation_logger.addHandler(file_handler)

