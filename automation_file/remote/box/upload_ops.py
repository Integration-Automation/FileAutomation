"""Box upload operations."""

from __future__ import annotations

from pathlib import Path

from automation_file.exceptions import BoxException, FileNotExistsException
from automation_file.logging_config import file_automation_logger
from automation_file.remote._upload_tree import walk_and_upload
from automation_file.remote.box.client import box_instance


def box_upload_file(file_path: str, parent_folder_id: str = "0", name: str = "") -> str:
    """Upload a local file into ``parent_folder_id``; return the new Box file id.

    ``parent_folder_id`` defaults to ``"0"`` — Box's conventional id for
    the root folder of the authenticated user. ``name`` overrides the
    local filename on upload; empty means "use the source basename".
    """
    local = Path(file_path)
    if not local.is_file():
        raise FileNotExistsException(str(local))
    client = box_instance.require_client()
    target_name = name or local.name
    try:
        folder = client.folder(folder_id=parent_folder_id)
        new_file = folder.upload(file_path=str(local), file_name=target_name)
    except Exception as error:  # pylint: disable=broad-except
        raise BoxException(f"box_upload_file failed: {error}") from error
    file_automation_logger.info(
        "box_upload_file: %s -> %s/%s (id=%s)",
        local,
        parent_folder_id,
        target_name,
        getattr(new_file, "id", "?"),
    )
    return str(getattr(new_file, "id", ""))


def box_upload_dir(dir_path: str, parent_folder_id: str = "0") -> list[str]:
    """Upload every file under ``dir_path`` into ``parent_folder_id``.

    Box doesn't accept nested paths on upload — this helper flattens the
    tree, uploading each file with its relative path joined by ``/`` as
    the Box name. Folder hierarchy on Box is not mirrored; callers that
    need it should create folders first via the Box UI or SDK.
    """
    result = walk_and_upload(
        dir_path,
        "",
        lambda _prefix, rel: rel.replace("\\", "/"),
        lambda local, flat_name: box_upload_file(str(local), parent_folder_id, flat_name),
    )
    file_automation_logger.info(
        "box_upload_dir: %s -> folder %s (%d files)",
        result.source,
        parent_folder_id,
        len(result.uploaded),
    )
    return result.uploaded
