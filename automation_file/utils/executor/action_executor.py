import builtins
import types
from inspect import getmembers, isbuiltin
from typing import Union, Any

from automation_file.local.dir.dir_process import copy_dir, create_dir, remove_dir_tree
from automation_file.local.file.file_process import copy_file, remove_file, rename_file, copy_specify_extension_file, \
    copy_all_file_to_dir, create_file
from automation_file.local.zip.zip_process import zip_dir, zip_file, zip_info, zip_file_info, set_zip_password, \
    read_zip_file, unzip_file, unzip_all
from automation_file.remote.google_drive.delete.delete_manager import drive_delete_file
from automation_file.remote.google_drive.dir.folder_manager import drive_add_folder
from automation_file.remote.google_drive.download.download_file import drive_download_file, \
    drive_download_file_from_folder
from automation_file.remote.google_drive.driver_instance import driver_instance
from automation_file.remote.google_drive.search.search_drive import \
    drive_search_all_file, drive_search_field, drive_search_file_mimetype
from automation_file.remote.google_drive.share.share_file import \
    drive_share_file_to_anyone, drive_share_file_to_domain, drive_share_file_to_user
from automation_file.remote.google_drive.upload.upload_to_driver import \
    drive_upload_dir_to_folder, drive_upload_to_folder, drive_upload_dir_to_drive, drive_upload_to_drive
from automation_file.utils.exception.exception_tags import add_command_exception, executor_list_error, \
    action_is_null_error, cant_execute_action_error
from automation_file.utils.exception.exceptions import ExecuteActionException, AddCommandException
from automation_file.utils.json.json_file import read_action_json
from automation_file.utils.logging.loggin_instance import file_automation_logger
from automation_file.utils.package_manager.package_manager_class import package_manager


class Executor(object):

    def __init__(self):
        self.event_dict: dict = {
            # File
            "FA_create_file": create_file,
            "FA_copy_file": copy_file,
            "FA_rename_file": rename_file,
            "FA_remove_file": remove_file,
            # Dir
            "FA_copy_all_file_to_dir": copy_all_file_to_dir,
            "FA_copy_specify_extension_file": copy_specify_extension_file,
            "FA_copy_dir": copy_dir,
            "FA_create_dir": create_dir,
            "FA_remove_dir_tree": remove_dir_tree,
            # Zip
            "FA_zip_dir": zip_dir,
            "FA_zip_file": zip_file,
            "FA_zip_info": zip_info,
            "FA_zip_file_info": zip_file_info,
            "FA_set_zip_password": set_zip_password,
            "FA_unzip_file": unzip_file,
            "FA_read_zip_file": read_zip_file,
            "FA_unzip_all": unzip_all,
            # Drive
            "FA_drive_later_init": driver_instance.later_init,
            "FA_drive_search_all_file": drive_search_all_file,
            "FA_drive_search_field": drive_search_field,
            "FA_drive_search_file_mimetype": drive_search_file_mimetype,
            "FA_drive_upload_dir_to_folder": drive_upload_dir_to_folder,
            "FA_drive_upload_to_folder": drive_upload_to_folder,
            "FA_drive_upload_dir_to_drive": drive_upload_dir_to_drive,
            "FA_drive_upload_to_drive": drive_upload_to_drive,
            "FA_drive_add_folder": drive_add_folder,
            "FA_drive_share_file_to_anyone": drive_share_file_to_anyone,
            "FA_drive_share_file_to_domain": drive_share_file_to_domain,
            "FA_drive_share_file_to_user": drive_share_file_to_user,
            "FA_drive_delete_file": drive_delete_file,
            "FA_drive_download_file": drive_download_file,
            "FA_drive_download_file_from_folder": drive_download_file_from_folder,
            # Execute
            "FA_execute_action": self.execute_action,
            "FA_execute_files": self.execute_files,
            "FA_add_package_to_executor": package_manager.add_package_to_executor,
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
            action_list: list = action_list.get("auto_control")
            if action_list is None:
                raise ExecuteActionException(executor_list_error)
        execute_record_dict = dict()
        try:
            if len(action_list) == 0 or isinstance(action_list, list) is False:
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
