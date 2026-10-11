"""Manifest: the JSON document a baseline is stored as.

Schema version 2::

    {
      "schema_version": 2,
      "created_at": "2026-10-08T10:15:30.123456+00:00",
      "root": "s3://reports/2026",
      "backend": "s3",
      "algorithm": "sha256",
      "entries": [
        {"path": "q1.csv", "size": 1024, "modified_at": "2026-10-01T08:00:00+00:00",
         "checksum": "9f86d0...", "algorithm": "sha256", "content_type": "text/csv",
         "backend": "s3", "version": null, "etag": "5d41402a...", "mode": null}
      ]
    }

The format written by :func:`automation_file.core.manifest.write_manifest` (no
``schema_version`` key, a ``files`` mapping with ``size`` and ``checksum``) is
read as well and converted. Any other version is refused, so a newer document
is never half-understood.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from automation_file.exceptions import StorageURIException
from automation_file.integrity.errors import IntegrityException
from automation_file.integrity.hashing import DEFAULT_ALGORITHM
from automation_file.integrity.snapshot import Snapshot, SnapshotEntry, parse_timestamp
from automation_file.storage.uri import LOCAL_SCHEME, local_path_to_uri

MANIFEST_SCHEMA_VERSION = 2
LEGACY_MANIFEST_VERSION = 1
_SCHEMA_KEY = "schema_version"
_LEGACY_FILES_KEY = "files"
_LEGACY_VERSION_KEY = "version"
_ENCODING = "utf-8"


def to_manifest(snapshot: Snapshot) -> dict[str, Any]:
    """Return the schema-version-2 document of ``snapshot``."""
    return {_SCHEMA_KEY: MANIFEST_SCHEMA_VERSION, **snapshot.to_dict()}


def from_manifest(document: Any, *, origin: str = "manifest") -> Snapshot:
    """Return the snapshot a manifest document describes.

    ``origin`` names the document in error messages. Raises
    :class:`IntegrityException` for a document that is not a manifest or whose
    version this release does not read.
    """
    if not isinstance(document, Mapping):
        raise IntegrityException(f"{origin} is not a manifest: expected a JSON object")
    if _SCHEMA_KEY not in document:
        return _from_legacy(document, origin)
    version = document[_SCHEMA_KEY]
    if isinstance(version, bool) or version != MANIFEST_SCHEMA_VERSION:
        raise IntegrityException(
            f"{origin} has manifest schema version {version!r}; this release reads version "
            f"{MANIFEST_SCHEMA_VERSION} and the legacy format without a version"
        )
    try:
        return Snapshot.from_dict(document)
    except IntegrityException as error:
        raise IntegrityException(f"{origin} is not a valid manifest: {error}") from error


def dump_manifest(snapshot: Snapshot) -> bytes:
    """Return ``snapshot`` as an encoded schema-version-2 JSON document."""
    return json.dumps(to_manifest(snapshot), indent=2, ensure_ascii=False).encode(_ENCODING)


def load_manifest(data: bytes | str, *, origin: str = "manifest") -> Snapshot:
    """Return the snapshot held by the JSON text ``data`` (version 2 or legacy)."""
    try:
        text = data.decode(_ENCODING) if isinstance(data, bytes) else data
        document = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntegrityException(f"{origin} is not readable JSON: {error}") from error
    return from_manifest(document, origin=origin)


def _legacy_root(value: object) -> str:
    """Return the storage URI of the directory a legacy manifest was written for."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return str(local_path_to_uri(value))
    except StorageURIException:
        return ""


def _legacy_entry(path: object, meta: object, algorithm: str) -> SnapshotEntry:
    details = meta if isinstance(meta, Mapping) else {}
    size = details.get("size")
    checksum = details.get("checksum")
    return SnapshotEntry.from_dict(
        {
            "path": path,
            "size": size if isinstance(size, int) and not isinstance(size, bool) else None,
            "checksum": checksum if isinstance(checksum, str) else "",
        },
        algorithm=algorithm,
        backend=LOCAL_SCHEME,
    )


def _from_legacy(document: Mapping[str, Any], origin: str) -> Snapshot:
    files = document.get(_LEGACY_FILES_KEY)
    if not isinstance(files, Mapping):
        raise IntegrityException(
            f"{origin} is not a manifest: it has neither {_SCHEMA_KEY!r} nor a legacy "
            f"{_LEGACY_FILES_KEY!r} mapping"
        )
    version = document.get(_LEGACY_VERSION_KEY, LEGACY_MANIFEST_VERSION)
    if isinstance(version, bool) or version != LEGACY_MANIFEST_VERSION:
        raise IntegrityException(
            f"{origin} is a legacy manifest of version {version!r}; only version "
            f"{LEGACY_MANIFEST_VERSION} is known"
        )
    algorithm = document.get("algorithm")
    name = algorithm if isinstance(algorithm, str) and algorithm else DEFAULT_ALGORITHM
    created_at = parse_timestamp(document.get("created_at"), f"{origin} 'created_at'")
    try:
        return Snapshot(
            root=_legacy_root(document.get("root")),
            backend=LOCAL_SCHEME,
            algorithm=name,
            created_at=created_at or datetime.now(timezone.utc),
            entries=tuple(_legacy_entry(path, meta, name) for path, meta in files.items()),
        )
    except IntegrityException as error:
        raise IntegrityException(f"{origin} is not a valid legacy manifest: {error}") from error
