"""CLI entry point (``python -m automation_file``).

Supports three invocation styles:

* Legacy flags (``-e``, ``-d``, ``-c``, ``--execute_str``) — run JSON action
  lists without writing Python.
* Subcommands (``zip``, ``unzip``, ``download``, ``server``, ``http-server``,
  ``drive-upload``, ``ui``) — wrap the most common facade calls so users do
  not need to hand-author JSON for one-shot operations.
* No arguments — prints help and exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from typing import Any

from automation_file.core.action_executor import execute_action, execute_files
from automation_file.core.json_store import read_action_json
from automation_file.exceptions import ArgparseException
from automation_file.local.file_ops import create_file
from automation_file.local.zip_ops import unzip_all, zip_dir, zip_file
from automation_file.project.project_builder import create_project_dir
from automation_file.remote.http_download import download_file
from automation_file.utils.file_discovery import get_dir_files_as_list


def _execute_file(path: str) -> Any:
    return execute_action(read_action_json(path))


def _execute_dir(path: str) -> Any:
    return execute_files(get_dir_files_as_list(path))


def _execute_str(raw: str) -> Any:
    return execute_action(json.loads(raw))


_LEGACY_DISPATCH: dict[str, Callable[[str], Any]] = {
    "execute_file": _execute_file,
    "execute_dir": _execute_dir,
    "execute_str": _execute_str,
    "create_project": create_project_dir,
}


def _cmd_zip(args: argparse.Namespace) -> int:
    if args.source_is_dir:
        zip_dir(args.source, args.target)
    else:
        zip_file(args.source, args.target)
    return 0


def _cmd_unzip(args: argparse.Namespace) -> int:
    unzip_all(args.archive, args.target_dir, password=args.password)
    return 0


def _cmd_download(args: argparse.Namespace) -> int:
    ok = download_file(args.url, args.output)
    return 0 if ok else 1


def _cmd_create_file(args: argparse.Namespace) -> int:
    create_file(args.path, args.content or "")
    return 0


def _cmd_server(args: argparse.Namespace) -> int:
    from automation_file.server.tcp_server import start_autocontrol_socket_server

    start_autocontrol_socket_server(
        host=args.host,
        port=args.port,
        allow_non_loopback=args.allow_non_loopback,
        shared_secret=args.shared_secret,
    )
    _sleep_forever()
    return 0


def _cmd_http_server(args: argparse.Namespace) -> int:
    from automation_file.server.http_server import start_http_action_server

    start_http_action_server(
        host=args.host,
        port=args.port,
        allow_non_loopback=args.allow_non_loopback,
        shared_secret=args.shared_secret,
    )
    _sleep_forever()
    return 0


def _cmd_ui(_args: argparse.Namespace) -> int:
    from automation_file.ui.launcher import launch_ui

    return launch_ui()


def _cmd_mcp(args: argparse.Namespace) -> int:
    from automation_file.server.mcp_server import _cli as mcp_cli

    forwarded: list[str] = ["--name", args.name, "--version", args.version]
    if args.allowed_actions:
        forwarded.extend(["--allowed-actions", args.allowed_actions])
    return mcp_cli(forwarded)


def _cmd_drive_upload(args: argparse.Namespace) -> int:
    from automation_file.remote.google_drive.client import driver_instance
    from automation_file.remote.google_drive.upload_ops import (
        drive_upload_to_drive,
        drive_upload_to_folder,
    )

    driver_instance.later_init(args.token, args.credentials)
    if args.folder_id:
        result = drive_upload_to_folder(args.folder_id, args.file, args.name)
    else:
        result = drive_upload_to_drive(args.file, args.name)
    return 0 if result is not None else 1


def _sleep_forever() -> None:
    while True:
        time.sleep(3600)


def _add_zip_commands(subparsers: argparse._SubParsersAction) -> None:
    zip_parser = subparsers.add_parser("zip", help="zip a file or directory")
    zip_parser.add_argument("source")
    zip_parser.add_argument("target")
    zip_parser.add_argument(
        "--dir",
        dest="source_is_dir",
        action="store_true",
        help="treat source as a directory (zips the tree instead of one file)",
    )
    zip_parser.set_defaults(handler=_cmd_zip)

    unzip_parser = subparsers.add_parser("unzip", help="extract an archive")
    unzip_parser.add_argument("archive")
    unzip_parser.add_argument("target_dir")
    unzip_parser.add_argument("--password", default=None)
    unzip_parser.set_defaults(handler=_cmd_unzip)


def _add_file_commands(subparsers: argparse._SubParsersAction) -> None:
    download_parser = subparsers.add_parser("download", help="SSRF-validated HTTP download")
    download_parser.add_argument("url")
    download_parser.add_argument("output")
    download_parser.set_defaults(handler=_cmd_download)

    touch_parser = subparsers.add_parser("create-file", help="write a text file")
    touch_parser.add_argument("path")
    touch_parser.add_argument("--content", default="")
    touch_parser.set_defaults(handler=_cmd_create_file)


def _add_server_commands(subparsers: argparse._SubParsersAction) -> None:
    server_parser = subparsers.add_parser("server", help="run the TCP action server")
    server_parser.add_argument("--host", default="localhost")
    server_parser.add_argument("--port", type=int, default=9943)
    server_parser.add_argument("--allow-non-loopback", action="store_true")
    server_parser.add_argument("--shared-secret", default=None)
    server_parser.set_defaults(handler=_cmd_server)

    http_parser = subparsers.add_parser("http-server", help="run the HTTP action server")
    http_parser.add_argument("--host", default="127.0.0.1")
    http_parser.add_argument("--port", type=int, default=9944)
    http_parser.add_argument("--allow-non-loopback", action="store_true")
    http_parser.add_argument("--shared-secret", default=None)
    http_parser.set_defaults(handler=_cmd_http_server)


def _add_integration_commands(subparsers: argparse._SubParsersAction) -> None:
    ui_parser = subparsers.add_parser("ui", help="launch the PySide6 GUI")
    ui_parser.set_defaults(handler=_cmd_ui)

    mcp_parser = subparsers.add_parser(
        "mcp", help="serve the action registry as an MCP server over stdio"
    )
    mcp_parser.add_argument("--name", default="automation_file")
    mcp_parser.add_argument("--version", default="1.0.0")
    mcp_parser.add_argument(
        "--allowed-actions",
        default=None,
        help="comma-separated allow list (default: expose every registered action)",
    )
    mcp_parser.set_defaults(handler=_cmd_mcp)

    drive_parser = subparsers.add_parser("drive-upload", help="upload a file to Google Drive")
    drive_parser.add_argument("file")
    drive_parser.add_argument("--token", required=True)
    drive_parser.add_argument("--credentials", required=True)
    drive_parser.add_argument("--folder-id", default=None)
    drive_parser.add_argument("--name", default=None)
    drive_parser.set_defaults(handler=_cmd_drive_upload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="automation_file")
    parser.add_argument("-e", "--execute_file", help="path to an action JSON file")
    parser.add_argument("-d", "--execute_dir", help="directory containing action JSON files")
    parser.add_argument("-c", "--create_project", help="scaffold a project at this path")
    parser.add_argument("--execute_str", help="JSON action list as a string")

    subparsers = parser.add_subparsers(dest="command")
    _add_zip_commands(subparsers)
    _add_file_commands(subparsers)
    _add_server_commands(subparsers)
    _add_integration_commands(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None):
        return args.handler(args)

    ran = False
    for key, handler in _LEGACY_DISPATCH.items():
        value = getattr(args, key, None)
        if value is None:
            continue
        handler(value)
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
