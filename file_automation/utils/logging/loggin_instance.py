import logging

logging.getLogger().setLevel(logging.INFO)
file_automation_logger = logging.getLogger("File Automation")
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
file_automation_logger.addHandler(handler)
file_automation_logger.setLevel(logging.DEBUG)
