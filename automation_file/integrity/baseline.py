"""Baseline Manager: where the approved state of a tree is kept.

A baseline is one manifest file, addressed by a storage URI, so it can live in
another backend than the tree it describes. Keeping it elsewhere is the point:
whoever can change the tree should not be able to change what it is compared
with.

``save`` writes the manifest to a sibling temporary file and moves it over the
baseline, so a reader never sees a half-written document. The move is a rename
where the backend has one (the local filesystem); elsewhere it is one whole
write of the finished file.
"""

from __future__ import annotations

import uuid

from automation_file.exceptions import (
    StorageException,
    StorageNotFoundException,
    StoragePathTypeException,
)
from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.manifest import dump_manifest, load_manifest
from automation_file.integrity.snapshot import Snapshot
from automation_file.logging_config import file_automation_logger
from automation_file.storage.file import File
from automation_file.storage.resolver import StorageResolver
from automation_file.storage.uri import StorageURI, URILike, parse_storage_uri

_TEMPORARY_SUFFIX = ".tmp"


def _temporary_prefix(name: str) -> str:
    return f".{name}."


def is_baseline_path(candidate: str, baseline: str) -> bool:
    """Say whether ``candidate`` is the baseline file ``baseline`` or a temporary sibling of it.

    Both are paths inside the same tree. A monitor uses it to leave its own
    baseline out of the snapshots when the baseline is kept inside the target.
    """
    if candidate == baseline:
        return True
    directory, _, name = baseline.rpartition("/")
    parent, _, leaf = candidate.rpartition("/")
    return (
        parent == directory
        and leaf.startswith(_temporary_prefix(name))
        and leaf.endswith(_TEMPORARY_SUFFIX)
    )


class BaselineManager:
    """Reads and writes the baseline manifest at one storage URI."""

    def __init__(self, location: URILike, *, resolver: StorageResolver | None = None) -> None:
        self._uri = parse_storage_uri(location)
        if not self._uri.name:
            raise IntegrityException(f"a baseline must be a file, not the storage root {self._uri}")
        self._resolver = resolver
        self._file = File(self._uri, resolver=resolver)

    @property
    def uri(self) -> StorageURI:
        return self._uri

    def exists(self) -> bool:
        """Return whether a baseline file is stored."""
        return self._file.is_file()

    def load(self) -> Snapshot:
        """Return the stored baseline; the legacy manifest format is converted on the way."""
        try:
            data = self._file.read()
        except StorageNotFoundException as error:
            raise IntegrityException(
                f"no baseline at {self._uri}; create one with create_baseline()"
            ) from error
        except StoragePathTypeException as error:
            raise IntegrityException(f"baseline {self._uri} is a directory") from error
        return load_manifest(data, origin=f"baseline {self._uri}")

    def save(self, snapshot: Snapshot) -> None:
        """Store ``snapshot`` as the baseline, replacing the previous one in one step."""
        temporary = File(
            self._uri.parent.joinpath(
                f"{_temporary_prefix(self._uri.name)}{uuid.uuid4().hex}{_TEMPORARY_SUFFIX}"
            ),
            resolver=self._resolver,
        )
        try:
            temporary.write(dump_manifest(snapshot))
            temporary.move_to(self._file)
        finally:
            _discard(temporary)
        file_automation_logger.info(
            "integrity: baseline %s written (%d files, %s)",
            self._uri,
            len(snapshot),
            snapshot.algorithm,
        )


def _discard(temporary: File) -> None:
    """Remove what a failed ``save`` left behind; after a successful one nothing is there."""
    try:
        temporary.delete(missing_ok=True)
    except StorageException as error:
        file_automation_logger.warning(
            "integrity: could not remove the temporary baseline %s: %r", temporary, error
        )
