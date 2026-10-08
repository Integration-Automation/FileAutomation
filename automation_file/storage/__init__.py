"""Universal storage layer: one contract, one URI syntax, any backend.

* :class:`File` and :class:`Storage` are the application API.
* :class:`StorageBackend` is the contract a backend implements. The built-in ones
  are :class:`LocalStorage`, :class:`MemoryStorage`, :class:`S3Storage` and
  :class:`AzureStorage`; :class:`ObjectStorage` is the shared base of the last two.
* :class:`StorageURI` / :func:`parse_storage_uri` define the address syntax, and
  :class:`StorageResolver` maps an address to a backend.
* :func:`register_storage_ops` adds the ``FA_storage_*`` actions to a registry.
"""

from __future__ import annotations

from automation_file.storage.actions import register_storage_ops
from automation_file.storage.azure_storage import AzureStorage
from automation_file.storage.backend import StorageBackend
from automation_file.storage.file import File
from automation_file.storage.local_storage import LocalStorage
from automation_file.storage.memory_storage import (
    MemoryStorage,
    clear_memory_stores,
    memory_store,
)
from automation_file.storage.object_storage import ObjectStorage
from automation_file.storage.resolver import (
    BackendFactory,
    StorageResolver,
    default_resolver,
    register_default_schemes,
)
from automation_file.storage.s3_storage import S3Storage
from automation_file.storage.storage import Storage
from automation_file.storage.tree import TreeResult, copy_tree, sync_tree
from automation_file.storage.types import Checksum, FileInfo, StorageCapabilities
from automation_file.storage.uri import (
    StorageURI,
    URILike,
    local_path_to_uri,
    normalize_path,
    parse_storage_uri,
)

__all__ = [
    "AzureStorage",
    "BackendFactory",
    "Checksum",
    "File",
    "FileInfo",
    "LocalStorage",
    "MemoryStorage",
    "ObjectStorage",
    "S3Storage",
    "Storage",
    "StorageBackend",
    "StorageCapabilities",
    "StorageResolver",
    "StorageURI",
    "TreeResult",
    "URILike",
    "clear_memory_stores",
    "copy_tree",
    "default_resolver",
    "local_path_to_uri",
    "memory_store",
    "normalize_path",
    "parse_storage_uri",
    "register_default_schemes",
    "register_storage_ops",
    "sync_tree",
]
