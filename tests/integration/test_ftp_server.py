"""FTPStorage against a real FTP server (a container in CI).

Environment: ``FA_IT_FTP_HOST``, ``FA_IT_FTP_USER``, ``FA_IT_FTP_PASSWORD``, and
optionally ``FA_IT_FTP_PORT`` (21), ``FA_IT_FTP_ROOT`` (``/``, an absolute
directory the user may write to) and ``FA_IT_FTP_TLS`` (``1`` for FTPS).
"""

# pylint: disable=arguments-differ  # a fixture or a stand-in takes other arguments than the one it replaces
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name

from __future__ import annotations

from collections.abc import Iterator

import pytest

from automation_file import FTPClient
from automation_file.storage import FTPStorage, StorageBackend
from tests.integration.service_env import optional_setting, service_setting, unique_name
from tests.storage_contract import StorageContract

HOST = service_setting("FA_IT_FTP_HOST", "an FTP server")
ROOT = optional_setting("FA_IT_FTP_ROOT", "/")


@pytest.fixture(scope="module")
def client() -> Iterator[FTPClient]:
    connected = FTPClient()
    connected.later_init(
        host=HOST,
        port=int(optional_setting("FA_IT_FTP_PORT", "21")),
        username=service_setting("FA_IT_FTP_USER", "an FTP server"),
        password=service_setting("FA_IT_FTP_PASSWORD", "an FTP server"),
        tls=optional_setting("FA_IT_FTP_TLS", "0") == "1",
    )
    yield connected
    connected.close()


class TestFTPServerContract(StorageContract):
    @pytest.fixture
    def backend(self, client: FTPClient) -> Iterator[StorageBackend]:
        whole, name = FTPStorage(client, root=ROOT), unique_name()
        whole.mkdir(name)
        yield FTPStorage(client, root=f"{ROOT.rstrip('/')}/{name}")
        whole.delete(name, recursive=True)


def test_stat_reports_what_the_server_returns(client: FTPClient) -> None:
    whole, name = FTPStorage(client, root=ROOT), unique_name()
    try:
        info = whole.write_bytes(f"{name}/reports/q1.json", b"{}")
        assert info.size == 2
        assert whole.read_bytes(f"{name}/reports/q1.json") == b"{}"
    finally:
        whole.delete(name, recursive=True)
