"""Universal storage layer: one contract, one URI syntax, any backend.

* :class:`File` and :class:`Storage` are the application API.
* :class:`StorageBackend` is the contract a backend implements;
  :class:`LocalStorage` and :class:`MemoryStorage` are the built-in ones.
* :class:`StorageURI` / :func:`parse_storage_uri` define the address syntax, and
  :class:`StorageResolver` maps an address to a backend.
"""

from __future__ import annotations

from automation_file.storage.backend import StorageBackend
from automation_file.storage.file import File
from automation_file.storage.local_storage import LocalStorage
from automation_file.storage.memory_storage import (
    MemoryStorage,
    clear_memory_stores,
    memory_store,
)
from automation_file.storage.resolver import (
    BackendFactory,
    StorageResolver,
    default_resolver,
    register_default_schemes,
)
from automation_file.storage.storage import Storage
from automation_file.storage.types import Checksum, FileInfo, StorageCapabilities
from automation_file.storage.uri import (
    StorageURI,
    URILike,
    local_path_to_uri,
    normalize_path,
    parse_storage_uri,
)

__all__ = [
    "BackendFactory",
    "Checksum",
    "File",
    "FileInfo",
    "LocalStorage",
    "MemoryStorage",
    "Storage",
    "StorageBackend",
    "StorageCapabilities",
    "StorageResolver",
    "StorageURI",
    "URILike",
    "clear_memory_stores",
    "default_resolver",
    "local_path_to_uri",
    "memory_store",
    "normalize_path",
    "parse_storage_uri",
    "register_default_schemes",
]
