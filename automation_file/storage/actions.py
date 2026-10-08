"""``FA_storage_*`` actions: the storage layer for JSON action lists.

Each function takes storage URIs as plain strings and returns JSON-friendly
values, so the same call works from Python, an action file, the CLI, the TCP and
HTTP action servers and as an MCP tool:

.. code-block:: json

    [
        ["FA_storage_copy", {"source": "s3://reports/q1.csv", "target": "local:///backup/q1.csv"}],
        ["FA_storage_checksum", {"uri": "local:///backup/q1.csv"}]
    ]

A ``FileInfo`` comes back as its ``to_dict()`` form plus a ``"uri"`` key. Failures
raise the storage layer's exceptions; the executor records them per action.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from automation_file.logging_config import file_automation_logger
from automation_file.storage.backend import DEFAULT_CHECKSUM_ALGORITHM
from automation_file.storage.file import File
from automation_file.storage.storage import Storage
from automation_file.storage.types import FileInfo

if TYPE_CHECKING:
    from automation_file.core.action_registry import ActionRegistry

_DEFAULT_ENCODING = "utf-8"


def _described(info: FileInfo, uri: str) -> dict[str, Any]:
    return {"uri": uri, **info.to_dict()}


def storage_exists(uri: str) -> bool:
    """Return whether a file or a directory is at ``uri``."""
    return File(uri).exists()


def storage_stat(uri: str) -> dict[str, Any]:
    """Return the size, modification time and other metadata of ``uri``."""
    target = File(uri)
    return _described(target.stat(), str(target))


def storage_list(uri: str, recursive: bool = False) -> list[dict[str, Any]]:
    """List the directory ``uri``; ``recursive`` adds every descendant.

    Each entry's ``path`` is relative to ``uri`` and its ``uri`` is absolute.
    """
    directory = Storage(uri)
    return [
        _described(info, str(directory.uri.joinpath(info.path)))
        for info in directory.list_dir(recursive=recursive)
    ]


def storage_mkdir(uri: str, parents: bool = True, exist_ok: bool = True) -> bool:
    """Create the directory ``uri``."""
    Storage(uri).mkdir(parents=parents, exist_ok=exist_ok)
    file_automation_logger.info("storage_mkdir: %s", uri)
    return True


def storage_upload(local_path: str, uri: str, overwrite: bool = True) -> dict[str, Any]:
    """Store the local file ``local_path`` at ``uri``."""
    target = File(uri)
    info = target.upload_from(local_path, overwrite=overwrite)
    file_automation_logger.info("storage_upload: %s -> %s", local_path, target)
    return _described(info, str(target))


def storage_download(uri: str, local_path: str, overwrite: bool = True) -> str:
    """Write the file ``uri`` to ``local_path`` and return that path."""
    source = File(uri)
    written = source.download_to(local_path, overwrite=overwrite)
    file_automation_logger.info("storage_download: %s -> %s", source, written)
    return str(written)


def storage_delete(uri: str, recursive: bool = False, missing_ok: bool = False) -> bool:
    """Remove the file or directory at ``uri``; a directory with entries needs ``recursive``."""
    target = Storage(uri)
    target.delete("", recursive=recursive, missing_ok=missing_ok)
    file_automation_logger.info("storage_delete: %s (recursive=%s)", target, recursive)
    return True


def storage_checksum(uri: str, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> dict[str, str]:
    """Return ``{"algorithm": ..., "value": ...}`` for the content of ``uri``."""
    return File(uri).checksum(algorithm).to_dict()


def storage_verify(uri: str, expected: str, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> bool:
    """Return whether ``uri`` has the digest ``expected`` (``"sha256:..."`` or a bare digest)."""
    matched = File(uri).verify(expected, algorithm=algorithm)
    if not matched:
        file_automation_logger.warning("storage_verify mismatch: %s", uri)
    return matched


def storage_copy(source: str, target: str, overwrite: bool = True) -> dict[str, Any]:
    """Copy the file ``source`` to ``target``, in the same backend or another one."""
    copied = File(source).copy_to(target, overwrite=overwrite)
    file_automation_logger.info("storage_copy: %s -> %s", source, copied)
    return _described(copied.stat(), str(copied))


def storage_move(source: str, target: str, overwrite: bool = True) -> dict[str, Any]:
    """Move the file ``source`` to ``target``, in the same backend or another one."""
    moved = File(source).move_to(target, overwrite=overwrite)
    file_automation_logger.info("storage_move: %s -> %s", source, moved)
    return _described(moved.stat(), str(moved))


def storage_read_text(uri: str, encoding: str = _DEFAULT_ENCODING) -> str:
    """Return the content of ``uri`` decoded as text."""
    return File(uri).read_text(encoding)


def storage_write_text(
    uri: str, text: str, overwrite: bool = True, encoding: str = _DEFAULT_ENCODING
) -> dict[str, Any]:
    """Store ``text`` as the content of ``uri``."""
    target = File(uri)
    info = target.write(text, overwrite=overwrite, encoding=encoding)
    file_automation_logger.info("storage_write_text: %s", target)
    return _described(info, str(target))


def storage_copy_tree(source: str, target: str, overwrite: bool = True) -> dict[str, Any]:
    """Copy every file below the directory ``source`` to ``target``; returns a summary."""
    return Storage(source).copy_to(target, overwrite=overwrite).to_dict()


def storage_sync(
    source: str,
    target: str,
    delete: bool = False,
    checksum: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Mirror the directory ``source`` into ``target``, copying only what changed."""
    result = Storage(source).sync_to(target, delete=delete, checksum=checksum, dry_run=dry_run)
    return result.to_dict()


def storage_schemes() -> list[str]:
    """Return the URI schemes a backend is registered or mounted for."""
    return Storage.schemes()


def storage_commands() -> dict[str, Callable[..., Any]]:
    """Return every ``FA_storage_*`` action by name."""
    return {
        "FA_storage_exists": storage_exists,
        "FA_storage_stat": storage_stat,
        "FA_storage_list": storage_list,
        "FA_storage_mkdir": storage_mkdir,
        "FA_storage_upload": storage_upload,
        "FA_storage_download": storage_download,
        "FA_storage_delete": storage_delete,
        "FA_storage_checksum": storage_checksum,
        "FA_storage_verify": storage_verify,
        "FA_storage_copy": storage_copy,
        "FA_storage_move": storage_move,
        "FA_storage_read_text": storage_read_text,
        "FA_storage_write_text": storage_write_text,
        "FA_storage_copy_tree": storage_copy_tree,
        "FA_storage_sync": storage_sync,
        "FA_storage_schemes": storage_schemes,
    }


def register_storage_ops(registry: ActionRegistry) -> None:
    """Register every ``FA_storage_*`` command into ``registry``."""
    registry.register_many(storage_commands())
