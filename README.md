# FileAutomation

This project provides a modular framework for file automation and Google Drive integration. 
It supports local file and directory operations, ZIP archive handling, 
Google Drive CRUD (create, search, upload, download, delete, share), 
and remote execution through a TCP Socket Server.

# Features
## Local File and Directory Operations
- Create, delete, copy, and rename files
- Create, delete, and copy directories
- Recursively search for files by extension

## ZIP Archive Handling
- Create ZIP archives
- Extract single files or entire archives
- Set ZIP archive passwords
- Read archive information

## Google Drive Integration
- Upload: single files, entire directories, to root or specific folders
- Download: single files or entire folders
- Search: by name, MIME type, or custom fields
- Delete: remove files from Drive
- Share: with specific users, domains, or via public link
- Folder Management: create new folders in Drive

## Automation Executors
- Executor: central manager for all executable functions, supports action lists
- CallbackExecutor: supports callback functions for flexible workflows
- PackageManager: dynamically loads packages and registers functions into executors

# JSON Configuration
- Read and write JSON-based action lists
- Define automation workflows in JSON format

# TCP Socket Server
- Start a TCP server to receive JSON commands and execute corresponding actions
- Supports remote control and returns execution results

## Installation and Requirements

- Requirements
  - Python 3.9+
  - Google API Client
  - Google Drive API enabled and credentials.json downloaded


## Installation
> pip install automation_file

# Usage

1. Initialize Google Drive
```python
from automation_file.remote.google_drive.driver_instance import driver_instance

driver_instance.later_init("token.json", "credentials.json") 
```

2. Upload a File
```python
from automation_file.remote.google_drive.upload.upload_to_driver import drive_upload_to_drive

drive_upload_to_drive("example.txt") 
```

3. Search Files
```python
from automation_file.remote.google_drive.search.search_drive import drive_search_all_file

files = drive_search_all_file()
print(files)
```

4. Start TCP Server
```python
from automation_file.utils.socket_server.file_automation_socket_server import start_autocontrol_socket_server

server = start_autocontrol_socket_server("localhost", 9943)
```

# Example JSON Action
```json
[
  ["FA_create_file", {"file_path": "test.txt"}],
  ["FA_drive_upload_to_drive", {"file_path": "test.txt"}],
  ["FA_drive_search_all_file"]
]
```