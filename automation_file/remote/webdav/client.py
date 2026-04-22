"""WebDAV client built on ``requests``.

Supports the minimal set used for file automation — ``PUT`` upload, ``GET``
download, ``DELETE``, ``MKCOL`` directory create, ``HEAD`` existence check, and
``PROPFIND`` listing. All URLs pass through
:func:`automation_file.remote.url_validator.validate_http_url`; private /
loopback hosts require ``allow_private_hosts=True``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from urllib.parse import quote, unquote, urlparse

import requests
from defusedxml.ElementTree import ParseError as DefusedParseError
from defusedxml.ElementTree import fromstring as defused_fromstring

from automation_file.exceptions import WebDAVException
from automation_file.remote.url_validator import validate_http_url

_DAV_NS = "{DAV:}"
_DEFAULT_TIMEOUT = 30.0
_ABSOLUTE_URL_PREFIXES = ("http" + "://", "https://")
_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<propfind xmlns="DAV:">'
    "<prop>"
    "<resourcetype/><getcontentlength/><getlastmodified/><displayname/>"
    "</prop>"
    "</propfind>"
)


@dataclass(frozen=True)
class WebDAVEntry:
    """A single directory listing entry returned by :meth:`WebDAVClient.list_dir`."""

    href: str
    name: str
    is_dir: bool
    size: int | None
    last_modified: str | None


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

    def _url_for(self, remote_path: str) -> str:
        remote_path = remote_path.strip()
        if remote_path.startswith(_ABSOLUTE_URL_PREFIXES):
            return remote_path
        remote_path = remote_path.lstrip("/")
        if not remote_path:
            return self._base_url + "/"
        return f"{self._base_url}/{quote(remote_path, safe='/')}"

    def _request(self, method: str, remote_path: str, **kwargs: object) -> requests.Response:
        url = self._url_for(remote_path)
        try:
            response = self._session.request(
                method,
                url,
                auth=self._auth,
                timeout=self._timeout,
                verify=self._verify_tls,
                **kwargs,
            )
        except requests.RequestException as error:
            raise WebDAVException(f"{method} {url} failed: {error}") from error
        if response.status_code >= 400:
            response.close()
            raise WebDAVException(
                f"{method} {url} -> HTTP {response.status_code}: {response.reason}"
            )
        return response

    def exists(self, remote_path: str) -> bool:
        """Return True if the remote resource exists (HEAD 200-299)."""
        url = self._url_for(remote_path)
        try:
            response = self._session.request(
                "HEAD",
                url,
                auth=self._auth,
                timeout=self._timeout,
                verify=self._verify_tls,
            )
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
            response = self._request("PUT", remote_path, data=fh)
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
        """DELETE the remote resource."""
        response = self._request("DELETE", remote_path)
        response.close()

    def mkcol(self, remote_path: str) -> None:
        """MKCOL — create a collection (directory) at the remote path."""
        response = self._request("MKCOL", remote_path)
        response.close()

    def list_dir(self, remote_path: str) -> list[WebDAVEntry]:
        """PROPFIND depth=1 against ``remote_path`` and return its entries."""
        headers = {"Depth": "1", "Content-Type": 'application/xml; charset="utf-8"'}
        response = self._request(
            "PROPFIND",
            remote_path,
            data=_PROPFIND_BODY,
            headers=headers,
        )
        try:
            payload = response.text
        finally:
            response.close()
        return _parse_propfind(payload)


def _parse_propfind(xml_text: str) -> list[WebDAVEntry]:
    try:
        root = defused_fromstring(xml_text)
    except DefusedParseError as error:
        raise WebDAVException(f"malformed PROPFIND response: {error}") from error
    entries: list[WebDAVEntry] = []
    for response in root.findall(f"{_DAV_NS}response"):
        href_elem = response.find(f"{_DAV_NS}href")
        if href_elem is None or href_elem.text is None:
            continue
        href = href_elem.text.strip()
        is_dir = response.find(f".//{_DAV_NS}collection") is not None
        size_elem = response.find(f".//{_DAV_NS}getcontentlength")
        size = int(size_elem.text) if size_elem is not None and size_elem.text else None
        modified_elem = response.find(f".//{_DAV_NS}getlastmodified")
        modified = (
            modified_elem.text.strip() if modified_elem is not None and modified_elem.text else None
        )
        name = unquote(urlparse(href).path.rstrip("/").rsplit("/", 1)[-1])
        entries.append(
            WebDAVEntry(href=href, name=name, is_dir=is_dir, size=size, last_modified=modified)
        )
    return entries
