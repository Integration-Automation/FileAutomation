"""The ``FA_storage_*`` actions as a pipeline run through MCP may call them.

A pipeline task names an action and its arguments, and the arguments are only
known when the task runs (``${params.date}``, ``${tasks.fetch.result}``). The
policy therefore cannot be checked on the definition alone: these functions
take the place of the storage actions in the registry such a pipeline is given,
and each one checks the location and the permission at the moment it is called.

They take the same arguments and return the same values as the functions of
:mod:`automation_file.storage.actions`, with three differences:

* ``overwrite`` defaults to what the policy permits instead of ``True``, and an
  explicit ``overwrite: true`` is refused where the policy forbids it;
* ``FA_storage_verify`` also takes the result of ``FA_storage_checksum`` as its
  ``expected``, so ``"${tasks.digest.result}"`` compares two files;
* ``FA_storage_upload`` and ``FA_storage_download`` are missing: they take a
  filesystem path, which is not a storage URI the policy could check. Copy to or
  from a ``local://`` URI instead.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from automation_file.exceptions import StorageChecksumException, StorageException
from automation_file.server.mcp_policy import (
    LIMIT_EXCEEDED,
    OUTSIDE_ROOT,
    MCPLocationException,
    MCPPermissionException,
    MCPPolicy,
)
from automation_file.server.mcp_tool_model import ToolSession
from automation_file.storage.backend import DEFAULT_CHECKSUM_ALGORITHM
from automation_file.storage.file import File
from automation_file.storage.storage import Storage
from automation_file.storage.types import Checksum, FileInfo

_UTF8 = "utf-8"
_PREFIX = "FA_storage_"
EXISTS = f"{_PREFIX}exists"
STAT = f"{_PREFIX}stat"
LIST = f"{_PREFIX}list"
CHECKSUM = f"{_PREFIX}checksum"
VERIFY = f"{_PREFIX}verify"
READ_TEXT = f"{_PREFIX}read_text"
SCHEMES = f"{_PREFIX}schemes"
MKDIR = f"{_PREFIX}mkdir"
WRITE_TEXT = f"{_PREFIX}write_text"
COPY = f"{_PREFIX}copy"
COPY_TREE = f"{_PREFIX}copy_tree"
SYNC = f"{_PREFIX}sync"
MOVE = f"{_PREFIX}move"
DELETE = f"{_PREFIX}delete"

#: The guarded actions by the permission each one needs.
READ_ACTIONS: frozenset[str] = frozenset({EXISTS, STAT, LIST, CHECKSUM, VERIFY, READ_TEXT, SCHEMES})
WRITE_ACTIONS: frozenset[str] = frozenset({MKDIR, WRITE_TEXT, COPY, COPY_TREE})
OVERWRITE_ACTIONS: frozenset[str] = frozenset({SYNC})
DELETE_ACTIONS: frozenset[str] = frozenset({MOVE, DELETE})
GUARDED_ACTIONS: frozenset[str] = READ_ACTIONS | WRITE_ACTIONS | OVERWRITE_ACTIONS | DELETE_ACTIONS


def default_pipeline_actions(policy: MCPPolicy) -> frozenset[str]:
    """Return the actions a pipeline may call when the policy names none: what it permits."""
    allowed = set(READ_ACTIONS)
    if policy.allow_write:
        allowed |= WRITE_ACTIONS
        if policy.allow_overwrite:
            allowed |= OVERWRITE_ACTIONS
        if policy.allow_delete:
            allowed |= DELETE_ACTIONS
    return frozenset(allowed)


def _described(info: FileInfo, uri: object) -> dict[str, Any]:
    return {"uri": str(uri), **info.to_dict()}


def _expected_digest(expected: object) -> str | Checksum:
    """Return what a file is to be compared with: digest text, or a checksum result."""
    if isinstance(expected, str):
        return expected
    if isinstance(expected, Mapping):
        algorithm, value = expected.get("algorithm"), expected.get("value")
        if isinstance(algorithm, str) and isinstance(value, str):
            return Checksum(algorithm, value)
    raise StorageException(
        "expected must be a hex digest, '<algorithm>:<hex>' or the result of FA_storage_checksum"
    )


class GuardedStorageActions:
    """The storage actions bound to one session's policy and guard."""

    def __init__(self, session: ToolSession) -> None:
        self._session = session
        self._policy = session.policy

    def commands(self) -> dict[str, Callable[..., Any]]:
        """Return every guarded action by its ``FA_storage_*`` name."""
        return {
            EXISTS: self.exists,
            STAT: self.stat,
            LIST: self.list_dir,
            CHECKSUM: self.checksum,
            VERIFY: self.verify,
            READ_TEXT: self.read_text,
            SCHEMES: self.schemes,
            MKDIR: self.mkdir,
            WRITE_TEXT: self.write_text,
            COPY: self.copy,
            COPY_TREE: self.copy_tree,
            SYNC: self.sync,
            MOVE: self.move,
            DELETE: self.delete,
        }

    # ------------------------------------------------------------------ helpers

    def _file(self, uri: str) -> File:
        return self._session.file(uri)

    def _storage(self, uri: str) -> Storage:
        return self._session.storage(uri)

    def _replace(self, action: str, target: File, overwrite: bool | None) -> bool:
        """Return the ``overwrite`` to pass on: the caller's wish, as far as the policy goes."""
        if overwrite is None:
            return self._policy.allow_overwrite
        if overwrite and not self._policy.allow_overwrite and target.exists():
            self._policy.require_overwrite(action)
        return bool(overwrite) and self._policy.allow_overwrite

    # ------------------------------------------------------------------ reading

    def exists(self, uri: str) -> bool:
        """Return whether a file or a directory is at ``uri``."""
        return self._file(uri).exists()

    def stat(self, uri: str) -> dict[str, Any]:
        """Return the size, modification time and other metadata of ``uri``."""
        target = self._file(uri)
        return _described(target.stat(), target)

    def list_dir(self, uri: str, recursive: bool = False) -> list[dict[str, Any]]:
        """List the directory ``uri``; ``recursive`` adds every descendant."""
        directory = self._storage(uri)
        return [
            _described(info, directory.uri.joinpath(info.path))
            for info in directory.list_dir(recursive=bool(recursive))
        ]

    def checksum(self, uri: str, algorithm: str = DEFAULT_CHECKSUM_ALGORITHM) -> dict[str, str]:
        """Return ``{"algorithm": ..., "value": ...}`` for the content of ``uri``."""
        return self._file(uri).checksum(algorithm).to_dict()

    def verify(
        self,
        uri: str,
        expected: str | Mapping[str, Any],
        algorithm: str = DEFAULT_CHECKSUM_ALGORITHM,
        strict: bool = False,
    ) -> bool:
        """Return whether ``uri`` has the digest ``expected``; ``strict`` raises on a mismatch.

        ``expected`` is a hex digest, ``"<algorithm>:<hex>"``, or the mapping
        ``FA_storage_checksum`` returns.
        """
        target = self._file(uri)
        if target.verify(_expected_digest(expected), algorithm=algorithm):
            return True
        if strict:
            raise StorageChecksumException(f"{target} does not have the expected digest")
        return False

    def read_text(self, uri: str, encoding: str = _UTF8) -> str:
        """Return the content of ``uri`` as text, up to the policy's read limit."""
        source = self._file(uri)
        size = source.stat().size
        if size is None or size > self._policy.max_read_bytes:
            raise MCPPermissionException(
                f"{source} is larger than the {self._policy.max_read_bytes} bytes a task may "
                "read into its result (--max-read-bytes)",
                LIMIT_EXCEEDED,
            )
        return source.read_text(encoding)

    def schemes(self) -> list[str]:
        """Return the URI schemes a backend is registered or mounted for."""
        return self._session.guard.inner.schemes()

    # ------------------------------------------------------------------ writing

    def mkdir(self, uri: str, parents: bool = True, exist_ok: bool = True) -> bool:
        """Create the directory ``uri``."""
        self._policy.require_write(MKDIR)
        self._storage(uri).mkdir(parents=bool(parents), exist_ok=bool(exist_ok))
        return True

    def write_text(
        self, uri: str, text: str, overwrite: bool | None = None, encoding: str = _UTF8
    ) -> dict[str, Any]:
        """Store ``text`` as the content of ``uri``, up to the policy's write limit."""
        self._policy.require_write(WRITE_TEXT)
        payload = str(text).encode(encoding)
        if len(payload) > self._policy.max_write_bytes:
            raise MCPPermissionException(
                f"the text is {len(payload)} bytes and a task writes at most "
                f"{self._policy.max_write_bytes} (--max-write-bytes)",
                LIMIT_EXCEEDED,
            )
        target = self._file(uri)
        info = target.write(payload, overwrite=self._replace(WRITE_TEXT, target, overwrite))
        return _described(info, target)

    def copy(self, source: str, target: str, overwrite: bool | None = None) -> dict[str, Any]:
        """Copy the file ``source`` to ``target``, in the same backend or another one."""
        self._policy.require_write(COPY)
        origin, destination = self._file(source), self._file(target)
        copied = origin.copy_to(destination, overwrite=self._replace(COPY, destination, overwrite))
        return _described(copied.stat(), copied)

    def copy_tree(self, source: str, target: str, overwrite: bool | None = None) -> dict[str, Any]:
        """Copy every file below ``source`` to ``target``.

        A file the target already has is skipped unless overwriting is asked for
        and permitted.
        """
        self._policy.require_write(COPY_TREE)
        if overwrite:
            self._policy.require_overwrite(COPY_TREE)
        replace = self._policy.allow_overwrite if overwrite is None else bool(overwrite)
        return self._storage(source).copy_to(self._storage(target), overwrite=replace).to_dict()

    def sync(
        self,
        source: str,
        target: str,
        delete: bool = False,
        checksum: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Mirror ``source`` into ``target``.

        It replaces changed files, and ``delete`` removes what the source does not
        have, so it needs those permissions.
        """
        self._policy.require_overwrite(SYNC)
        if delete:
            self._policy.require_delete(SYNC)
        result = self._storage(source).sync_to(
            self._storage(target), delete=bool(delete), checksum=bool(checksum), dry_run=dry_run
        )
        return result.to_dict()

    # ------------------------------------------------------------------ deleting

    def move(self, source: str, target: str, overwrite: bool | None = None) -> dict[str, Any]:
        """Move the file ``source`` to ``target``; the source is deleted."""
        self._policy.require_delete(MOVE)
        origin, destination = self._file(source), self._file(target)
        moved = origin.move_to(destination, overwrite=self._replace(MOVE, destination, overwrite))
        return _described(moved.stat(), moved)

    def delete(self, uri: str, recursive: bool = False, missing_ok: bool = False) -> bool:
        """Remove the file or directory at ``uri``. An allowed root itself is never removed."""
        self._policy.require_delete(DELETE)
        target = self._storage(uri)
        if self._policy.is_root(target.uri):
            raise MCPLocationException(
                f"{target} is an allowed location itself and is not deleted", OUTSIDE_ROOT
            )
        target.delete("", recursive=bool(recursive), missing_ok=bool(missing_ok))
        return True
