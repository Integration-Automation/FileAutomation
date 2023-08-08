from pathlib import Path

from automation_file import driver_instance
from automation_file.remote.google_drive.search.search_drive import drive_search_all_file

driver_instance.later_init(str(Path(Path.cwd(), "token.json")), str(Path(Path.cwd(), "credentials.json")))
print(drive_search_all_file())
