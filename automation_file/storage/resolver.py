"""Resolve a storage URI to the backend that serves it.

A :class:`StorageResolver` answers "which backend, and which path inside it?" in
two steps:

1. **Mounts.** ``mount("sftp://nas/archive", backend)`` binds one backend
   instance to a URI. A URI at or below a mount goes to that backend, with the
   mount's own path stripped. The longest matching mount wins.
2. **Scheme factories.** ``register_scheme("local", factory)`` handles every URI
   of a scheme no mount claimed. The factory receives the parsed URI and returns
   ``(backend, path)``.

The default factories serve ``local``, ``memory``, ``s3``, ``azure``, ``gdrive``,
``dropbox``, ``onedrive``, ``sftp``, ``ftp`` and ``ftps`` through the shared clients.
WebDAV, SMB and fsspec backends need a client or a filesystem of their own, so they
are mounted.

:data:`default_resolver` is the process-wide instance behind
:class:`~automation_file.storage.File` and :class:`~automation_file.storage.Storage`.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

from automation_file.exceptions import StorageURIException
from automation_file.storage.azure_storage import AZURE_SCHEME, AzureStorage
from automation_file.storage.backend import StorageBackend
from automation_file.storage.dropbox_storage import DROPBOX_SCHEME, dropbox_factory
from automation_file.storage.ftp_storage import FTP_SCHEME, FTPS_SCHEME, ftp_factory
from automation_file.storage.gdrive_storage import GDRIVE_SCHEME, gdrive_factory
from automation_file.storage.local_storage import LocalStorage
from automation_file.storage.memory_storage import MEMORY_SCHEME, memory_store
from automation_file.storage.onedrive_storage import ONEDRIVE_SCHEME, onedrive_factory
from automation_file.storage.s3_storage import S3_SCHEME, S3Storage
from automation_file.storage.sftp_storage import SFTP_SCHEME, sftp_factory
from automation_file.storage.types import StorageCapabilities
from automation_file.storage.uri import (
    LOCAL_SCHEME,
    StorageURI,
    URILike,
    canonical_scheme,
    parse_storage_uri,
)

BackendFactory = Callable[[StorageURI], tuple[StorageBackend, str]]
_MountKey = tuple[str, str, str]


def _mount_key(uri: StorageURI) -> _MountKey:
    return uri.scheme, uri.authority.casefold(), uri.path


def _below(path: str, prefix: str) -> str | None:
    """Return ``path`` relative to ``prefix``, or ``None`` when it is not at or below it."""
    if not prefix:
        return path
    if path == prefix:
        return ""
    if path.startswith(f"{prefix}/"):
        return path[len(prefix) + 1 :]
    return None


class StorageResolver:
    """A thread-safe table of mounts and scheme factories."""

    def __init__(self, *, defaults: bool = True) -> None:
        self._lock = threading.RLock()
        self._factories: dict[str, BackendFactory] = {}
        self._mounts: dict[_MountKey, StorageBackend] = {}
        if defaults:
            register_default_schemes(self)

    def register_scheme(self, scheme: str, factory: BackendFactory) -> None:
        """Serve every unmounted URI of ``scheme`` through ``factory``."""
        if not callable(factory):
            raise TypeError(f"storage factory for {scheme!r} is not callable")
        with self._lock:
            self._factories[canonical_scheme(scheme)] = factory

    def unregister_scheme(self, scheme: str) -> bool:
        """Drop the factory of ``scheme``; return whether there was one."""
        with self._lock:
            return self._factories.pop(canonical_scheme(scheme), None) is not None

    def mount(self, uri: URILike, backend: StorageBackend) -> None:
        """Serve ``uri`` and everything below it from ``backend``."""
        if not isinstance(backend, StorageBackend):
            raise TypeError(f"cannot mount {type(backend).__name__}: not a StorageBackend")
        with self._lock:
            self._mounts[_mount_key(parse_storage_uri(uri))] = backend

    def unmount(self, uri: URILike) -> bool:
        """Remove the mount at exactly ``uri``; return whether there was one."""
        with self._lock:
            return self._mounts.pop(_mount_key(parse_storage_uri(uri)), None) is not None

    def schemes(self) -> list[str]:
        """Return every scheme that has a factory or a mount, sorted."""
        with self._lock:
            return sorted({*self._factories, *(key[0] for key in self._mounts)})

    def resolve(self, uri: URILike) -> tuple[StorageBackend, str]:
        """Return the backend that serves ``uri`` and the path inside that backend."""
        parsed = parse_storage_uri(uri)
        with self._lock:
            mounted = self._find_mount(parsed)
            factory = self._factories.get(parsed.scheme)
        if mounted is not None:
            return mounted
        if factory is None:
            known = ", ".join(self.schemes()) or "none"
            raise StorageURIException(
                f"no storage backend serves {str(parsed)!r}: scheme {parsed.scheme!r} has no "
                f"factory and no mount covers the URI (known schemes: {known})"
            )
        return factory(parsed)

    def capabilities(self, uri: URILike) -> StorageCapabilities:
        """Return the capabilities of the backend that serves ``uri``."""
        return self.resolve(uri)[0].capabilities

    def _find_mount(self, uri: StorageURI) -> tuple[StorageBackend, str] | None:
        authority = uri.authority.casefold()
        best: tuple[int, StorageBackend, str] | None = None
        for (scheme, mounted_authority, prefix), backend in self._mounts.items():
            if scheme != uri.scheme or mounted_authority != authority:
                continue
            relative = _below(uri.path, prefix)
            if relative is not None and (best is None or len(prefix) > best[0]):
                best = (len(prefix), backend, relative)
        return None if best is None else (best[1], best[2])


_whole_filesystem = LocalStorage()


def _local_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    if not uri.authority:
        return _whole_filesystem, uri.path
    share, _, rest = uri.path.partition("/")
    if os.sep != "\\" or not share:
        raise StorageURIException(
            f"{str(uri)!r} names the host {uri.authority!r}; a local file takes an empty "
            f"authority, as in 'local:///{uri.authority}/{uri.path}'. Only Windows reads "
            "'local://server/share/path' as a UNC path"
        )
    return LocalStorage(f"//{uri.authority}/{share}/"), rest


def _memory_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    return memory_store(uri.authority), uri.path


def _container_of(uri: StorageURI, kind: str) -> str:
    if not uri.authority:
        raise StorageURIException(
            f"{str(uri)!r} names no {kind}; write '{uri.scheme}://<{kind}>/<path>'"
        )
    return uri.authority


def _s3_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    return S3Storage(_container_of(uri, "bucket")), uri.path


def _azure_factory(uri: StorageURI) -> tuple[StorageBackend, str]:
    return AzureStorage(_container_of(uri, "container")), uri.path


def register_default_schemes(resolver: StorageResolver) -> None:
    """Register the factory of every built-in backend on ``resolver``."""
    resolver.register_scheme(LOCAL_SCHEME, _local_factory)
    resolver.register_scheme(MEMORY_SCHEME, _memory_factory)
    resolver.register_scheme(S3_SCHEME, _s3_factory)
    resolver.register_scheme(AZURE_SCHEME, _azure_factory)
    resolver.register_scheme(GDRIVE_SCHEME, gdrive_factory)
    resolver.register_scheme(DROPBOX_SCHEME, dropbox_factory)
    resolver.register_scheme(ONEDRIVE_SCHEME, onedrive_factory)
    resolver.register_scheme(SFTP_SCHEME, sftp_factory)
    resolver.register_scheme(FTP_SCHEME, ftp_factory)
    resolver.register_scheme(FTPS_SCHEME, ftp_factory)


default_resolver = StorageResolver()
