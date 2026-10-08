"""Value types shared by every storage backend.

``FileInfo`` is what ``stat`` and ``list`` return, ``Checksum`` what ``checksum``
returns, and ``StorageCapabilities`` says which optional ``FileInfo`` fields and
which directory semantics a backend provides. All three are frozen and turn into
JSON-friendly dictionaries with ``to_dict`` so action results can cross the TCP,
HTTP and MCP transports unchanged.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

_CHECKSUM_SEPARATOR = ":"


@dataclass(frozen=True)
class Checksum:
    """A digest and the algorithm that produced it, both lower-case."""

    algorithm: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "algorithm", self.algorithm.strip().lower())
        object.__setattr__(self, "value", self.value.strip().lower())

    @classmethod
    def parse(cls, text: str) -> Checksum:
        """Build a checksum from ``"<algorithm>:<hex digest>"``."""
        algorithm, separator, value = text.partition(_CHECKSUM_SEPARATOR)
        if not separator or not algorithm.strip() or not value.strip():
            raise ValueError(f"checksum must look like 'sha256:<hex digest>', got {text!r}")
        return cls(algorithm, value)

    def matches(self, expected: str | Checksum) -> bool:
        """Compare in constant time against a digest, ``"algorithm:digest"`` or a ``Checksum``.

        A different algorithm never matches. A bare digest is compared as is.
        """
        if isinstance(expected, str) and _CHECKSUM_SEPARATOR in expected:
            expected = Checksum.parse(expected)
        if isinstance(expected, Checksum):
            if expected.algorithm != self.algorithm:
                return False
            expected = expected.value
        return hmac.compare_digest(
            self.value.encode("utf-8"), expected.strip().lower().encode("utf-8")
        )

    def to_dict(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "value": self.value}

    def __str__(self) -> str:
        return f"{self.algorithm}{_CHECKSUM_SEPARATOR}{self.value}"


@dataclass(frozen=True)
class FileInfo:
    """One file or directory as a backend reports it.

    ``path`` uses ``/`` separators and has no leading slash. A backend reports it
    relative to its own root; :class:`~automation_file.storage.File` and
    :class:`~automation_file.storage.Storage` report it relative to the object that
    was asked. Fields a backend cannot provide are ``None`` (``metadata`` is empty);
    :class:`StorageCapabilities` says which ones to expect.
    """

    path: str
    is_dir: bool = False
    size: int | None = None
    modified_at: datetime | None = None
    etag: str | None = None
    version: str | None = None
    content_type: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict, hash=False)

    @property
    def name(self) -> str:
        """The last path segment (empty for a storage root)."""
        return self.path.rsplit("/", 1)[-1]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping; ``modified_at`` becomes ISO 8601."""
        return {
            "path": self.path,
            "name": self.name,
            "is_dir": self.is_dir,
            "size": self.size,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "etag": self.etag,
            "version": self.version,
            "content_type": self.content_type,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class StorageCapabilities:
    """What a backend provides beyond the mandatory contract.

    ``directories`` is ``True`` when directories exist on their own (a filesystem)
    and ``False`` when they are only implied by the paths of the files under them
    (an object store): there ``mkdir`` creates nothing and an empty directory
    cannot exist. The other flags name the optional :class:`FileInfo` fields the
    backend fills in.
    """

    directories: bool = True
    modified_at: bool = True
    etag: bool = False
    version: bool = False
    content_type: bool = False
    metadata: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)
