import builtins
import types
from inspect import getmembers, isbuiltin
from typing import Union, Any

from file_automation.local.dir.dir_process import copy_dir, create_dir, remove_dir_tree
from file_automation.local.file.file_process import copy_file, remove_file, rename_file, copy_specify_extension_file, \
    copy_all_file_to_dir, create_file
from file_automation.local.zip.zip_process import zip_dir, zip_file, zip_info, zip_file_info, set_zip_password, \
    read_zip_file, unzip_file, unzip_all
from file_automation.remote.google_drive.delete.delete_manager import drive_delete_file
from file_automation.remote.google_drive.dir.folder_manager import drive_add_folder
from file_automation.remote.google_drive.download.download_file import drive_download_file, \
    drive_download_file_from_folder
from file_automation.remote.google_drive.driver_instance import driver_instance
from file_automation.remote.google_drive.search.search_drive import \
    drive_search_all_file, drive_search_field, drive_search_file_mimetype
from file_automation.remote.google_drive.share.share_file import \
    drive_share_file_to_anyone, drive_share_file_to_domain, drive_share_file_to_user
from file_automation.remote.google_drive.upload.upload_to_driver import \
    drive_upload_dir_to_folder, drive_upload_to_folder, drive_upload_dir_to_drive, drive_upload_to_drive
from file_automation.utils.exception.exception_tags import add_command_exception, executor_list_error, \
    action_is_null_error, cant_execute_action_error
from file_automation.utils.exception.exceptions import ExecuteActionException, AddCommandException
from file_automation.utils.json.json_file import read_action_json
from file_automation.utils.logging.loggin_instance import file_automation_logger
from file_automation.utils.package_manager.package_manager_class import package_manager
from file_automation.utils.scheduler.extend_apscheduler import scheduler_manager


class Executor(object):

    def __init__(self):
        self.event_dict: dict = {
            # File
            "create_file": create_file,
            "copy_file": copy_file,
            "rename_file": rename_file,
            "remove_file": remove_file,
            # Dir
            "copy_all_file_to_dir": copy_all_file_to_dir,
            "copy_specify_extension_file": copy_specify_extension_file,
            "copy_dir": copy_dir,
            "create_dir": create_dir,
            "remove_dir_tree": remove_dir_tree,
            # Zip
            "zip_dir": zip_dir,
            "zip_file": zip_file,
            "zip_info": zip_info,
            "zip_file_info": zip_file_info,
            "set_zip_password": set_zip_password,
            "unzip_file": unzip_file,
            "read_zip_file": read_zip_file,
            "unzip_all": unzip_all,
            # Drive
            "drive_later_init": driver_instance.later_init,
            "drive_search_all_file": drive_search_all_file,
            "drive_search_field": drive_search_field,
            "drive_search_file_mimetype": drive_search_file_mimetype,
            "drive_upload_dir_to_folder": drive_upload_dir_to_folder,
            "drive_upload_to_folder": drive_upload_to_folder,
            "drive_upload_dir_to_drive": drive_upload_dir_to_drive,
            "drive_upload_to_drive": drive_upload_to_drive,
            "drive_add_folder": drive_add_folder,
            "drive_share_file_to_anyone": drive_share_file_to_anyone,
            "drive_share_file_to_domain": drive_share_file_to_domain,
            "drive_share_file_to_user": drive_share_file_to_user,
            "drive_delete_file": drive_delete_file,
            "drive_download_file": drive_download_file,
            "drive_download_file_from_folder": drive_download_file_from_folder,
            # Execute
            "execute_action": self.execute_action,
            "execute_files": self.execute_files,
            "add_package_to_executor": package_manager.add_package_to_executor,
            # Scheduler
            "scheduler_event_trigger": self.scheduler_event_trigger,
            "remove_blocking_scheduler_job": scheduler_manager.remove_blocking_job,
            "remove_nonblocking_scheduler_job": scheduler_manager.remove_nonblocking_job,
            "start_blocking_scheduler": scheduler_manager.start_block_scheduler,
            "start_nonblocking_scheduler": scheduler_manager.start_nonblocking_scheduler,
            "start_all_scheduler": scheduler_manager.start_all_scheduler,
            "shutdown_blocking_scheduler": scheduler_manager.shutdown_blocking_scheduler,
            "shutdown_nonblocking_scheduler": scheduler_manager.shutdown_nonblocking_scheduler,
        }
        # get all builtin function and add to event dict
        for function in getmembers(builtins, isbuiltin):
            self.event_dict.update({str(function[0]): function[1]})

    def _execute_event(self, action: list):
        event = self.event_dict.get(action[0])
        if len(action) == 2:
            if isinstance(action[1], dict):
                return event(**action[1])
            else:
                return event(*action[1])
        elif len(action) == 1:
            return event()
        else:
            raise ExecuteActionException(cant_execute_action_error + " " + str(action))

    def execute_action(self, action_list: [list, dict]) -> dict:
        """
        use to execute all action on action list(action file or program list)
        :param action_list the list include action
        for loop the list and execute action
        """
        if isinstance(action_list, dict):
            action_list: list = action_list.get("auto_control", None)
            if action_list is None:
                raise ExecuteActionException(executor_list_error)
        execute_record_dict = dict()
        try:
            if len(action_list) > 0 or isinstance(action_list, list):
                pass
            else:
                raise ExecuteActionException(action_is_null_error)
        except Exception as error:
            file_automation_logger.error(
                f"Execute {action_list} failed. {repr(error)}"
            )
        for action in action_list:
            try:
                event_response = self._execute_event(action)
                execute_record = "execute: " + str(action)
                file_automation_logger.info(
                    f"Execute {action}"
                )
                execute_record_dict.update({execute_record: event_response})
            except Exception as error:
                file_automation_logger.error(
                    f"Execute {action} failed. {repr(error)}"
                )
                execute_record = "execute: " + str(action)
                execute_record_dict.update({execute_record: repr(error)})
        for key, value in execute_record_dict.items():
            print(key, flush=True)
            print(value, flush=True)
        return execute_record_dict

    def execute_files(self, execute_files_list: list) -> list:
        """
        :param execute_files_list: list include execute files path
        :return: every execute detail as list
        """
        execute_detail_list: list = list()
        for file in execute_files_list:
            execute_detail_list.append(self.execute_action(read_action_json(file)))
        return execute_detail_list

    def scheduler_event_trigger(
            self, function: str, id: str = None, args: Union[list, tuple] = None,
            kwargs: dict = None, scheduler_type: str = "nonblocking", wait_type: str = "secondly",
            wait_value: int = 1, **trigger_args: Any) -> None:
        if scheduler_type == "nonblocking":
            scheduler_event = scheduler_manager.nonblocking_scheduler_event_dict.get(wait_type)
        else:
            scheduler_event = scheduler_manager.blocking_scheduler_event_dict.get(wait_type)
        scheduler_event(self.event_dict.get(function), id, args, kwargs, wait_value, **trigger_args)


executor = Executor()
package_manager.executor = executor


def add_command_to_executor(command_dict: dict):
    """
    :param command_dict: dict include command we want to add to event_dict
    """
    file_automation_logger.info(
        f"Add command to executor {command_dict}"
    )
    for command_name, command in command_dict.items():
        if isinstance(command, (types.MethodType, types.FunctionType)):
            executor.event_dict.update({command_name: command})
        else:
            raise AddCommandException(add_command_exception)


def execute_action(action_list: list) -> dict:
    return executor.execute_action(action_list)


def execute_files(execute_files_list: list) -> list:
    return executor.execute_files(execute_files_list)
