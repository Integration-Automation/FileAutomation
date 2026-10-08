"""SFTPStorage against a real SFTP server (OpenSSH in a container in CI).

Environment: ``FA_IT_SFTP_HOST``, ``FA_IT_SFTP_USER``, ``FA_IT_SFTP_PASSWORD``,
``FA_IT_SFTP_KNOWN_HOSTS`` (a file holding the server's host key: unknown hosts
are rejected), and optionally ``FA_IT_SFTP_PORT`` (22) and ``FA_IT_SFTP_ROOT``
(``/upload``, an absolute directory the user may write to).
"""

# pylint: disable=arguments-differ  # a fixture or a stand-in takes other arguments than the one it replaces
# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=ungrouped-imports  # imports follow pytest.importorskip

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.integration.service_env import optional_setting, service_setting, unique_name

HOST = service_setting("FA_IT_SFTP_HOST", "an SFTP server")
pytest.importorskip("paramiko", reason="needs the sftp extra")

# pylint: disable=wrong-import-position  # the two guards above must come first
from automation_file import SFTPClient  # noqa: E402
from automation_file.storage import SFTPStorage, StorageBackend  # noqa: E402
from tests.storage_contract import StorageContract  # noqa: E402

ROOT = optional_setting("FA_IT_SFTP_ROOT", "/upload")


@pytest.fixture(scope="module")
def client() -> Iterator[SFTPClient]:
    connected = SFTPClient()
    connected.later_init(
        host=HOST,
        port=int(optional_setting("FA_IT_SFTP_PORT", "22")),
        username=service_setting("FA_IT_SFTP_USER", "an SFTP server"),
        password=service_setting("FA_IT_SFTP_PASSWORD", "an SFTP server"),
        known_hosts=service_setting("FA_IT_SFTP_KNOWN_HOSTS", "an SFTP server"),
    )
    yield connected
    connected.close()


class TestSFTPServerContract(StorageContract):
    @pytest.fixture
    def backend(self, client: SFTPClient) -> Iterator[StorageBackend]:
        whole, name = SFTPStorage(client, root=ROOT), unique_name()
        whole.mkdir(name)
        yield SFTPStorage(client, root=f"{ROOT}/{name}")
        whole.delete(name, recursive=True)


def test_stat_reports_what_the_server_returns(client: SFTPClient) -> None:
    whole, name = SFTPStorage(client, root=ROOT), unique_name()
    try:
        info = whole.write_bytes(f"{name}/reports/q1.json", b"{}")
        assert info.size == 2
        assert info.modified_at is not None
        assert whole.uri_for(f"{name}/reports/q1.json").startswith(f"sftp://{HOST}")
    finally:
        whole.delete(name, recursive=True)
