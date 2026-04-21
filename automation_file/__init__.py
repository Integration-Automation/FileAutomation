"""Public API for automation_file.

This module is the facade: every publicly supported function, class, or shared
singleton is re-exported from here, so callers only ever need
``from automation_file import X``.
"""
from __future__ import annotations

from automation_file.core.action_executor import (
    ActionExecutor,
    add_command_to_executor,
    execute_action,
    execute_action_parallel,
    execute_files,
    executor,
    validate_action,
)
from automation_file.core.action_registry import ActionRegistry, build_default_registry
from automation_file.core.callback_executor import CallbackExecutor
from automation_file.core.json_store import read_action_json, write_action_json
from automation_file.core.package_loader import PackageLoader
from automation_file.core.quota import Quota
from automation_file.core.retry import retry_on_transient
from automation_file.local.dir_ops import copy_dir, create_dir, remove_dir_tree, rename_dir
from automation_file.local.file_ops import (
    copy_all_file_to_dir,
    copy_file,
    copy_specify_extension_file,
    create_file,
    remove_file,
    rename_file,
)
from automation_file.local.safe_paths import is_within, safe_join
from automation_file.local.zip_ops import (
    read_zip_file,
    set_zip_password,
    unzip_all,
    unzip_file,
    zip_dir,
    zip_file,
    zip_file_info,
    zip_info,
)
from automation_file.project.project_builder import ProjectBuilder, create_project_dir
from automation_file.remote.google_drive.client import GoogleDriveClient, driver_instance
from automation_file.remote.google_drive.delete_ops import drive_delete_file
from automation_file.remote.google_drive.download_ops import (
    drive_download_file,
    drive_download_file_from_folder,
)
from automation_file.remote.google_drive.folder_ops import drive_add_folder
from automation_file.remote.google_drive.search_ops import (
    drive_search_all_file,
    drive_search_field,
    drive_search_file_mimetype,
)
from automation_file.remote.google_drive.share_ops import (
    drive_share_file_to_anyone,
    drive_share_file_to_domain,
    drive_share_file_to_user,
)
from automation_file.remote.google_drive.upload_ops import (
    drive_upload_dir_to_drive,
    drive_upload_dir_to_folder,
    drive_upload_to_drive,
    drive_upload_to_folder,
)
from automation_file.remote.http_download import download_file
from automation_file.remote.url_validator import validate_http_url
from automation_file.server.http_server import HTTPActionServer, start_http_action_server
from automation_file.server.tcp_server import (
    TCPActionServer,
    start_autocontrol_socket_server,
)
from automation_file.utils.file_discovery import get_dir_files_as_list

# Shared callback executor + package loader wired to the shared registry.
callback_executor: CallbackExecutor = CallbackExecutor(executor.registry)
package_manager: PackageLoader = PackageLoader(executor.registry)

__all__ = [
    # Core
    "ActionExecutor", "ActionRegistry", "CallbackExecutor", "PackageLoader",
    "Quota", "build_default_registry", "execute_action", "execute_action_parallel",
    "execute_files", "validate_action", "retry_on_transient",
    "add_command_to_executor", "read_action_json", "write_action_json",
    "executor", "callback_executor", "package_manager",
    # Local
    "copy_file", "rename_file", "remove_file", "copy_all_file_to_dir",
    "copy_specify_extension_file", "create_file",
    "copy_dir", "create_dir", "remove_dir_tree", "rename_dir",
    "zip_dir", "zip_file", "zip_info", "zip_file_info", "set_zip_password",
    "unzip_file", "read_zip_file", "unzip_all",
    "safe_join", "is_within",
    # Remote
    "download_file", "validate_http_url",
    "GoogleDriveClient", "driver_instance",
    "drive_search_all_file", "drive_search_field", "drive_search_file_mimetype",
    "drive_upload_dir_to_folder", "drive_upload_to_folder",
    "drive_upload_dir_to_drive", "drive_upload_to_drive",
    "drive_add_folder",
    "drive_share_file_to_anyone", "drive_share_file_to_domain", "drive_share_file_to_user",
    "drive_delete_file",
    "drive_download_file", "drive_download_file_from_folder",
    # Server / Project / Utils
    "TCPActionServer", "start_autocontrol_socket_server",
    "HTTPActionServer", "start_http_action_server",
    "ProjectBuilder", "create_project_dir",
    "get_dir_files_as_list",
]
