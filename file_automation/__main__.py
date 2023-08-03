# argparse
import argparse
import json
import sys

from file_automation.utils.exception.exception_tags import \
    argparse_get_wrong_data
from file_automation.utils.exception.exceptions import \
    ArgparseException
from file_automation.utils.executor.action_executor import execute_action
from file_automation.utils.executor.action_executor import execute_files
from file_automation.utils.file_process.get_dir_file_list import \
    get_dir_files_as_list
from file_automation.utils.json.json_file import read_action_json
from file_automation.utils.project.create_project_structure import create_project_dir

if __name__ == "__main__":
    try:
        def preprocess_execute_action(file_path: str):
            execute_action(read_action_json(file_path))


        def preprocess_execute_files(file_path: str):
            execute_files(get_dir_files_as_list(file_path))


        def preprocess_read_str_execute_action(execute_str: str):
            execute_str = json.loads(execute_str)
            execute_action(execute_str)


        argparse_event_dict = {
            "execute_file": preprocess_execute_action,
            "execute_dir": preprocess_execute_files,
            "execute_str": preprocess_read_str_execute_action,
            "create_project": create_project_dir
        }
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-e", "--execute_file",
            type=str, help="choose action file to execute"
        )
        parser.add_argument(
            "-d", "--execute_dir",
            type=str, help="choose dir include action file to execute"
        )
        parser.add_argument(
            "-c", "--create_project",
            type=str, help="create project with template"
        )
        parser.add_argument(
            "--execute_str",
            type=str, help="execute json str"
        )
        args = parser.parse_args()
        args = vars(args)
        for key, value in args.items():
            if value is not None:
                argparse_event_dict.get(key)(value)
        if all(value is None for value in args.values()):
            raise ArgparseException(argparse_get_wrong_data)
    except Exception as error:
        print(repr(error), file=sys.stderr)
        sys.exit(1)
