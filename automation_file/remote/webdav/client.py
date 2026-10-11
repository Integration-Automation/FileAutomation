"""WebDAV client built on ``requests``.

Supports the set used for file automation — ``PUT`` upload, ``GET`` download,
``DELETE``, ``MKCOL`` directory create, ``HEAD`` existence check, ``PROPFIND``
lookup and listing, and ``COPY`` / ``MOVE`` on the server. The base URL, and a
``COPY`` / ``MOVE`` destination outside it, pass through
:func:`automation_file.remote.url_validator.validate_http_url`; private /
loopback hosts require ``allow_private_hosts=True``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit

import requests
from defusedxml.ElementTree import ParseError as DefusedParseError
from defusedxml.ElementTree import fromstring as defused_fromstring

from automation_file.exceptions import WebDAVException
from automation_file.remote.url_validator import validate_http_url

_DAV_NS = "{DAV:}"
_DEFAULT_TIMEOUT = 30.0
_ABSOLUTE_URL_PREFIXES = ("http" + "://", "https://")
_MULTI_STATUS = 207
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5
# A redirect is followed only for requests that change nothing on the server.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PROPFIND"})
_DEPTH_SELF = "0"
_DEPTH_MEMBERS = "1"
_PROPFIND_CONTENT_TYPE = 'application/xml; charset="utf-8"'
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<propfind xmlns="DAV:">'
    "<prop>"
    "<resourcetype/><getcontentlength/><getlastmodified/><displayname/>"
    "<getetag/><getcontenttype/>"
    "</prop>"
    "</propfind>"
)


@dataclass(frozen=True)
class WebDAVEntry:
    """One resource as ``PROPFIND`` describes it.

    Returned by :meth:`WebDAVClient.list_dir` and :meth:`WebDAVClient.stat`.
    """

    href: str
    name: str
    is_dir: bool
    size: int | None
    last_modified: str | None
    etag: str | None = None
    content_type: str | None = None


class WebDAVClient:
    """Minimal WebDAV client scoped to the operations used by this project."""

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        *,
        allow_private_hosts: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
        verify_tls: bool = True,
    ) -> None:
        validate_http_url(base_url, allow_private=allow_private_hosts)
        self._base_url = base_url.rstrip("/")
        self._allow_private_hosts = allow_private_hosts
        self._auth: tuple[str, str] | None = (
            (username, password) if username is not None and password is not None else None
        )
        self._timeout = timeout
        self._verify_tls = verify_tls
        self._session = requests.Session()

    def __enter__(self) -> WebDAVClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    @property
    def base_url(self) -> str:
        """The URL every remote path is resolved against, without a trailing slash."""
        return self._base_url

    def _url_for(self, remote_path: str) -> str:
        remote_path = remote_path.strip()
        if remote_path.startswith(_ABSOLUTE_URL_PREFIXES):
            return remote_path
        remote_path = remote_path.lstrip("/")
        if not remote_path:
            return self._base_url + "/"
        return f"{self._base_url}/{quote(remote_path, safe='/')}"

    def _own_url(self, remote_path: str) -> str:
        """Return the URL of ``remote_path``, refusing one outside this client's server."""
        url = self._url_for(remote_path)
        self._require_own_server(url)
        return url

    def _require_own_server(self, url: str) -> None:
        """Raise unless ``url`` is on the scheme, host and port this client was built for.

        A request carries the client's credentials, so it never goes anywhere else.
        """
        ours, theirs = urlsplit(self._base_url), urlsplit(url)
        own = (ours.scheme, ours.netloc.rpartition("@")[2].lower())
        other = (theirs.scheme, theirs.netloc.rpartition("@")[2].lower())
        if other != own:
            raise WebDAVException(
                f"refusing a request to {other[0]}://{other[1]}: "
                f"this client only talks to {own[0]}://{own[1]}"
            )

    def _send(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Send one request. A redirect is followed by hand, and only when it is safe.

        ``requests`` would follow a redirect anywhere, past the URL validation the
        client was built with. Here a redirect is followed for a read-only method
        to a location on the same server, and reported as an error otherwise.
        """
        for _ in range(_MAX_REDIRECTS + 1):
            response = self._session.request(
                method,
                url,
                auth=self._auth,
                timeout=self._timeout,
                verify=self._verify_tls,
                allow_redirects=False,
                **kwargs,
            )
            location = self._redirect_target(method, url, response)
            if location is None:
                return response
            response.close()
            url = location
        raise WebDAVException(f"{method} {url}: more than {_MAX_REDIRECTS} redirects")

    def _redirect_target(self, method: str, url: str, response: requests.Response) -> str | None:
        """Return where to repeat the request, or ``None`` when ``response`` is the answer."""
        if response.status_code not in _REDIRECT_STATUS:
            return None
        location = response.headers.get("Location")
        if not location or method not in _SAFE_METHODS:
            response.close()
            raise WebDAVException(
                f"{method} {url} -> HTTP {response.status_code}: the redirect is not followed",
                status_code=response.status_code,
            )
        target = urljoin(url, location)
        self._require_own_server(target)
        return target

    def _request(self, method: str, remote_path: str, **kwargs: Any) -> requests.Response:
        url = self._own_url(remote_path)
        try:
            response = self._send(method, url, **kwargs)
        except requests.RequestException as error:
            raise WebDAVException(f"{method} {url} failed: {error}") from error
        if response.status_code >= 400:
            response.close()
            raise WebDAVException(
                f"{method} {url} -> HTTP {response.status_code}: {response.reason}",
                status_code=response.status_code,
            )
        return response

    def _change(self, method: str, remote_path: str, **kwargs: Any) -> None:
        """Send a request that changes a resource and everything below it.

        A 207 answer to ``DELETE``, ``COPY`` or ``MOVE`` lists the members the
        server could not change, so it is a failure.
        """
        response = self._request(method, remote_path, **kwargs)
        response.close()
        if response.status_code == _MULTI_STATUS:
            raise WebDAVException(
                f"{method} {self._url_for(remote_path)} -> HTTP {_MULTI_STATUS}: "
                "the server could not complete it for every member",
                status_code=_MULTI_STATUS,
            )

    def exists(self, remote_path: str) -> bool:
        """Return True if the remote resource exists (HEAD 200-299)."""
        url = self._own_url(remote_path)
        try:
            response = self._send("HEAD", url)
        except requests.RequestException as error:
            raise WebDAVException(f"HEAD {url} failed: {error}") from error
        response.close()
        return 200 <= response.status_code < 300

    def upload(self, local_path: str | os.PathLike[str], remote_path: str) -> None:
        """PUT the contents of ``local_path`` to ``remote_path``."""
        source = Path(local_path)
        if not source.is_file():
            raise WebDAVException(f"local source is not a file: {source}")
        with open(source, "rb") as fh:
            # requests sends an empty stream chunked, which some servers refuse;
            # empty bytes go out with ``Content-Length: 0``.
            body: Any = fh if source.stat().st_size else b""
            response = self._request("PUT", remote_path, data=body)
        response.close()

    def download(self, remote_path: str, local_path: str | os.PathLike[str]) -> None:
        """GET the remote resource and stream it to ``local_path``."""
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = self._request("GET", remote_path, stream=True)
        try:
            with open(dest, "wb") as out:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    if chunk:
                        out.write(chunk)
        finally:
            response.close()

    def delete(self, remote_path: str) -> None:
        """DELETE the remote resource; a collection goes with everything in it."""
        self._change("DELETE", remote_path)

    def mkcol(self, remote_path: str) -> None:
        """MKCOL — create a collection (directory) at the remote path."""
        response = self._request("MKCOL", remote_path)
        response.close()

    def copy(self, remote_path: str, destination: str, *, overwrite: bool = True) -> None:
        """COPY ``remote_path`` to ``destination`` on the server."""
        self._relocate("COPY", remote_path, destination, overwrite)

    def move(self, remote_path: str, destination: str, *, overwrite: bool = True) -> None:
        """MOVE ``remote_path`` to ``destination`` on the server."""
        self._relocate("MOVE", remote_path, destination, overwrite)

    def _relocate(self, method: str, remote_path: str, destination: str, overwrite: bool) -> None:
        target = self._url_for(destination)
        if not target.startswith(f"{self._base_url}/"):
            validate_http_url(target, allow_private=self._allow_private_hosts)
        headers = {"Destination": target, "Overwrite": "T" if overwrite else "F"}
        self._change(method, remote_path, headers=headers)

    def stat(self, remote_path: str) -> WebDAVEntry:
        """PROPFIND depth=0 against ``remote_path`` and return its own entry."""
        entries = self._propfind(remote_path, _DEPTH_SELF)
        if not entries:
            raise WebDAVException(f"PROPFIND {self._url_for(remote_path)} described no resource")
        return entries[0]

    def list_dir(self, remote_path: str, *, include_self: bool = True) -> list[WebDAVEntry]:
        """PROPFIND depth=1 against ``remote_path`` and return its entries.

        A server lists the collection itself next to its members;
        ``include_self=False`` leaves that entry out.
        """
        entries = self._propfind(remote_path, _DEPTH_MEMBERS)
        if include_self:
            return entries
        own_path = _decoded_path(self._url_for(remote_path))
        return [entry for entry in entries if _decoded_path(entry.href) != own_path]

    def _propfind(self, remote_path: str, depth: str) -> list[WebDAVEntry]:
        response = self._request(
            "PROPFIND",
            remote_path,
            data=_PROPFIND_BODY,
            headers={"Depth": depth, "Content-Type": _PROPFIND_CONTENT_TYPE},
        )
        try:
            payload = response.text
        finally:
            response.close()
        return _parse_propfind(payload)


def _decoded_path(href: str) -> str:
    """Return the decoded path of an href or a URL, without a trailing slash."""
    return unquote(urlsplit(href).path).rstrip("/")


def _text(element: Any) -> str | None:
    """Return the stripped text of an XML element, or ``None`` when it has none."""
    text = element.text.strip() if element is not None and element.text else ""
    return text or None


def _parse_propfind(xml_text: str) -> list[WebDAVEntry]:
    try:
        root = defused_fromstring(xml_text)
    except DefusedParseError as error:
        raise WebDAVException(f"malformed PROPFIND response: {error}") from error
    entries: list[WebDAVEntry] = []
    for response in root.findall(f"{_DAV_NS}response"):
        href = _text(response.find(f"{_DAV_NS}href"))
        if href is None:
            continue
        size = _text(response.find(f".//{_DAV_NS}getcontentlength"))
        # urlsplit, not urlparse: a ";" in the last segment belongs to the name.
        name = unquote(urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1])
        entries.append(
            WebDAVEntry(
                href=href,
                name=name,
                is_dir=response.find(f".//{_DAV_NS}collection") is not None,
                size=int(size) if size is not None and size.isdigit() else None,
                last_modified=_text(response.find(f".//{_DAV_NS}getlastmodified")),
                etag=_text(response.find(f".//{_DAV_NS}getetag")),
                content_type=_text(response.find(f".//{_DAV_NS}getcontenttype")),
            )
        )
    return entries
