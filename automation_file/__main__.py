"""CLI entry point (``python -m automation_file``)."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from automation_file.core.action_executor import execute_action, execute_files
from automation_file.core.json_store import read_action_json
from automation_file.exceptions import ArgparseException
from automation_file.project.project_builder import create_project_dir
from automation_file.utils.file_discovery import get_dir_files_as_list


def _execute_file(path: str) -> Any:
    return execute_action(read_action_json(path))


def _execute_dir(path: str) -> Any:
    return execute_files(get_dir_files_as_list(path))


def _execute_str(raw: str) -> Any:
    return execute_action(json.loads(raw))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="automation_file")
    parser.add_argument("-e", "--execute_file", help="path to an action JSON file")
    parser.add_argument("-d", "--execute_dir", help="directory containing action JSON files")
    parser.add_argument("-c", "--create_project", help="scaffold a project at this path")
    parser.add_argument("--execute_str", help="JSON action list as a string")
    return parser


_DISPATCH: dict[str, Callable[[str], Any]] = {
    "execute_file": _execute_file,
    "execute_dir": _execute_dir,
    "execute_str": _execute_str,
    "create_project": create_project_dir,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = vars(parser.parse_args(argv))
    ran = False
    for key, value in args.items():
        if value is None:
            continue
        _DISPATCH[key](value)
        ran = True
    if not ran:
        raise ArgparseException("no argument supplied; try --help")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ArgparseException as error:
        print(repr(error), file=sys.stderr)
        sys.exit(1)
    except Exception as error:  # pylint: disable=broad-except
        print(repr(error), file=sys.stderr)
        sys.exit(1)
