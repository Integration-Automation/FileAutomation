import builtins
import sys
import types
from inspect import getmembers, isbuiltin

from file_automation.local.dir.dir_process import copy_dir, create_dir, remove_dir_tree
from file_automation.local.file.file_process import copy_file, remove_file, rename_file, copy_specify_extension_file, \
    copy_all_file_to_dir
from file_automation.local.zip.zip_process import zip_dir, zip_file, zip_info, zip_file_info, set_zip_password, \
    read_zip_file, unzip_file, unzip_all
from file_automation.remote.google_drive.delete.delete_manager import delete_file
from file_automation.remote.google_drive.dir.folder_manager import add_folder
from file_automation.remote.google_drive.download.download_file import download_file, download_file_from_folder
from file_automation.remote.google_drive.driver_instance import driver_instance
from file_automation.remote.google_drive.search.search_drive import \
    search_all_file, search_field, search_file_mimetype
from file_automation.remote.google_drive.share.share_file import \
    share_file_to_anyone, share_file_to_domain, share_file_to_user
from file_automation.remote.google_drive.upload.upload_to_driver import \
    upload_dir_to_folder, upload_to_folder, upload_dir_to_drive, upload_to_drive
from file_automation.utils.exception.exception_tags import add_command_exception, executor_list_error, \
    action_is_null_error, cant_execute_action_error
from file_automation.utils.exception.exceptions import ExecuteActionException, AddCommandException
from file_automation.utils.json.json_file import read_action_json


class Executor(object):

    def __init__(self):
        self.event_dict: dict = {
            "copy_file": copy_file,
            "rename_file": rename_file,
            "remove_file": remove_file,
            "copy_all_file_to_dir": copy_all_file_to_dir,
            "copy_specify_extension_file": copy_specify_extension_file,
            "copy_dir": copy_dir,
            "create_dir": create_dir,
            "remove_dir_tree": remove_dir_tree,
            "zip_dir": zip_dir,
            "zip_file": zip_file,
            "zip_info": zip_info,
            "zip_file_info": zip_file_info,
            "set_zip_password": set_zip_password,
            "unzip_file": unzip_file,
            "read_zip_file": read_zip_file,
            "unzip_all": unzip_all,
            "driver_instance": driver_instance,
            "search_all_file": search_all_file,
            "search_field": search_field,
            "search_file_mimetype": search_file_mimetype,
            "upload_dir_to_folder": upload_dir_to_folder,
            "upload_to_folder": upload_to_folder,
            "upload_dir_to_drive": upload_dir_to_drive,
            "upload_to_drive": upload_to_drive,
            "add_folder": add_folder,
            "share_file_to_anyone": share_file_to_anyone,
            "share_file_to_domain": share_file_to_domain,
            "share_file_to_user": share_file_to_user,
            "delete_file": delete_file,
            "download_file": download_file,
            "download_file_from_folder": download_file_from_folder
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
            print(repr(error), file=sys.stderr, flush=True)
        for action in action_list:
            try:
                event_response = self._execute_event(action)
                execute_record = "execute: " + str(action)
                execute_record_dict.update({execute_record: event_response})
            except Exception as error:
                print(repr(error), file=sys.stderr, flush=True)
                print(action, file=sys.stderr, flush=True)
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


def add_command_to_executor(command_dict: dict):
    """
    :param command_dict: dict include command we want to add to event_dict
    """
    for command_name, command in command_dict.items():
        if isinstance(command, (types.MethodType, types.FunctionType)):
            executor.event_dict.update({command_name: command})
        else:
            raise AddCommandException(add_command_exception)


def execute_action(action_list: list) -> dict:
    return executor.execute_action(action_list)


def execute_files(execute_files_list: list) -> list:
    return executor.execute_files(execute_files_list)
