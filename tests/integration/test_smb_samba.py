"""SMBStorage against a real SMB server (Samba in a container in CI).

Environment: ``FA_IT_SMB_SERVER``, ``FA_IT_SMB_SHARE``, ``FA_IT_SMB_USER``,
``FA_IT_SMB_PASSWORD``, and optionally ``FA_IT_SMB_PORT`` (445) and
``FA_IT_SMB_ENCRYPT`` (``1``; ``0`` for a server without SMB3 encryption).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.integration.service_env import optional_setting, service_setting, unique_name

SERVER = service_setting("FA_IT_SMB_SERVER", "an SMB server")
pytest.importorskip("smbclient", reason="needs the smb extra")

# pylint: disable=wrong-import-position  # the two guards above must come first
from automation_file import SMBClient  # noqa: E402
from automation_file.storage import SMBStorage, StorageBackend  # noqa: E402
from tests.storage_contract import StorageContract  # noqa: E402


@pytest.fixture(scope="module")
def client() -> SMBClient:
    return SMBClient(
        SERVER,
        service_setting("FA_IT_SMB_SHARE", "an SMB server"),
        service_setting("FA_IT_SMB_USER", "an SMB server"),
        service_setting("FA_IT_SMB_PASSWORD", "an SMB server"),
        port=int(optional_setting("FA_IT_SMB_PORT", "445")),
        encrypt=optional_setting("FA_IT_SMB_ENCRYPT", "1") == "1",
    )


class TestSMBServerContract(StorageContract):
    @pytest.fixture
    def backend(self, client: SMBClient) -> Iterator[StorageBackend]:
        whole, name = SMBStorage(client), unique_name()
        whole.mkdir(name)
        yield SMBStorage(client, root=name)
        whole.delete(name, recursive=True)


def test_stat_reports_what_the_server_returns(client: SMBClient) -> None:
    whole, name = SMBStorage(client), unique_name()
    try:
        info = whole.write_bytes(f"{name}/reports/q1.json", b"{}")
        assert info.size == 2
        assert info.modified_at is not None
    finally:
        whole.delete(name, recursive=True)
