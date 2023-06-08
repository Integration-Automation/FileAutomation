from pathlib import Path

from file_automation import driver_instance
from file_automation.remote.google_drive.search.search_drive import search_all_file

driver_instance.later_init(str(Path(Path.cwd(), "token.json")), str(Path(Path.cwd(), "credentials.json")))
print(search_all_file())
