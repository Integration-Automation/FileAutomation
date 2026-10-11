"""The Storage service: which backends are there, and whether each one can be used.

.. code-block:: python

    from automation_file.app import app_services

    storage = app_services().storage
    for backend in storage.backends():
        print(backend.name, backend.usable, backend.detail)
    storage.mount_local("sandbox://jobs", "/srv/jobs")

A backend is *usable* when its client is ready: the local and in-memory
backends always are, a cloud backend once its shared client has been
initialised. When the package its extra installs is missing, the status says
so and carries the ``pip install`` command. Nothing here opens a connection.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from automation_file.app.errors import AppException
from automation_file.core.optional import install_hint
from automation_file.exceptions import FileAutomationException
from automation_file.storage import (
    LocalStorage,
    StorageBackend,
    StorageResolver,
    StorageURI,
    default_resolver,
    parse_storage_uri,
)

KIND_SCHEME = "scheme"
KIND_MOUNT = "mount"
KIND_CLIENT = "client"

_READY = "ready"
_MOUNTED = "mounted"
_NO_FACTORY_INFO = "registered by the application"


@dataclass(frozen=True)
class _Client:
    """One shared client singleton: where it lives and how to ask whether it is ready."""

    label: str
    module: str
    attribute: str
    probe: str
    extra: str | None
    sdk: str | None
    init_hint: str


_CLIENTS: dict[str, _Client] = {
    "s3": _Client(
        "Amazon S3",
        "automation_file.remote.s3.client",
        "s3_instance",
        "require_client",
        "s3",
        "boto3",
        "call s3_instance.later_init() or FA_s3_later_init",
    ),
    "azure": _Client(
        "Azure Blob",
        "automation_file.remote.azure_blob.client",
        "azure_blob_instance",
        "require_service",
        "azure",
        "azure.storage.blob",
        "call azure_blob_instance.later_init() or FA_azure_blob_later_init",
    ),
    "gdrive": _Client(
        "Google Drive",
        "automation_file.remote.google_drive.client",
        "driver_instance",
        "require_service",
        "gdrive",
        "googleapiclient",
        "call driver_instance.later_init(token_path, credentials_path)",
    ),
    "dropbox": _Client(
        "Dropbox",
        "automation_file.remote.dropbox_api.client",
        "dropbox_instance",
        "require_client",
        "dropbox",
        "dropbox",
        "call dropbox_instance.later_init(token) or FA_dropbox_later_init",
    ),
    "onedrive": _Client(
        "OneDrive",
        "automation_file.remote.onedrive.client",
        "onedrive_instance",
        "require_session",
        "onedrive",
        "msal",
        "call onedrive_instance.later_init(access_token) or device_code_login()",
    ),
    "sftp": _Client(
        "SFTP",
        "automation_file.remote.sftp.client",
        "sftp_instance",
        "require_sftp",
        "sftp",
        "paramiko",
        "call sftp_instance.later_init(...) or FA_sftp_later_init",
    ),
    "ftp": _Client(
        "FTP / FTPS",
        "automation_file.remote.ftp.client",
        "ftp_instance",
        "require_ftp",
        "ftp",
        None,
        "call ftp_instance.later_init(...) or FA_ftp_later_init",
    ),
    "box": _Client(
        "Box",
        "automation_file.remote.box.client",
        "box_instance",
        "require_client",
        "box",
        "box_sdk_gen",
        "call box_instance.later_init(...) or FA_box_later_init",
    ),
}
#: Storage scheme -> the client that serves it. ``box`` has actions but no storage scheme.
_SCHEME_CLIENTS = {
    "s3": "s3",
    "azure": "azure",
    "gdrive": "gdrive",
    "dropbox": "dropbox",
    "onedrive": "onedrive",
    "sftp": "sftp",
    "ftp": "ftp",
    "ftps": "ftp",
}
_ALWAYS_READY = {"local": "Local filesystem", "memory": "In-memory store"}
_CLIENTS_WITHOUT_SCHEME = tuple(
    name for name in _CLIENTS if name not in frozenset(_SCHEME_CLIENTS.values())
)


@dataclass(frozen=True)
class BackendStatus:
    """Whether one backend can be used, and what is missing when it cannot.

    ``kind`` is ``"scheme"`` for a URI scheme with a factory, ``"mount"`` for a
    backend mounted at a URI and ``"client"`` for a shared client that has
    ``FA_*`` actions but no storage scheme. ``install_hint`` is set only when
    the package of the backend's extra is not installed.
    """

    name: str
    kind: str
    label: str
    backend: str = ""
    extra: str | None = None
    installed: bool = True
    ready: bool = True
    usable: bool = True
    detail: str = _READY
    install_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the status."""
        return asdict(self)


@dataclass(frozen=True)
class MountInfo:
    """One mount of the resolver: the URI it serves and the backend behind it."""

    uri: str
    scheme: str
    backend: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serialisable mapping of the mount."""
        return asdict(self)


def is_installed(module: str | None) -> bool:
    """Return whether ``module`` can be imported, without importing it."""
    if module is None:
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        # A missing parent package, or a module that is half-imported.
        return False


def _client_ready(client: _Client) -> bool:
    """Ask the shared client whether it has been initialised. Never opens a connection."""
    try:
        # nosemgrep  # the module name comes from a fixed table of this package's clients
        instance = getattr(importlib.import_module(client.module), client.attribute)
        probe: Callable[[], Any] = getattr(instance, client.probe)
        probe()
    except (FileAutomationException, RuntimeError, ImportError, AttributeError):
        return False
    return True


def _client_status(name: str, kind: str, client: _Client) -> BackendStatus:
    installed = is_installed(client.sdk)
    ready = _client_ready(client)
    hint = None if installed or client.extra is None else install_hint(client.extra)
    if ready:
        detail = _READY
    elif hint is not None:
        detail = f"{client.sdk} is not installed: {hint}"
    else:
        detail = f"not initialised: {client.init_hint}"
    return BackendStatus(
        name=name,
        kind=kind,
        label=client.label,
        extra=client.extra,
        installed=installed,
        ready=ready,
        usable=ready,
        detail=detail,
        install_hint=hint,
    )


def _mount_uri(key: tuple[str, str, str]) -> str:
    scheme, authority, path = key
    return str(StorageURI(scheme, authority, path))


class StorageService:
    """Schemes, mounts and backend status of one :class:`StorageResolver`."""

    def __init__(self, resolver: StorageResolver | None = None) -> None:
        self._resolver = default_resolver if resolver is None else resolver

    @property
    def resolver(self) -> StorageResolver:
        """The resolver this service reads and changes."""
        return self._resolver

    def schemes(self) -> list[str]:
        """Return every scheme that has a factory or a mount, sorted."""
        return self._resolver.schemes()

    def mounts(self) -> list[MountInfo]:
        """Return the mounts, sorted by URI."""
        return sorted(
            (
                MountInfo(uri=_mount_uri(key), scheme=key[0], backend=type(backend).__name__)
                for key, backend in self._mount_table().items()
            ),
            key=lambda mount: mount.uri,
        )

    def backends(self) -> list[BackendStatus]:
        """Return one status per scheme, per mount and per shared client without a scheme.

        A scheme that exists only because something is mounted under it is
        listed through its mounts.
        """
        mounted = self.mounts()
        factories = self._factory_schemes()
        statuses = [self._scheme_status(scheme) for scheme in self.schemes() if scheme in factories]
        statuses.extend(
            BackendStatus(
                name=mount.uri,
                kind=KIND_MOUNT,
                label=f"Mount of {mount.backend}",
                backend=mount.backend,
                detail=_MOUNTED,
            )
            for mount in mounted
        )
        statuses.extend(
            _client_status(name, KIND_CLIENT, _CLIENTS[name]) for name in _CLIENTS_WITHOUT_SCHEME
        )
        return statuses

    def capabilities(self, uri: str) -> dict[str, bool]:
        """Return what the backend serving ``uri`` provides beyond the mandatory contract."""
        return self._resolver.capabilities(uri).to_dict()

    def mount_local(self, uri: str, root: str | os.PathLike[str]) -> MountInfo:
        """Serve ``uri`` from the local directory ``root``, confined to that directory.

        This is how paths that come from outside the process get a sandbox:
        ``mount_local("sandbox://jobs", "/srv/jobs")``. The directory must exist.
        """
        if not os.path.isdir(root):
            raise AppException(f"cannot mount {os.fspath(root)!r}: it is not a directory")
        parsed = parse_storage_uri(uri)
        self._resolver.mount(parsed, LocalStorage(root))
        return MountInfo(uri=str(parsed), scheme=parsed.scheme, backend=LocalStorage.__name__)

    def mount(self, uri: str, backend: StorageBackend) -> MountInfo:
        """Serve ``uri`` and everything below it from ``backend``."""
        parsed = parse_storage_uri(uri)
        try:
            self._resolver.mount(parsed, backend)
        except TypeError as error:
            raise AppException(str(error)) from error
        return MountInfo(uri=str(parsed), scheme=parsed.scheme, backend=type(backend).__name__)

    def unmount(self, uri: str) -> bool:
        """Remove the mount at exactly ``uri``; return whether there was one."""
        return self._resolver.unmount(uri)

    def _table(self, name: str) -> dict[Any, Any] | None:
        # StorageResolver lists its schemes but neither its mounts nor which schemes have a
        # factory, so its two tables are read here, in one place, under its own lock.
        table = getattr(self._resolver, name, None)
        lock = getattr(self._resolver, "_lock", None)
        if not isinstance(table, dict) or lock is None:
            return None
        with lock:
            return dict(table)

    def _mount_table(self) -> dict[tuple[str, str, str], StorageBackend]:
        return self._table("_mounts") or {}

    def _factory_schemes(self) -> frozenset[str]:
        """Return the schemes served by a factory; every scheme when that cannot be told."""
        factories = self._table("_factories")
        return frozenset(self.schemes() if factories is None else factories)

    @staticmethod
    def _scheme_status(scheme: str) -> BackendStatus:
        if scheme in _ALWAYS_READY:
            return BackendStatus(name=scheme, kind=KIND_SCHEME, label=_ALWAYS_READY[scheme])
        client = _CLIENTS.get(_SCHEME_CLIENTS.get(scheme, ""))
        if client is None:
            return BackendStatus(
                name=scheme, kind=KIND_SCHEME, label=scheme, detail=_NO_FACTORY_INFO
            )
        return _client_status(scheme, KIND_SCHEME, client)
