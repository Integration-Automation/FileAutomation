"""Public API for automation_file.

This module is the facade: every publicly supported function, class, or shared
singleton is re-exported from here, so callers only ever need
``from automation_file import X``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from automation_file.client import HTTPActionClient, HTTPActionClientException
from automation_file.core.action_executor import (
    ActionExecutor,
    add_command_to_executor,
    execute_action,
    execute_action_parallel,
    execute_files,
    executor,
    validate_action,
)
from automation_file.core.action_queue import ActionQueue, QueueItem
from automation_file.core.action_registry import ActionRegistry, build_default_registry
from automation_file.core.audit import AuditException, AuditLog
from automation_file.core.callback_executor import CallbackExecutor
from automation_file.core.checksum import (
    ChecksumMismatchException,
    file_checksum,
    verify_checksum,
)
from automation_file.core.circuit_breaker import CircuitBreaker
from automation_file.core.config import AutomationConfig, ConfigException
from automation_file.core.config_watcher import ConfigWatcher
from automation_file.core.content_store import ContentStore
from automation_file.core.crypto import (
    CryptoException,
    decrypt_file,
    encrypt_file,
    generate_key,
    key_from_password,
)
from automation_file.core.dag_executor import execute_action_dag
from automation_file.core.file_lock import FileLock
from automation_file.core.fim import IntegrityMonitor
from automation_file.core.json_store import read_action_json, write_action_json
from automation_file.core.manifest import ManifestException, verify_manifest, write_manifest
from automation_file.core.metrics import ACTION_COUNT, ACTION_DURATION, record_action
from automation_file.core.metrics import render as render_metrics
from automation_file.core.package_loader import PackageLoader
from automation_file.core.progress import (
    CancellationToken,
    CancelledException,
    ProgressRegistry,
    ProgressReporter,
    progress_cancel,
    progress_clear,
    progress_list,
    progress_registry,
    register_progress_ops,
)
from automation_file.core.quota import Quota
from automation_file.core.rate_limit import RateLimiter
from automation_file.core.retry import retry_on_transient
from automation_file.core.secrets import (
    ChainedSecretProvider,
    EnvSecretProvider,
    FileSecretProvider,
    SecretException,
    SecretNotFoundException,
    SecretProvider,
    default_provider,
    resolve_secret_refs,
)
from automation_file.core.sqlite_lock import SQLiteLock
from automation_file.core.substitution import SubstitutionException, substitute
from automation_file.local.conditional import if_exists, if_newer, if_size_gt
from automation_file.local.dir_ops import copy_dir, create_dir, remove_dir_tree, rename_dir
from automation_file.local.file_ops import (
    copy_all_file_to_dir,
    copy_file,
    copy_specify_extension_file,
    create_file,
    remove_file,
    rename_file,
)
from automation_file.local.json_edit import (
    JsonEditException,
    json_delete,
    json_get,
    json_set,
)
from automation_file.local.mime import detect_from_bytes, detect_mime
from automation_file.local.safe_paths import is_within, safe_join
from automation_file.local.shell_ops import ShellException, run_shell
from automation_file.local.sync_ops import SyncException, sync_dir
from automation_file.local.tar_ops import TarException, create_tar, extract_tar
from automation_file.local.templates import render_file, render_string
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
from automation_file.notify import (
    DiscordSink,
    EmailSink,
    NotificationException,
    NotificationManager,
    NotificationSink,
    PagerDutySink,
    SlackSink,
    TeamsSink,
    TelegramSink,
    WebhookSink,
    notification_manager,
    notify_send,
    register_notify_ops,
)
from automation_file.project.project_builder import ProjectBuilder, create_project_dir
from automation_file.remote.azure_blob import (
    AzureBlobClient,
    azure_blob_instance,
    register_azure_blob_ops,
)
from automation_file.remote.cross_backend import CrossBackendException, copy_between
from automation_file.remote.dropbox_api import (
    DropboxClient,
    dropbox_instance,
    register_dropbox_ops,
)
from automation_file.remote.ftp import (
    FTPClient,
    FTPConnectOptions,
    FTPException,
    ftp_instance,
    register_ftp_ops,
)
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
from automation_file.remote.s3 import S3Client, register_s3_ops, s3_instance
from automation_file.remote.sftp import SFTPClient, register_sftp_ops, sftp_instance
from automation_file.remote.url_validator import validate_http_url
from automation_file.scheduler import (
    CronExpression,
    ScheduledJob,
    Scheduler,
    register_scheduler_ops,
    schedule_add,
    schedule_list,
    schedule_remove,
    schedule_remove_all,
    scheduler,
)
from automation_file.server.action_acl import ActionACL, ActionNotPermittedException
from automation_file.server.http_server import HTTPActionServer, start_http_action_server
from automation_file.server.metrics_server import MetricsServer, start_metrics_server
from automation_file.server.tcp_server import (
    TCPActionServer,
    start_autocontrol_socket_server,
)
from automation_file.trigger import (
    FileWatcher,
    TriggerManager,
    register_trigger_ops,
    trigger_manager,
    watch_list,
    watch_start,
    watch_stop,
    watch_stop_all,
)
from automation_file.utils.deduplicate import find_duplicates
from automation_file.utils.fast_find import fast_find, has_os_index, scandir_find
from automation_file.utils.file_discovery import get_dir_files_as_list
from automation_file.utils.grep import GrepException, grep_files, iter_grep
from automation_file.utils.rotate import RotateException, rotate_backups

if TYPE_CHECKING:
    from automation_file.ui.launcher import (
        launch_ui as launch_ui,  # pylint: disable=useless-import-alias
    )

# Shared callback executor + package loader wired to the shared registry.
callback_executor: CallbackExecutor = CallbackExecutor(executor.registry)
package_manager: PackageLoader = PackageLoader(executor.registry)


def __getattr__(name: str) -> Any:
    if name == "launch_ui":
        from automation_file.ui.launcher import launch_ui as _launch_ui

        return _launch_ui
    raise AttributeError(f"module 'automation_file' has no attribute {name!r}")


__all__ = [
    # Core
    "ActionExecutor",
    "ActionQueue",
    "ActionRegistry",
    "CallbackExecutor",
    "CircuitBreaker",
    "ContentStore",
    "FileLock",
    "PackageLoader",
    "Quota",
    "QueueItem",
    "RateLimiter",
    "SQLiteLock",
    "build_default_registry",
    "execute_action",
    "execute_action_parallel",
    "execute_action_dag",
    "execute_files",
    "validate_action",
    "retry_on_transient",
    "substitute",
    "SubstitutionException",
    "add_command_to_executor",
    "read_action_json",
    "write_action_json",
    "executor",
    "callback_executor",
    "package_manager",
    # Local
    "copy_file",
    "rename_file",
    "remove_file",
    "copy_all_file_to_dir",
    "copy_specify_extension_file",
    "create_file",
    "copy_dir",
    "create_dir",
    "detect_from_bytes",
    "detect_mime",
    "remove_dir_tree",
    "rename_dir",
    "render_file",
    "render_string",
    "sync_dir",
    "SyncException",
    "create_tar",
    "extract_tar",
    "TarException",
    "run_shell",
    "ShellException",
    "json_get",
    "json_set",
    "json_delete",
    "JsonEditException",
    "zip_dir",
    "zip_file",
    "zip_info",
    "zip_file_info",
    "set_zip_password",
    "unzip_file",
    "read_zip_file",
    "unzip_all",
    "safe_join",
    "is_within",
    "if_exists",
    "if_newer",
    "if_size_gt",
    # Remote
    "download_file",
    "validate_http_url",
    "GoogleDriveClient",
    "driver_instance",
    "drive_search_all_file",
    "drive_search_field",
    "drive_search_file_mimetype",
    "drive_upload_dir_to_folder",
    "drive_upload_to_folder",
    "drive_upload_dir_to_drive",
    "drive_upload_to_drive",
    "drive_add_folder",
    "drive_share_file_to_anyone",
    "drive_share_file_to_domain",
    "drive_share_file_to_user",
    "drive_delete_file",
    "drive_download_file",
    "drive_download_file_from_folder",
    "S3Client",
    "s3_instance",
    "register_s3_ops",
    "AzureBlobClient",
    "azure_blob_instance",
    "register_azure_blob_ops",
    "DropboxClient",
    "dropbox_instance",
    "register_dropbox_ops",
    "SFTPClient",
    "sftp_instance",
    "register_sftp_ops",
    "FTPClient",
    "FTPConnectOptions",
    "FTPException",
    "ftp_instance",
    "register_ftp_ops",
    "CrossBackendException",
    "copy_between",
    # Server / Project / Utils
    "TCPActionServer",
    "start_autocontrol_socket_server",
    "HTTPActionServer",
    "start_http_action_server",
    "HTTPActionClient",
    "HTTPActionClientException",
    "ActionACL",
    "ActionNotPermittedException",
    "ProjectBuilder",
    "create_project_dir",
    "get_dir_files_as_list",
    "fast_find",
    "scandir_find",
    "has_os_index",
    "file_checksum",
    "verify_checksum",
    "ChecksumMismatchException",
    "find_duplicates",
    "grep_files",
    "iter_grep",
    "GrepException",
    "rotate_backups",
    "RotateException",
    "ManifestException",
    "write_manifest",
    "verify_manifest",
    "AuditException",
    "AuditLog",
    "IntegrityMonitor",
    "CryptoException",
    "encrypt_file",
    "decrypt_file",
    "generate_key",
    "key_from_password",
    "ACTION_COUNT",
    "ACTION_DURATION",
    "record_action",
    "render_metrics",
    "MetricsServer",
    "start_metrics_server",
    # Triggers
    "FileWatcher",
    "TriggerManager",
    "register_trigger_ops",
    "trigger_manager",
    "watch_start",
    "watch_stop",
    "watch_stop_all",
    "watch_list",
    # Scheduler
    "CronExpression",
    "ScheduledJob",
    "Scheduler",
    "register_scheduler_ops",
    "schedule_add",
    "schedule_list",
    "schedule_remove",
    "schedule_remove_all",
    "scheduler",
    # Progress / cancellation
    "CancellationToken",
    "CancelledException",
    "ProgressRegistry",
    "ProgressReporter",
    "progress_cancel",
    "progress_clear",
    "progress_list",
    "progress_registry",
    "register_progress_ops",
    # Notifications
    "DiscordSink",
    "EmailSink",
    "NotificationException",
    "NotificationManager",
    "NotificationSink",
    "PagerDutySink",
    "SlackSink",
    "TeamsSink",
    "TelegramSink",
    "WebhookSink",
    "notification_manager",
    "notify_send",
    "register_notify_ops",
    # Config / secrets
    "AutomationConfig",
    "ConfigException",
    "ConfigWatcher",
    "ChainedSecretProvider",
    "EnvSecretProvider",
    "FileSecretProvider",
    "SecretException",
    "SecretNotFoundException",
    "SecretProvider",
    "default_provider",
    "resolve_secret_refs",
    # UI (lazy-loaded)
    "launch_ui",
]
