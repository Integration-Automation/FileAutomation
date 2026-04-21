"""Registry of named callables (Registry + Command pattern).

The registry decouples "what to run" (a string name inside a JSON action list)
from "how to run it" (a Python callable). Executors delegate name resolution
to an :class:`ActionRegistry`, which keeps look-up O(1) and lets plugins add
commands at runtime without touching the executor class.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from automation_file.exceptions import AddCommandException
from automation_file.logging_config import file_automation_logger

Command = Callable[..., Any]


class ActionRegistry:
    """Mapping of action name -> callable."""

    def __init__(self, initial: Mapping[str, Command] | None = None) -> None:
        self._commands: dict[str, Command] = {}
        if initial:
            for name, command in initial.items():
                self.register(name, command)

    def register(self, name: str, command: Command) -> None:
        """Add or overwrite a command. Raises if ``command`` is not callable."""
        if not callable(command):
            raise AddCommandException(f"{name!r} is not callable")
        self._commands[name] = command

    def register_many(self, mapping: Mapping[str, Command]) -> None:
        """Register every ``name -> command`` pair in ``mapping``."""
        for name, command in mapping.items():
            self.register(name, command)

    def update(self, mapping: Mapping[str, Command]) -> None:
        """Alias for :meth:`register_many` (dict-compatible)."""
        self.register_many(mapping)

    def unregister(self, name: str) -> None:
        self._commands.pop(name, None)

    def resolve(self, name: str) -> Command | None:
        return self._commands.get(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._commands

    def __len__(self) -> int:
        return len(self._commands)

    def __iter__(self) -> Iterator[str]:
        return iter(self._commands)

    def names(self) -> Iterable[str]:
        return self._commands.keys()

    @property
    def event_dict(self) -> dict[str, Command]:
        """Backwards-compatible view used by older ``package_manager`` style code."""
        return self._commands


def _local_commands() -> dict[str, Command]:
    from automation_file.local import dir_ops, file_ops, zip_ops

    return {
        # Files
        "FA_create_file": file_ops.create_file,
        "FA_copy_file": file_ops.copy_file,
        "FA_rename_file": file_ops.rename_file,
        "FA_remove_file": file_ops.remove_file,
        "FA_copy_all_file_to_dir": file_ops.copy_all_file_to_dir,
        "FA_copy_specify_extension_file": file_ops.copy_specify_extension_file,
        # Directories
        "FA_copy_dir": dir_ops.copy_dir,
        "FA_create_dir": dir_ops.create_dir,
        "FA_remove_dir_tree": dir_ops.remove_dir_tree,
        "FA_rename_dir": dir_ops.rename_dir,
        # Zip
        "FA_zip_dir": zip_ops.zip_dir,
        "FA_zip_file": zip_ops.zip_file,
        "FA_zip_info": zip_ops.zip_info,
        "FA_zip_file_info": zip_ops.zip_file_info,
        "FA_set_zip_password": zip_ops.set_zip_password,
        "FA_unzip_file": zip_ops.unzip_file,
        "FA_read_zip_file": zip_ops.read_zip_file,
        "FA_unzip_all": zip_ops.unzip_all,
    }


def _drive_commands() -> dict[str, Command]:
    from automation_file.remote.google_drive import (
        client,
        delete_ops,
        download_ops,
        folder_ops,
        search_ops,
        share_ops,
        upload_ops,
    )

    return {
        "FA_drive_later_init": client.driver_instance.later_init,
        "FA_drive_search_all_file": search_ops.drive_search_all_file,
        "FA_drive_search_field": search_ops.drive_search_field,
        "FA_drive_search_file_mimetype": search_ops.drive_search_file_mimetype,
        "FA_drive_upload_dir_to_folder": upload_ops.drive_upload_dir_to_folder,
        "FA_drive_upload_to_folder": upload_ops.drive_upload_to_folder,
        "FA_drive_upload_dir_to_drive": upload_ops.drive_upload_dir_to_drive,
        "FA_drive_upload_to_drive": upload_ops.drive_upload_to_drive,
        "FA_drive_add_folder": folder_ops.drive_add_folder,
        "FA_drive_share_file_to_anyone": share_ops.drive_share_file_to_anyone,
        "FA_drive_share_file_to_domain": share_ops.drive_share_file_to_domain,
        "FA_drive_share_file_to_user": share_ops.drive_share_file_to_user,
        "FA_drive_delete_file": delete_ops.drive_delete_file,
        "FA_drive_download_file": download_ops.drive_download_file,
        "FA_drive_download_file_from_folder": download_ops.drive_download_file_from_folder,
    }


def _http_commands() -> dict[str, Command]:
    from automation_file.remote import http_download

    return {"FA_download_file": http_download.download_file}


def _utils_commands() -> dict[str, Command]:
    from automation_file.utils import fast_find

    return {"FA_fast_find": fast_find.fast_find}


def _register_cloud_backends(registry: ActionRegistry) -> None:
    from automation_file.remote.azure_blob import register_azure_blob_ops
    from automation_file.remote.dropbox_api import register_dropbox_ops
    from automation_file.remote.s3 import register_s3_ops
    from automation_file.remote.sftp import register_sftp_ops

    register_s3_ops(registry)
    register_azure_blob_ops(registry)
    register_dropbox_ops(registry)
    register_sftp_ops(registry)


def _register_trigger_ops(registry: ActionRegistry) -> None:
    from automation_file.trigger import register_trigger_ops

    register_trigger_ops(registry)


def _register_scheduler_ops(registry: ActionRegistry) -> None:
    from automation_file.scheduler import register_scheduler_ops

    register_scheduler_ops(registry)


def _register_progress_ops(registry: ActionRegistry) -> None:
    from automation_file.core.progress import register_progress_ops

    register_progress_ops(registry)


def build_default_registry() -> ActionRegistry:
    """Return a registry pre-populated with every built-in ``FA_*`` action."""
    registry = ActionRegistry()
    registry.register_many(_local_commands())
    registry.register_many(_http_commands())
    registry.register_many(_utils_commands())
    registry.register_many(_drive_commands())
    _register_cloud_backends(registry)
    _register_trigger_ops(registry)
    _register_scheduler_ops(registry)
    _register_progress_ops(registry)
    file_automation_logger.info(
        "action_registry: built default registry with %d commands", len(registry)
    )
    return registry
