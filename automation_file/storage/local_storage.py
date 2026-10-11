"""Local filesystem backend.

``LocalStorage()`` spans the whole filesystem: its paths are absolute paths
without the leading slash (``data/report.csv``, or ``C:/data/report.csv`` on
Windows), which is what ``local:///data/report.csv`` resolves to.

``LocalStorage(root)`` is confined to one directory tree. Every path goes through
:func:`~automation_file.local.safe_paths.safe_join`, so a path that leaves the
root -- through a symlink or an absolute Windows path -- raises
:class:`~automation_file.exceptions.PathTraversalException`.

Symbolic links are followed when reading and writing. Deleting never follows
them: the link is removed and its target is left alone.
"""

# pylint: disable=protected-access  # a backend reads the private parts of another instance of its own kind

from __future__ import annotations

import contextlib
import errno
import os
import re
import shutil
import stat
import uuid
from collections.abc import Hashable, Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from automation_file.core.checksum import file_checksum
from automation_file.exceptions import (
    StorageException,
    StoragePermissionException,
    StorageTransientException,
)
from automation_file.local.safe_paths import safe_join
from automation_file.storage.backend import (
    StorageBackend,
    guess_content_type,
    join_path,
    missing_error,
    not_empty_error,
)
from automation_file.storage.types import FileInfo, StorageCapabilities
from automation_file.storage.uri import LOCAL_SCHEME, StorageURI, local_path_to_uri, normalize_path

_WINDOWS = os.sep == "\\"
_DRIVE = re.compile(r"[A-Za-z]:")


@contextlib.contextmanager
def _os_errors(location: str) -> Iterator[None]:
    """Turn the ``OSError`` family into the storage layer's exceptions."""
    try:
        yield
    except FileNotFoundError as error:
        raise missing_error(location) from error
    except PermissionError as error:
        raise StoragePermissionException(f"access to {location} was denied") from error
    except (TimeoutError, ConnectionError, InterruptedError) as error:
        # A network filesystem mounted as a local path fails this way.
        raise StorageTransientException(f"{location}: {error}") from error
    except OSError as error:
        raise StorageException(f"{location}: {error}") from error


def _anchored(path: str) -> Path:
    """Return the absolute filesystem path a rootless storage path stands for."""
    if _WINDOWS:
        drive, _, rest = path.partition("/")
        if _DRIVE.fullmatch(drive):
            return Path(f"{drive}/{rest}")
    return Path(f"/{path}")


def _file_info(path: str, result: os.stat_result) -> FileInfo:
    is_dir = stat.S_ISDIR(result.st_mode)
    return FileInfo(
        path=path,
        is_dir=is_dir,
        size=None if is_dir else result.st_size,
        modified_at=datetime.fromtimestamp(result.st_mtime, tz=timezone.utc),
        content_type=None if is_dir else guess_content_type(path),
    )


def _stat_entry(entry: Path) -> os.stat_result:
    """Stat ``entry``, falling back to the link itself when its target is gone."""
    try:
        return entry.stat()
    except FileNotFoundError:
        return entry.lstat()


def _remove_link(link: Path) -> None:
    try:
        link.unlink()
    except (PermissionError, IsADirectoryError):
        # A Windows directory link is removed like a directory.
        os.rmdir(link)


def _replace_with_copy(source: Path, target: Path) -> None:
    """Copy ``source`` over ``target`` through a sibling file, so readers never see half of it."""
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
    try:
        shutil.copyfile(source, partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def _raise(error: OSError) -> None:
    raise error


class LocalStorage(StorageBackend):
    """The local filesystem, whole (``root=None``) or confined to ``root``."""

    scheme = LOCAL_SCHEME
    capabilities = StorageCapabilities(directories=True, modified_at=True, content_type=True)

    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self._root: Path | None = Path(root).resolve() if root is not None else None

    @property
    def root(self) -> Path | None:
        """The directory this backend is confined to, or ``None`` for the whole filesystem."""
        return self._root

    def local_path(self, path: str = "") -> Path:
        """Return the filesystem path of ``path``, checked against the root when there is one."""
        clean = self._normalize(path)
        if self._root is None:
            return _anchored(clean)
        return safe_join(self._root, clean) if clean else self._root

    def uri_for(self, path: str = "") -> str:
        clean = self._normalize(path)
        if self._root is None:
            return str(StorageURI(LOCAL_SCHEME, "", clean))
        return str(local_path_to_uri(self._root / clean))

    def __repr__(self) -> str:
        return "LocalStorage()" if self._root is None else f"LocalStorage({str(self._root)!r})"

    def _normalize(self, path: str) -> str:
        return normalize_path(path.replace("\\", "/") if _WINDOWS else path)

    def _entry_path(self, path: str) -> Path:
        """Like :meth:`local_path`, but the last segment is not resolved: a link stays a link."""
        parent, _, name = path.rpartition("/")
        return self.local_path(parent) / name if name else self.local_path(parent)

    def _identity(self, path: str) -> Hashable:
        # Resolved, so a rooted view, the rootless one and a link all name one file alike.
        return (LOCAL_SCHEME, os.path.normcase(os.path.realpath(self.local_path(path))))

    def _is_root(self, path: str) -> bool:
        if not path:
            return True
        target = self.local_path(path)
        return target == target.parent

    def _stat(self, path: str) -> FileInfo | None:
        with _os_errors(self.uri_for(path)):
            try:
                return _file_info(path, self.local_path(path).stat())
            except (FileNotFoundError, NotADirectoryError):
                return self._dangling_link(path)

    def _dangling_link(self, path: str) -> FileInfo | None:
        """Report a link whose target is gone as a file, so it can still be deleted."""
        try:
            entry = self._entry_path(path)
            if not entry.is_symlink():
                return None
            return _file_info(path, entry.lstat())
        except (FileNotFoundError, NotADirectoryError):
            return None

    def _list_dir(self, path: str) -> Iterable[FileInfo]:
        directory = self.local_path(path)
        with _os_errors(self.uri_for(path)):
            return [
                _file_info(join_path(path, entry.name), _stat_entry(entry))
                for entry in directory.iterdir()
            ]

    def _walk(self, path: str) -> Iterable[FileInfo]:
        top = self.local_path(path)
        found: list[FileInfo] = []
        with _os_errors(self.uri_for(path)):
            # os.walk lists linked directories but does not descend into them.
            for current, directories, files in os.walk(top, onerror=_raise):
                here = Path(current)
                relative = here.relative_to(top).as_posix()
                base = path if relative == "." else join_path(path, relative)
                found.extend(
                    _file_info(join_path(base, name), _stat_entry(here / name))
                    for name in (*directories, *files)
                )
        return found

    def _upload(self, source: Path, path: str) -> None:
        with _os_errors(self.uri_for(path)):
            _replace_with_copy(source, self.local_path(path))

    def _download(self, path: str, target: Path) -> None:
        with _os_errors(self.uri_for(path)):
            shutil.copyfile(self.local_path(path), target)

    def _delete_file(self, path: str) -> None:
        with _os_errors(self.uri_for(path)):
            self._entry_path(path).unlink()

    def _mkdir(self, path: str) -> None:
        with _os_errors(self.uri_for(path)):
            self.local_path(path).mkdir(parents=True, exist_ok=True)

    def _delete_directory(self, path: str, recursive: bool) -> None:
        entry = self._entry_path(path)
        with _os_errors(self.uri_for(path)):
            if entry.is_symlink():
                _remove_link(entry)
            elif recursive:
                shutil.rmtree(entry)
            elif any(entry.iterdir()):
                raise not_empty_error(self.uri_for(path))
            else:
                entry.rmdir()

    def _copy_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, LocalStorage):
            return False
        with _os_errors(self.uri_for(path)):
            _replace_with_copy(source.local_path(source_path), self.local_path(path))
        return True

    def _move_from(self, source: StorageBackend, source_path: str, path: str) -> bool:
        if not isinstance(source, LocalStorage):
            return False
        origin = source._entry_path(source_path)
        with _os_errors(self.uri_for(path)):
            try:
                os.replace(origin, self.local_path(path))
            except OSError as error:
                if error.errno == errno.EXDEV:
                    return False
                raise
        return True

    def _checksum(self, path: str, algorithm: str) -> str:
        with _os_errors(self.uri_for(path)):
            return file_checksum(self.local_path(path), algorithm)

    def _open_read(self, path: str) -> BinaryIO:
        with _os_errors(self.uri_for(path)):
            return self.local_path(path).open("rb")

    def _read_bytes(self, path: str) -> bytes:
        with _os_errors(self.uri_for(path)):
            return self.local_path(path).read_bytes()
