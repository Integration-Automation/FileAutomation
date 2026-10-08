"""An in-memory OneDrive for tests, served to a real ``requests.Session``.

:class:`FakeGraph` is a ``requests`` transport adapter. Mount it on the session of
a real ``OneDriveClient`` and every request is prepared by ``requests`` itself --
the merged headers, the encoded URL, the body and its length, the redirect of a
download -- before the stand-in answers it the way Microsoft Graph documents its
``driveItem`` API. No request leaves the process.

What the stand-in answers is a reading of that documentation, not a recording of
the service, and nothing installed describes Graph. It assumes that names are
compared without regard to case, that a path through a file is a 404, that an
upload creates the folders missing on its path, that creating a folder whose name
is taken is a 409, that ``/content`` redirects to a pre-authenticated URL, that
an upload session answers 202 until its last fragment, and that deleting a folder
deletes what is in it.
"""

# pylint: disable=raising-bad-type  # a stand-in raises what the test hands it
# pylint: disable=too-many-locals  # one scenario told in order
# pylint: disable=too-many-positional-arguments  # a stand-in keeps the real signature
# pylint: disable=unsupported-membership-test  # the value is a container at run time

from __future__ import annotations

import io
import itertools
import json
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlsplit

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

GRAPH_ORIGIN = "https://graph.microsoft.com"
DRIVE_ROOT = "/v1.0/me/drive/root"
UPLOAD_ORIGIN = "https://upload.onedrive.invalid"
DOWNLOAD_ORIGIN = "https://download.onedrive.invalid"
# Not credentials: markers the stand-in hands out and the tests look for in messages.
FAKE_TOKEN = "fake-token"  # nosec B105
URL_SIGNATURE = "tempauth=fake-url-secret"  # nosec B105
ROOT_ID = "ROOT"
DRIVE_ID = "fake-drive"
LIST_PAGE = 2
KIB = 1024
FRAGMENT_UNIT = 320 * KIB
FRAGMENT_LIMIT = 60 * KIB * KIB
SIMPLE_UPLOAD_LIMIT = 4 * KIB * KIB
FORBIDDEN_IN_NAMES = frozenset('"*:<>?/\\|')
ERROR_CODES = {
    400: "invalidRequest",
    401: "unauthenticated",
    403: "accessDenied",
    404: "itemNotFound",
    408: "requestTimeout",
    409: "nameAlreadyExists",
    429: "activityLimitReached",
    500: "generalException",
    503: "serviceNotAvailable",
    504: "gatewayTimeout",
    507: "quotaLimitReached",
}
CALLS = {
    (GRAPH_ORIGIN, "GET", ""): "item",
    (GRAPH_ORIGIN, "PATCH", ""): "patch",
    (GRAPH_ORIGIN, "DELETE", ""): "delete",
    (GRAPH_ORIGIN, "GET", "/children"): "children",
    (GRAPH_ORIGIN, "POST", "/children"): "mkdir",
    (GRAPH_ORIGIN, "PUT", "/content"): "put",
    (GRAPH_ORIGIN, "GET", "/content"): "content",
    (GRAPH_ORIGIN, "POST", "/createUploadSession"): "session",
    (UPLOAD_ORIGIN, "PUT", ""): "fragment",
    (UPLOAD_ORIGIN, "DELETE", ""): "cancel",
    (DOWNLOAD_ORIGIN, "GET", ""): "download",
}


class _Failure(Exception):
    """An error answer of the stand-in."""

    def __init__(self, status: int) -> None:
        super().__init__(str(status))
        self.status = status


@dataclass
class _Item:
    item_id: str
    name: str
    parent: str | None
    data: bytes | None = None
    revision: int = 1
    modified: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def resource(self, child_count: int) -> dict[str, Any]:
        stamp = self.modified.strftime("%Y-%m-%dT%H:%M:%S")
        resource: dict[str, Any] = {
            "id": self.item_id,
            "name": self.name,
            "eTag": f'"{{{self.item_id}}},{self.revision}"',
            # Seven fractional digits, as Graph sometimes sends.
            "lastModifiedDateTime": f"{stamp}.{self.modified.microsecond:06d}0Z",
            "parentReference": {"driveId": DRIVE_ID, "id": self.parent},
            "size": len(self.data or b""),
        }
        if self.data is None:
            resource["folder"] = {"childCount": child_count}
        else:
            # OneDrive derives the type from the name, not from the upload's Content-Type.
            mime_type = mimetypes.guess_type(self.name)[0] or "application/octet-stream"
            resource["file"] = {"mimeType": mime_type}
        return resource


@dataclass
class _Seen:
    call: str
    url: str
    headers: dict[str, str]
    stream: bool
    body: bytes


def graph_answer(
    request: requests.PreparedRequest,
    status: int,
    document: Any = None,
    *,
    content: bytes = b"",
    location: str | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.request = request
    response.url = request.url or ""
    body = content if document is None else json.dumps(document).encode("utf-8")
    response.headers = CaseInsensitiveDict({"Content-Length": str(len(body))})
    if document is not None:
        response.headers["Content-Type"] = "application/json"
    if location is not None:
        response.headers["Location"] = location
    response.raw = io.BytesIO(body)
    return response


def _error(request: requests.PreparedRequest, status: int) -> requests.Response:
    code = ERROR_CODES.get(status, "generalException")
    return graph_answer(request, status, {"error": {"code": code, "message": f"stand-in: {code}"}})


def _address(origin: str, raw_path: str) -> tuple[str, str]:
    """Split the path of a URL into the drive path it names and the facet asked for."""
    if origin != GRAPH_ORIGIN:
        return raw_path, ""
    assert raw_path.startswith(DRIVE_ROOT), f"unexpected Graph path {raw_path}"
    rest = raw_path.removeprefix(DRIVE_ROOT)
    if not rest.startswith(":"):
        return "", rest
    # A colon inside a name would arrive percent-encoded, so these colons are the delimiters.
    item, _, facet = rest[1:].partition(":")
    return unquote(item).strip("/"), facet


class FakeGraph(BaseAdapter):
    """The part of Microsoft Graph that OneDriveStorage reaches, as a requests transport.

    Like OneDrive, it compares names without regard to case, pages its listings,
    returns only the selected properties, redirects a download to a
    pre-authenticated URL, takes a large file through an upload session and
    removes a folder together with everything below it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.items: dict[str, _Item] = {ROOT_ID: _Item(ROOT_ID, "root", None)}
        self.seen: list[_Seen] = []
        self.fail_with: int | Exception | None = None
        self.fail_calls: frozenset[str] | None = None
        self.sessions: dict[str, tuple[str, bytearray]] = {}
        self._ids = itertools.count(1)
        self._downloads: dict[str, bytes] = {}

    # ------------------------------------------------------------------ for the tests

    @property
    def calls(self) -> list[str]:
        return [seen.call for seen in self.seen]

    def all(self, call: str) -> list[_Seen]:
        return [seen for seen in self.seen if seen.call == call]

    def find(self, path: str) -> _Item | None:
        item = self.items[ROOT_ID]
        for segment in filter(None, path.split("/")):
            wanted = segment.casefold()
            named = [child for child in self._children(item) if child.name.casefold() == wanted]
            if not named:
                return None
            (item,) = named
        return item

    def at(self, path: str) -> _Item:
        item = self.find(path)
        assert item is not None, f"nothing at {path}"
        return item

    def add_file(self, path: str, data: bytes) -> _Item:
        return self._store(path, data)[0]

    def add_folder(self, path: str) -> _Item:
        return self._folder(path)

    def paths(self) -> list[str]:
        found: list[str] = []
        pending = [("", self.items[ROOT_ID])]
        while pending:
            base, folder = pending.pop()
            for child in self._children(folder):
                path = f"{base}/{child.name}" if base else child.name
                found.append(path)
                if child.data is None:
                    pending.append((path, child))
        return sorted(found)

    # ------------------------------------------------------------------ requests transport

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        del cert, proxies
        assert verify is not False, "TLS verification was switched off"
        assert timeout is not None, "a request without a timeout"
        assert "Transfer-Encoding" not in request.headers, "a body without a length"
        url = request.url or ""
        split = urlsplit(url)
        origin = f"{split.scheme}://{split.netloc}"
        if origin == GRAPH_ORIGIN:
            assert request.headers.get("Authorization") == f"Bearer {FAKE_TOKEN}"
        else:
            assert "Authorization" not in request.headers, f"the bearer token reached {origin}"
        path, facet = _address(origin, split.path)
        call = CALLS[origin, request.method or "", facet]
        body = request.body or b""
        assert isinstance(body, bytes)
        self.seen.append(_Seen(call, url, dict(request.headers), stream, body))
        if self.fail_with is not None and (self.fail_calls is None or call in self.fail_calls):
            if isinstance(self.fail_with, Exception):
                raise self.fail_with
            return _error(request, self.fail_with)
        try:
            handler = getattr(self, f"_on_{call}")
            return handler(request, path, dict(parse_qsl(split.query)), body)
        except _Failure as failure:
            return _error(request, failure.status)

    def close(self) -> None:
        return None

    # ------------------------------------------------------------------ the drive

    def _children(self, folder: _Item) -> list[_Item]:
        return [item for item in self.items.values() if item.parent == folder.item_id]

    def _existing(self, path: str) -> _Item:
        item = self.find(path)
        if item is None:
            raise _Failure(404)
        return item

    def _resource(self, item: _Item, params: dict[str, str]) -> dict[str, Any]:
        resource = item.resource(len(self._children(item)))
        selected = params.get("$select")
        if selected is None:
            return resource
        return {key: value for key, value in resource.items() if key in selected.split(",")}

    def _new(self, name: str, parent: _Item, data: bytes | None) -> _Item:
        if not name or FORBIDDEN_IN_NAMES & set(name):
            raise _Failure(400)
        if parent.data is not None:
            raise _Failure(404)
        item = _Item(f"ITEM{next(self._ids):04d}", name, parent.item_id, data)
        self.items[item.item_id] = item
        return item

    def _folder(self, path: str) -> _Item:
        """Return the folder at ``path``, creating what is missing, as an upload does."""
        folder = self.items[ROOT_ID]
        walked = ""
        for segment in filter(None, path.split("/")):
            walked = f"{walked}/{segment}"
            folder = self.find(walked) or self._new(segment, folder, None)
        return folder

    def _store(self, path: str, data: bytes) -> tuple[_Item, bool]:
        """Create or replace the file at ``path``; say whether it is new."""
        existing = self.find(path)
        if existing is None:
            directory, _, name = path.rpartition("/")
            return self._new(name, self._folder(directory), data), True
        if existing.data is None:
            raise _Failure(409)
        existing.data = data
        existing.revision += 1
        existing.modified = datetime.now(timezone.utc)
        return existing, False

    # ------------------------------------------------------------------ Graph calls

    def _on_item(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        del body
        return graph_answer(request, 200, self._resource(self._existing(path), params))

    def _on_children(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        del body
        children = self._children(self._existing(path))
        start = int(params.get("$skiptoken", "0"))
        end = start + min(int(params.get("$top", LIST_PAGE)), LIST_PAGE)
        page: dict[str, Any] = {
            "value": [self._resource(child, params) for child in children[start:end]]
        }
        if end < len(children):
            following = {**params, "$skiptoken": str(end)}
            query = "&".join(f"{key}={quote(value, safe='')}" for key, value in following.items())
            page["@odata.nextLink"] = f"{request.url.partition('?')[0]}?{query}"
        return graph_answer(request, 200, page)

    def _on_mkdir(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        wanted = json.loads(body)
        assert wanted["folder"] == {}
        assert wanted["@microsoft.graph.conflictBehavior"] == "fail"
        parent = self._existing(path)
        folded = wanted["name"].casefold()
        if any(child.name.casefold() == folded for child in self._children(parent)):
            raise _Failure(409)
        created = self._new(wanted["name"], parent, None)
        return graph_answer(request, 201, self._resource(created, params))

    def _on_put(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        assert len(body) <= SIMPLE_UPLOAD_LIMIT, "too large for a simple upload"
        assert int(request.headers["Content-Length"]) == len(body)
        item, created = self._store(path, body)
        return graph_answer(request, 201 if created else 200, self._resource(item, params))

    def _on_content(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        del params, body
        data = self._existing(path).data
        if data is None:
            raise _Failure(400)
        ticket = f"{DOWNLOAD_ORIGIN}/content/{next(self._ids)}?{URL_SIGNATURE}"
        self._downloads[ticket] = data
        return graph_answer(request, 302, location=ticket)

    def _on_download(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        del path, params, body
        return graph_answer(request, 200, content=self._downloads.pop(request.url))

    def _on_session(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        del params
        assert json.loads(body) == {"item": {"@microsoft.graph.conflictBehavior": "replace"}}
        existing = self.find(path)
        if existing is not None and existing.data is None:
            raise _Failure(409)
        upload_url = f"{UPLOAD_ORIGIN}/session/{next(self._ids)}?{URL_SIGNATURE}"
        self.sessions[upload_url] = (path, bytearray())
        return graph_answer(request, 200, {"uploadUrl": upload_url, "nextExpectedRanges": ["0-"]})

    def _on_fragment(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        del path, params
        target, received = self.sessions[request.url]
        span, _, total = request.headers["Content-Range"].removeprefix("bytes ").partition("/")
        first, _, last = span.partition("-")
        assert int(first) == len(received), "fragments out of order"
        assert int(last) - int(first) + 1 == len(body) == int(request.headers["Content-Length"])
        assert 0 < len(body) <= FRAGMENT_LIMIT
        received.extend(body)
        if len(received) < int(total):
            assert len(body) % FRAGMENT_UNIT == 0, "a fragment must be a multiple of 320 KiB"
            expected = f"{len(received)}-{int(total) - 1}"
            return graph_answer(request, 202, {"nextExpectedRanges": [expected]})
        del self.sessions[request.url]
        item, created = self._store(target, bytes(received))
        return graph_answer(request, 201 if created else 200, self._resource(item, {}))

    def _on_cancel(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        del path, params, body
        del self.sessions[request.url]
        return graph_answer(request, 204)

    def _on_patch(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        item = self._existing(path)
        wanted = json.loads(body)
        name = wanted["name"]
        parent = self.items.get(wanted["parentReference"]["id"])
        if parent is None or parent.data is not None:
            raise _Failure(404)
        if FORBIDDEN_IN_NAMES & set(name):
            raise _Failure(400)
        siblings = [other for other in self._children(parent) if other is not item]
        if any(other.name.casefold() == name.casefold() for other in siblings):
            raise _Failure(409)
        item.name, item.parent = name, parent.item_id
        return graph_answer(request, 200, self._resource(item, params))

    def _on_delete(self, request: Any, path: str, params: dict[str, str], body: bytes) -> Any:
        del params, body
        doomed = [self._existing(path)]
        if doomed[0].item_id == ROOT_ID:
            raise _Failure(400)
        for item in doomed:
            doomed.extend(self._children(item))
        for item in doomed:
            del self.items[item.item_id]
        return graph_answer(request, 204)
