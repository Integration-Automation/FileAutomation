import typing

from file_automation.local.dir.dir_process import copy_dir, create_dir, remove_dir_tree
from file_automation.local.file.file_process import copy_file, remove_file, rename_file, copy_specify_extension_file, \
    copy_all_file_to_dir
from file_automation.local.zip.zip_process import zip_dir, zip_file, zip_info, zip_file_info, set_zip_password, \
    read_zip_file, unzip_file, unzip_all
from file_automation.remote.google_drive.delete.delete_manager import drive_delete_file
from file_automation.remote.google_drive.dir.folder_manager import drive_add_folder
from file_automation.remote.google_drive.download.download_file import drive_download_file, drive_download_file_from_folder
from file_automation.remote.google_drive.driver_instance import driver_instance
from file_automation.remote.google_drive.search.search_drive import \
    drive_search_all_file, drive_search_field, drive_search_file_mimetype
from file_automation.remote.google_drive.share.share_file import \
    drive_share_file_to_anyone, drive_share_file_to_domain, drive_share_file_to_user
from file_automation.remote.google_drive.upload.upload_to_driver import \
    drive_upload_dir_to_folder, drive_upload_to_folder, drive_upload_dir_to_drive, drive_upload_to_drive
from file_automation.utils.exception.exception_tags import get_bad_trigger_function, get_bad_trigger_method
from file_automation.utils.exception.exceptions import CallbackExecutorException
from file_automation.utils.logging.loggin_instance import file_automation_logger


class CallbackFunctionExecutor(object):

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
            "search_all_file": drive_search_all_file,
            "search_field": drive_search_field,
            "search_file_mimetype": drive_search_file_mimetype,
            "upload_dir_to_folder": drive_upload_dir_to_folder,
            "upload_to_folder": drive_upload_to_folder,
            "upload_dir_to_drive": drive_upload_dir_to_drive,
            "upload_to_drive": drive_upload_to_drive,
            "add_folder": drive_add_folder,
            "share_file_to_anyone": drive_share_file_to_anyone,
            "share_file_to_domain": drive_share_file_to_domain,
            "share_file_to_user": drive_share_file_to_user,
            "delete_file": drive_delete_file,
            "download_file": drive_download_file,
            "download_file_from_folder": drive_download_file_from_folder
        }

    def callback_function(
            self,
            trigger_function_name: str,
            callback_function: typing.Callable,
            callback_function_param: [dict, None] = None,
            callback_param_method: str = "kwargs",
            **kwargs
    ) -> typing.Any:
        """
        :param trigger_function_name: what function we want to trigger only accept function in event_dict
        :param callback_function: what function we want to callback
        :param callback_function_param: callback function's param only accept dict 
        :param callback_param_method: what type param will use on callback function only accept kwargs and args
        :param kwargs: trigger_function's param
        :return: trigger_function_name return value
        """
        try:
            if trigger_function_name not in self.event_dict.keys():
                raise CallbackExecutorException(get_bad_trigger_function)
            file_automation_logger.info(f"Callback trigger {trigger_function_name} with param {kwargs}")
            execute_return_value = self.event_dict.get(trigger_function_name)(**kwargs)
            if callback_function_param is not None:
                if callback_param_method not in ["kwargs", "args"]:
                    raise CallbackExecutorException(get_bad_trigger_method)
                if callback_param_method == "kwargs":
                    callback_function(**callback_function_param)
                    file_automation_logger.info(
                        f"Callback function {callback_function} with param {callback_function_param}")
                else:
                    callback_function(*callback_function_param)
                    file_automation_logger.info(
                        f"Callback function {callback_function} with param {callback_function_param}")
            else:
                callback_function()
                file_automation_logger.info(f"Callback function {callback_function}")
            return execute_return_value
        except Exception as error:
            file_automation_logger.error(
                f"Callback function failed. {repr(error)}")


callback_executor = CallbackFunctionExecutor()

