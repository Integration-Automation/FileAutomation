"""SMB / CIFS client built on ``smbprotocol``'s high-level ``smbclient`` API.

Scope mirrors :mod:`automation_file.remote.webdav.client` — existence check,
upload, download, delete, directory create, and shallow listing. The
underlying session is registered per ``(server, username)`` pair and torn
down when :meth:`SMBClient.close` runs. ``smbprotocol`` is imported lazily so
importing this module never touches the optional dependency.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

from automation_file.exceptions import SMBException

_DEFAULT_PORT = 445
_CHUNK_SIZE = 1 << 16


@dataclass(frozen=True)
class SMBEntry:
    """A single directory listing entry returned by :meth:`SMBClient.list_dir`."""

    name: str
    is_dir: bool
    size: int | None


def _import_smbclient() -> Any:
    try:
        import smbclient
    except ImportError as error:
        raise SMBException(
            "smbprotocol import failed — install `smbprotocol` to use the SMB backend"
        ) from error
    return smbclient


class SMBClient:
    """Minimal SMB client scoped to the operations used by this project."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        server: str,
        share: str,
        username: str | None = None,
        password: str | None = None,
        *,
        port: int = _DEFAULT_PORT,
        encrypt: bool = True,
        connection_timeout: float = 30.0,
    ) -> None:
        if not server or not share:
            raise SMBException("server and share are required")
        self._server = server
        self._share = share.strip("\\/")
        self._username = username
        self._password = password
        self._port = port
        self._encrypt = encrypt
        self._connection_timeout = connection_timeout
        self._registered = False

    def __enter__(self) -> SMBClient:
        self._ensure_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._registered:
            return
        smbclient = _import_smbclient()
        try:
            smbclient.delete_session(self._server, port=self._port)
        except Exception as error:
            raise SMBException(f"failed to close SMB session to {self._server}: {error}") from error
        finally:
            self._registered = False

    def _ensure_session(self) -> None:
        if self._registered:
            return
        smbclient = _import_smbclient()
        try:
            smbclient.register_session(
                self._server,
                username=self._username,
                password=self._password,
                port=self._port,
                encrypt=self._encrypt,
                connection_timeout=self._connection_timeout,
            )
        except Exception as error:
            raise SMBException(
                f"failed to register SMB session to {self._server}: {error}"
            ) from error
        self._registered = True

    def _unc(self, remote_path: str) -> str:
        cleaned = remote_path.replace("/", "\\").strip("\\")
        base = f"\\\\{self._server}\\{self._share}"
        if not cleaned:
            return base
        return f"{base}\\{cleaned}"

    def exists(self, remote_path: str) -> bool:
        """Return True if the remote path exists."""
        self._ensure_session()
        smbclient = _import_smbclient()
        try:
            smbclient.stat(self._unc(remote_path))
        except FileNotFoundError:
            return False
        except OSError as error:
            raise SMBException(f"stat failed for {remote_path}: {error}") from error
        return True

    def upload(self, local_path: str | os.PathLike[str], remote_path: str) -> None:
        """Copy the contents of ``local_path`` to ``remote_path`` on the share."""
        source = Path(local_path)
        if not source.is_file():
            raise SMBException(f"local source is not a file: {source}")
        self._ensure_session()
        smbclient = _import_smbclient()
        try:
            with (
                open(source, "rb") as src,
                smbclient.open_file(self._unc(remote_path), mode="wb") as dst,
            ):
                while True:
                    chunk = src.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    dst.write(chunk)
        except OSError as error:
            raise SMBException(f"upload failed for {remote_path}: {error}") from error

    def download(self, remote_path: str, local_path: str | os.PathLike[str]) -> None:
        """Stream the remote resource at ``remote_path`` to ``local_path``."""
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_session()
        smbclient = _import_smbclient()
        try:
            with (
                smbclient.open_file(self._unc(remote_path), mode="rb") as src,
                open(dest, "wb") as out,
            ):
                while True:
                    chunk = src.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
        except OSError as error:
            raise SMBException(f"download failed for {remote_path}: {error}") from error

    def delete(self, remote_path: str) -> None:
        """Remove the remote file at ``remote_path``."""
        self._ensure_session()
        smbclient = _import_smbclient()
        try:
            smbclient.remove(self._unc(remote_path))
        except OSError as error:
            raise SMBException(f"delete failed for {remote_path}: {error}") from error

    def mkdir(self, remote_path: str) -> None:
        """Create the remote directory at ``remote_path`` (parents must exist)."""
        self._ensure_session()
        smbclient = _import_smbclient()
        try:
            smbclient.makedirs(self._unc(remote_path), exist_ok=True)
        except OSError as error:
            raise SMBException(f"mkdir failed for {remote_path}: {error}") from error

    def rmdir(self, remote_path: str) -> None:
        """Remove the empty remote directory at ``remote_path``."""
        self._ensure_session()
        smbclient = _import_smbclient()
        try:
            smbclient.rmdir(self._unc(remote_path))
        except OSError as error:
            raise SMBException(f"rmdir failed for {remote_path}: {error}") from error

    def list_dir(self, remote_path: str) -> list[SMBEntry]:
        """Return a shallow listing of ``remote_path`` (non-recursive)."""
        self._ensure_session()
        smbclient = _import_smbclient()
        try:
            dir_entries = list(smbclient.scandir(self._unc(remote_path)))
        except OSError as error:
            raise SMBException(f"list_dir failed for {remote_path}: {error}") from error
        entries: list[SMBEntry] = []
        for item in dir_entries:
            is_dir = bool(item.is_dir())
            size: int | None
            if is_dir:
                size = None
            else:
                try:
                    size = int(item.stat().st_size)
                except OSError:
                    size = None
            entries.append(SMBEntry(name=item.name, is_dir=is_dir, size=size))
        return entries
