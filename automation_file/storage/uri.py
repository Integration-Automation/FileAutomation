"""Storage URIs: ``<scheme>://<authority>/<path>``.

One syntax addresses every backend::

    local:///data/report.csv          s3://bucket/report.csv
    local:///C:/data/report.csv       azure://container/report.csv
    sftp://server/data/report.csv     dropbox:///reports/report.csv

* **scheme** picks the backend. It is lower-cased; ``file`` is an alias of ``local``
  and ``az`` of ``azure``.
* **authority** is what the backend needs to find its root: a bucket, a container,
  a host. It is kept as written. Credentials never belong in it, so ``user@host``
  is rejected.
* **path** is taken literally. Nothing is percent-decoded and ``?`` / ``#`` are
  ordinary characters, so ``s3://bucket/Q1 #3?.csv`` names exactly that key. Empty
  and ``.`` segments are dropped; a ``..`` segment is an error.

Text without ``://`` is a local filesystem path and is made absolute, so
``reports/a.csv`` and ``C:\\data\\a.csv`` work as they are. Text that starts with
something scheme-like but has no ``//`` (``sftp:/data/a.csv``) could mean either,
so it is rejected with the two unambiguous spellings.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TypeAlias

from automation_file.exceptions import StorageURIException

LOCAL_SCHEME = "local"
_URI_SEPARATOR = "://"
_SCHEME_ALIASES = {"file": LOCAL_SCHEME, "az": "azure"}
_SCHEME_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*")
# Two or more characters before the colon: one character is a Windows drive letter.
_SCHEME_LIKE_PREFIX = re.compile(r"([A-Za-z][A-Za-z0-9+.-]+):")
_AUTHORITY_FORBIDDEN = re.compile(r"[\s/\\]")


def normalize_path(path: str) -> str:
    """Return ``path`` with ``/`` separators and no empty, ``.`` or leading segments.

    Raises :class:`StorageURIException` for a ``..`` segment or a NUL character, so
    a normalised path can never climb out of the root it is joined to.
    """
    if "\x00" in path:
        raise StorageURIException("storage paths cannot contain a NUL character")
    segments: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            raise StorageURIException(f"storage paths cannot contain '..' segments: {path!r}")
        segments.append(segment)
    return "/".join(segments)


def canonical_scheme(scheme: str) -> str:
    """Lower-case ``scheme``, resolve its alias and check its syntax."""
    lowered = scheme.strip().lower()
    if not _SCHEME_PATTERN.fullmatch(lowered):
        raise StorageURIException(f"invalid storage URI scheme: {scheme!r}")
    return _SCHEME_ALIASES.get(lowered, lowered)


def _checked_authority(authority: str, scheme: str) -> str:
    cleaned = authority.strip()
    if "@" in cleaned:
        raise StorageURIException(
            f"{scheme} URI authority {cleaned.rsplit('@', 1)[-1]!r} carries user information; "
            "credentials do not belong in a storage URI, initialise the backend with them instead"
        )
    if _AUTHORITY_FORBIDDEN.search(cleaned):
        raise StorageURIException(f"invalid {scheme} URI authority: {authority!r}")
    return cleaned


@dataclass(frozen=True)
class StorageURI:
    """A parsed storage URI. Construction validates and normalises all three parts."""

    scheme: str
    authority: str = ""
    path: str = ""

    def __post_init__(self) -> None:
        scheme = canonical_scheme(self.scheme)
        object.__setattr__(self, "scheme", scheme)
        object.__setattr__(self, "authority", _checked_authority(self.authority, scheme))
        object.__setattr__(self, "path", normalize_path(self.path))

    @property
    def name(self) -> str:
        """The last path segment (empty at the root)."""
        return self.path.rsplit("/", 1)[-1]

    @property
    def parent(self) -> StorageURI:
        """The URI one level up; the root is its own parent."""
        head, _, _ = self.path.rpartition("/")
        return StorageURI(self.scheme, self.authority, head)

    def joinpath(self, *segments: str) -> StorageURI:
        """Return this URI with ``segments`` appended to its path."""
        return StorageURI(self.scheme, self.authority, "/".join((self.path, *segments)))

    def __str__(self) -> str:
        root = f"{self.scheme}{_URI_SEPARATOR}{self.authority}"
        if self.path or not self.authority:
            return f"{root}/{self.path}"
        return root


URILike: TypeAlias = str | os.PathLike[str] | StorageURI


def local_path_to_uri(path: str | os.PathLike[str]) -> StorageURI:
    """Return the ``local`` URI of a filesystem path, made absolute first.

    A Windows UNC path ``\\\\server\\share\\x`` becomes ``local://server/share/x``.
    """
    absolute = os.path.abspath(os.fspath(path))
    if os.sep != "\\":
        return StorageURI(LOCAL_SCHEME, "", absolute)
    posix = absolute.replace("\\", "/")
    if posix.startswith("//"):
        host, _, tail = posix[2:].partition("/")
        return StorageURI(LOCAL_SCHEME, host, tail)
    return StorageURI(LOCAL_SCHEME, "", posix)


def parse_storage_uri(value: URILike) -> StorageURI:
    """Turn a URI string, a filesystem path or a ``StorageURI`` into a ``StorageURI``.

    Raises :class:`StorageURIException` when the text is empty, malformed or could
    be read as either a URI or a local path.
    """
    if isinstance(value, StorageURI):
        return value
    text = os.fspath(value)
    if not isinstance(text, str):
        raise StorageURIException("storage URIs and paths must be text, not bytes")
    if not text.strip():
        raise StorageURIException("storage URI is empty")
    if not isinstance(value, str):
        return local_path_to_uri(text)
    scheme, separator, rest = text.partition(_URI_SEPARATOR)
    if separator and len(scheme) > 1 and _SCHEME_PATTERN.fullmatch(scheme.lower()):
        authority, _, path = rest.partition("/")
        return StorageURI(scheme, authority, path)
    scheme_like = _SCHEME_LIKE_PREFIX.match(text)
    if scheme_like:
        prefix = scheme_like.group(1)
        raise StorageURIException(
            f"{text!r} is ambiguous: write '{prefix.lower()}://...' for a storage URI, "
            f"or './{text}' for a local file of that name"
        )
    return local_path_to_uri(text)
