"""An in-memory Google Drive for tests, served to the real ``googleapiclient``.

:class:`FakeDrive` is an ``httplib2`` transport. Hand it to
``googleapiclient.discovery.build("drive", "v3", http=FakeDrive(), static_discovery=True)``
and the service is the real one, built from the Drive v3 discovery document the
package ships: every ``files()`` call has its parameters checked against that
document, an upload and a download speak the resumable and ranged protocols of
``MediaFileUpload`` and ``MediaIoBaseDownload``, and a failure arrives as the
``HttpError`` googleapiclient builds from the response. No request leaves the
process.

What the stand-in answers is a reading of Drive's documentation, not a recording
of the service. It assumes that a folder can hold several entries of one name,
that ``name =`` in a query ignores case, that a query below a folder that does
not exist is a 404, that ``root`` is an alias of the My Drive folder wherever a
file ID goes, that a ranged read of an empty file is a 416 with
``Content-Range: bytes */0``, and that deleting a folder deletes what is in it.
Where it is stricter than Drive (``addParents`` takes real IDs only) a comment
says so.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import googleapiclient
import httplib2

from automation_file.storage.gdrive_storage import FOLDER_MIME_TYPE

MY_DRIVE_ID = "0AFakeMyDriveRootId"
DOCUMENT_MIME_TYPE = "application/vnd.google-apps.document"
BINARY_MIME_TYPE = "application/octet-stream"
LIST_PAGE = 2
UPLOAD_CHUNK_UNIT = 256 * 1024
UPLOAD_URL = "https://upload.drive.invalid/session/"
DISCOVERY = json.loads(
    (
        Path(googleapiclient.__file__).parent / "discovery_cache" / "documents" / "drive.v3.json"
    ).read_text(encoding="utf-8")
)
FILE_SCHEMA = DISCOVERY["schemas"]["File"]["properties"]
FILE_METHODS = DISCOVERY["resources"]["files"]["methods"]
_LITERAL = r"'((?:[^'\\]|\\.)*)'"
_QUERY = re.compile(rf"{_LITERAL} in parents(?: and name = {_LITERAL})? and trashed = false")


class _Failure(Exception):
    """An error answer of the stand-in: an HTTP status and a Drive ``reason`` code."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(f"{status} {reason}")
        self.status = status
        self.reason = reason


def error_answer(status: int, reason: str) -> tuple[httplib2.Response, bytes]:
    body = {
        "error": {
            "code": status,
            "message": f"stand-in says {reason}",
            "errors": [{"domain": "global", "reason": reason, "message": reason}],
        }
    }
    headers = {"status": str(status), "content-type": "application/json"}
    return httplib2.Response(headers), json.dumps(body).encode("utf-8")


def _answer(document: Any) -> tuple[httplib2.Response, bytes]:
    headers = {"status": "200", "content-type": "application/json"}
    return httplib2.Response(headers), json.dumps(document).encode("utf-8")


def _unescaped(literal: str) -> str:
    return re.sub(r"\\(.)", r"\1", literal)


def _field_names(fields: str) -> list[str]:
    """Split a ``fields`` selection of File properties; Drive refuses one it does not know."""
    names = [name.strip() for name in fields.split(",")]
    if any(name not in FILE_SCHEMA for name in names):
        raise _Failure(400, "invalid")
    return names


@dataclass
class _Entry:
    file_id: str
    name: str
    mime_type: str
    parent: str | None
    data: bytes | None = None
    version: int = 1
    trashed: bool = False
    modified: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def resource(self, *, digests: bool = True) -> dict[str, Any]:
        stamp = self.modified.strftime("%Y-%m-%dT%H:%M:%S")
        resource: dict[str, Any] = {
            "id": self.file_id,
            "name": self.name,
            "mimeType": self.mime_type,
            "parents": [self.parent] if self.parent else [],
            "trashed": self.trashed,
            "modifiedTime": f"{stamp}.{self.modified.microsecond // 1000:03d}Z",
            "version": str(self.version),
        }
        if self.data is not None:
            resource["size"] = str(len(self.data))
            if digests:
                resource["md5Checksum"] = hashlib.md5(self.data, usedforsecurity=False).hexdigest()
                resource["sha1Checksum"] = hashlib.sha1(
                    self.data, usedforsecurity=False
                ).hexdigest()
                resource["sha256Checksum"] = hashlib.sha256(self.data).hexdigest()
        elif self.mime_type != FOLDER_MIME_TYPE:
            # Drive reports the storage a Workspace document uses, which is not a content length.
            resource["size"] = "1024"
        return resource


@dataclass
class _Upload:
    file_id: str | None
    metadata: dict[str, Any]
    mime_type: str
    size: int
    fields: str
    received: bytearray = field(default_factory=bytearray)


@dataclass
class _Seen:
    call: str
    params: dict[str, str]
    headers: dict[str, str]
    body: Any = None


class FakeDrive:
    """The part of the Drive v3 REST API that GoogleDriveStorage reaches, as an httplib2 transport.

    Like Drive, it lets a folder hold several entries of one name, matches ``name =``
    without regard to case, pages its listings, returns only the fields that were
    asked for and removes a folder together with everything below it.
    """

    def __init__(self) -> None:
        self.entries: dict[str, _Entry] = {
            MY_DRIVE_ID: _Entry(MY_DRIVE_ID, "My Drive", FOLDER_MIME_TYPE, None)
        }
        self.seen: list[_Seen] = []
        self.fail_with: tuple[int, str] | Exception | None = None
        self.fail_methods: frozenset[str] | None = None
        self.digests = True
        self._ids = itertools.count(1)
        self._uploads: dict[str, _Upload] = {}

    # ------------------------------------------------------------------ for the tests

    @property
    def calls(self) -> list[str]:
        return [seen.call for seen in self.seen]

    def last(self, call: str) -> _Seen:
        return next(seen for seen in reversed(self.seen) if seen.call == call)

    def add_folder(self, name: str, parent: str = MY_DRIVE_ID) -> str:
        return self._new(name, FOLDER_MIME_TYPE, parent, None).file_id

    def add_file(
        self, name: str, data: bytes, parent: str = MY_DRIVE_ID, mime_type: str = BINARY_MIME_TYPE
    ) -> str:
        return self._new(name, mime_type, parent, data).file_id

    def add_document(self, name: str, parent: str = MY_DRIVE_ID) -> str:
        return self._new(name, DOCUMENT_MIME_TYPE, parent, None).file_id

    def named(self, name: str) -> list[_Entry]:
        return [entry for entry in self.entries.values() if entry.name == name]

    def only(self, name: str) -> _Entry:
        (entry,) = self.named(name)
        return entry

    # ------------------------------------------------------------------ httplib2.Http

    def request(
        self,
        uri: str,
        method: str = "GET",
        body: Any = None,
        headers: dict[str, str] | None = None,
        redirections: int = 1,
        connection_type: Any = None,
    ) -> tuple[httplib2.Response, bytes]:
        del redirections, connection_type
        if self.fail_with is not None and (
            self.fail_methods is None or method in self.fail_methods
        ):
            if isinstance(self.fail_with, Exception):
                raise self.fail_with
            return error_answer(*self.fail_with)
        lowered = {key.lower(): value for key, value in (headers or {}).items()}
        try:
            if uri.startswith(UPLOAD_URL):
                return self._receive(uri, body, lowered)
            split = urlsplit(uri)
            return self._route(method, split.path, dict(parse_qsl(split.query)), body, lowered)
        except _Failure as failure:
            return error_answer(failure.status, failure.reason)

    def close(self) -> None:
        return None

    # ------------------------------------------------------------------ routing

    def _route(
        self, method: str, path: str, params: dict[str, str], body: Any, headers: dict[str, str]
    ) -> tuple[httplib2.Response, bytes]:
        assert params.get("supportsAllDrives") == "true", (
            f"{method} {path} without supportsAllDrives"
        )
        if path.startswith("/upload/drive/v3/files"):
            file_id = path.removeprefix("/upload/drive/v3/files").strip("/")
            return self._open_upload(method, file_id, params, body, headers)
        assert path.startswith("/drive/v3/files"), f"unexpected Drive path {path}"
        file_id, _, verb = path.removeprefix("/drive/v3/files").strip("/").partition("/")
        if not file_id:
            if method == "GET":
                return self._list(params, headers)
            return self._create(params, json.loads(body), headers)
        if verb == "copy":
            return self._copy(file_id, params, json.loads(body), headers)
        assert not verb, f"unexpected Drive path {path}"
        if method == "DELETE":
            return self._delete(file_id, params, headers)
        if method == "PATCH":
            return self._update(file_id, params, json.loads(body), headers)
        if params.get("alt") == "media":
            return self._media(file_id, params, headers)
        self.seen.append(_Seen("get", params, headers))
        return _answer(self._projected(self._entry(file_id), params["fields"]))

    def _new(self, name: str, mime_type: str, parent: str, data: bytes | None) -> _Entry:
        entry = _Entry(f"id-{next(self._ids):04d}", name, mime_type, parent, data)
        self.entries[entry.file_id] = entry
        return entry

    def _entry(self, file_id: str) -> _Entry:
        """Look an ID up; ``root`` is Drive's alias of the My Drive folder."""
        entry = self.entries.get(MY_DRIVE_ID if file_id == "root" else file_id)
        if entry is None:
            raise _Failure(404, "notFound")
        return entry

    def _folder(self, file_id: str) -> _Entry:
        entry = self._entry(file_id)
        if entry.mime_type != FOLDER_MIME_TYPE:
            raise _Failure(400, "invalid")
        return entry

    def _projected(self, entry: _Entry, fields: str) -> dict[str, Any]:
        resource = entry.resource(digests=self.digests)
        return {name: resource[name] for name in _field_names(fields) if name in resource}

    # ------------------------------------------------------------------ files.list / get / delete

    def _list(self, params: dict[str, str], headers: dict[str, str]) -> Any:
        self.seen.append(_Seen("list", params, headers))
        assert params.get("includeItemsFromAllDrives") == "true"
        query = _QUERY.fullmatch(params["q"])
        selection = re.fullmatch(r"nextPageToken, files\((.*)\)", params["fields"])
        if query is None or selection is None:
            raise _Failure(400, "invalid")
        folder = self._entry(_unescaped(query.group(1)))
        name = None if query.group(2) is None else _unescaped(query.group(2)).casefold()
        matches = [
            entry
            for entry in self.entries.values()
            if entry.parent == folder.file_id
            and not entry.trashed
            and (name is None or entry.name.casefold() == name)
        ]
        start = int(params.get("pageToken", "0"))
        end = start + min(int(params.get("pageSize", "100")), LIST_PAGE)
        page: dict[str, Any] = {
            "files": [self._projected(entry, selection.group(1)) for entry in matches[start:end]]
        }
        if end < len(matches):
            page["nextPageToken"] = str(end)
        return _answer(page)

    def _media(self, file_id: str, params: dict[str, str], headers: dict[str, str]) -> Any:
        self.seen.append(_Seen("media", params, headers))
        data = self._entry(file_id).data
        if data is None:
            raise _Failure(403, "fileNotDownloadable")
        wanted = re.fullmatch(r"bytes=(\d+)-(\d+)", headers["range"])
        assert wanted is not None
        if not data:
            return httplib2.Response({"status": "416", "content-range": "bytes */0"}), b""
        start = int(wanted.group(1))
        chunk = data[start : int(wanted.group(2)) + 1]
        span = f"bytes {start}-{start + len(chunk) - 1}/{len(data)}"
        return httplib2.Response({"status": "206", "content-range": span}), chunk

    def _delete(self, file_id: str, params: dict[str, str], headers: dict[str, str]) -> Any:
        self.seen.append(_Seen("delete", params, headers))
        doomed = [self._entry(file_id).file_id]
        if doomed == [MY_DRIVE_ID]:
            raise _Failure(403, "insufficientFilePermissions")
        for parent in doomed:
            doomed.extend(key for key, entry in self.entries.items() if entry.parent == parent)
        for key in doomed:
            del self.entries[key]
        return httplib2.Response({"status": "204"}), b""

    # ------------------------------------------------------------------ files.create / update / copy

    def _create(self, params: dict[str, str], metadata: dict[str, Any], headers: Any) -> Any:
        self.seen.append(_Seen("create", params, headers, metadata))
        # Without media the adapter only ever creates folders.
        assert metadata["mimeType"] == FOLDER_MIME_TYPE
        (parent,) = metadata["parents"]
        entry = self._new(metadata["name"], FOLDER_MIME_TYPE, self._folder(parent).file_id, None)
        return _answer(self._projected(entry, params["fields"]))

    def _update(self, file_id: str, params: dict[str, str], metadata: Any, headers: Any) -> Any:
        self.seen.append(_Seen("update", params, headers, metadata))
        entry = self._entry(file_id)
        if "addParents" in params:
            # Stricter than Drive on purpose: real IDs only, so the adapter may not lean on
            # the "root" alias being accepted here.
            if params.get("removeParents") != entry.parent or params["addParents"] == "root":
                raise _Failure(400, "invalid")
            entry.parent = self._folder(params["addParents"]).file_id
        else:
            assert "removeParents" not in params
        entry.name = metadata.get("name", entry.name)
        entry.version += 1
        return _answer(self._projected(entry, params["fields"]))

    def _copy(self, file_id: str, params: dict[str, str], metadata: Any, headers: Any) -> Any:
        self.seen.append(_Seen("copy", params, headers, metadata))
        source = self._entry(file_id)
        (parent,) = metadata["parents"]
        copied = self._new(
            metadata["name"], source.mime_type, self._folder(parent).file_id, source.data
        )
        return _answer(self._projected(copied, params["fields"]))

    # ------------------------------------------------------------------ resumable upload

    def _open_upload(
        self, method: str, file_id: str, params: dict[str, str], body: Any, headers: dict[str, str]
    ) -> Any:
        metadata = json.loads(body) if body else {}
        self.seen.append(_Seen("update" if file_id else "create", params, headers, metadata))
        assert params["uploadType"] == "resumable"
        assert method == ("PATCH" if file_id else "POST")
        if file_id:
            self._entry(file_id)
        else:
            (parent,) = metadata["parents"]
            self._folder(parent)
        token = f"{UPLOAD_URL}{next(self._ids)}"
        self._uploads[token] = _Upload(
            file_id or None,
            metadata,
            headers["x-upload-content-type"],
            int(headers["x-upload-content-length"]),
            params["fields"],
        )
        return httplib2.Response({"status": "200", "location": token}), b""

    def _receive(self, uri: str, body: Any, headers: dict[str, str]) -> Any:
        self.seen.append(_Seen("upload", {}, headers))
        upload = self._uploads[uri]
        data = body.read() if hasattr(body, "read") else (body or b"")
        assert int(headers["content-length"]) == len(data)
        if data:
            first = len(upload.received)
            span = f"bytes {first}-{first + len(data) - 1}/{upload.size}"
            assert headers["content-range"] == span
        else:
            # googleapiclient sends an empty file without a Content-Range.
            assert "content-range" not in headers
        upload.received.extend(data)
        if len(upload.received) < upload.size:
            assert len(data) % UPLOAD_CHUNK_UNIT == 0, "a chunk must be a multiple of 256 KiB"
            last = len(upload.received) - 1
            return httplib2.Response({"status": "308", "range": f"bytes=0-{last}"}), b""
        del self._uploads[uri]
        return _answer(self._projected(self._stored(upload), upload.fields))

    def _stored(self, upload: _Upload) -> _Entry:
        content = bytes(upload.received)
        if upload.file_id is None:
            (parent,) = upload.metadata["parents"]
            mime_type = upload.metadata.get("mimeType", upload.mime_type)
            return self._new(
                upload.metadata["name"], mime_type, self._folder(parent).file_id, content
            )
        entry = self._entry(upload.file_id)
        entry.data = content
        entry.mime_type = upload.mime_type
        entry.version += 1
        entry.modified = datetime.now(timezone.utc)
        return entry
