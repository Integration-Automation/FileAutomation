"""WebDAVStorage against a real WebDAV server (Apache mod_dav in a container in CI).

Environment: ``FA_IT_WEBDAV_URL`` (for example ``http://127.0.0.1:8080``),
``FA_IT_WEBDAV_USER`` and ``FA_IT_WEBDAV_PASSWORD``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from automation_file import WebDAVClient
from automation_file.storage import StorageBackend, WebDAVStorage
from tests.integration.service_env import service_setting, unique_name
from tests.storage_contract import StorageContract

URL = service_setting("FA_IT_WEBDAV_URL", "a WebDAV server")


@pytest.fixture(scope="module")
def client() -> Iterator[WebDAVClient]:
    # The server of a test run is on the loopback interface, which the URL guard refuses
    # unless it is told the host is meant to be private.
    with WebDAVClient(
        URL,
        service_setting("FA_IT_WEBDAV_USER", "a WebDAV server"),
        service_setting("FA_IT_WEBDAV_PASSWORD", "a WebDAV server"),
        allow_private_hosts=True,
    ) as connected:
        yield connected


class TestWebDAVServerContract(StorageContract):
    @pytest.fixture
    def backend(self, client: WebDAVClient) -> Iterator[StorageBackend]:
        whole, name = WebDAVStorage(client), unique_name()
        whole.mkdir(name)
        yield WebDAVStorage(client, root=name)
        whole.delete(name, recursive=True)


def test_stat_reports_what_the_server_returns(client: WebDAVClient) -> None:
    whole, name = WebDAVStorage(client), unique_name()
    try:
        info = whole.write_bytes(f"{name}/reports/q1.json", b"{}")
        assert info.size == 2
        assert info.modified_at is not None
    finally:
        whole.delete(name, recursive=True)
