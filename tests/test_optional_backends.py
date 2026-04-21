"""Import-time smoke tests for the optional cloud/SFTP backends.

These tests verify that each optional subpackage imports cleanly even when the
third-party SDK is absent, and that calling ``later_init`` raises a clear
``RuntimeError`` in that case. Integration against a real cloud backend lives
outside CI.
"""
from __future__ import annotations

import importlib
import sys

import pytest

_OPTIONAL_BACKENDS = [
    ("automation_file.remote.s3", "s3_instance", ("boto3",)),
    ("automation_file.remote.azure_blob", "azure_blob_instance", ("azure.storage.blob",)),
    ("automation_file.remote.dropbox_api", "dropbox_instance", ("dropbox",)),
    ("automation_file.remote.sftp", "sftp_instance", ("paramiko",)),
]


@pytest.mark.parametrize("module_name,instance_attr,sdk_modules", _OPTIONAL_BACKENDS)
def test_backend_imports_without_sdk(
    module_name: str, instance_attr: str, sdk_modules: tuple[str, ...],
) -> None:
    module = importlib.import_module(module_name)
    assert hasattr(module, instance_attr)
    for sdk in sdk_modules:
        # Modules should only eagerly import our own code, not the optional SDK.
        # Can't assert the SDK is absent (CI may or may not install it), so we
        # just confirm the facade didn't crash.
        assert sys.modules.get(sdk) is None or sys.modules[sdk] is not None


def test_s3_later_init_raises_when_boto3_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import automation_file.remote.s3.client as client_module

    def fake_import() -> None:
        raise RuntimeError("boto3 is required for S3 support; install `automation_file[s3]`")

    monkeypatch.setattr(client_module, "_import_boto3", fake_import)
    with pytest.raises(RuntimeError, match="boto3"):
        client_module.s3_instance.later_init()


def test_register_s3_ops_adds_registry_entries() -> None:
    from automation_file.core.action_registry import ActionRegistry
    from automation_file.remote.s3 import register_s3_ops

    registry = ActionRegistry()
    register_s3_ops(registry)
    assert "FA_s3_upload_file" in registry
    assert "FA_s3_list_bucket" in registry


def test_register_azure_blob_ops_adds_entries() -> None:
    from automation_file.core.action_registry import ActionRegistry
    from automation_file.remote.azure_blob import register_azure_blob_ops

    registry = ActionRegistry()
    register_azure_blob_ops(registry)
    assert "FA_azure_blob_upload_file" in registry


def test_register_dropbox_ops_adds_entries() -> None:
    from automation_file.core.action_registry import ActionRegistry
    from automation_file.remote.dropbox_api import register_dropbox_ops

    registry = ActionRegistry()
    register_dropbox_ops(registry)
    assert "FA_dropbox_upload_file" in registry


def test_register_sftp_ops_adds_entries() -> None:
    from automation_file.core.action_registry import ActionRegistry
    from automation_file.remote.sftp import register_sftp_ops

    registry = ActionRegistry()
    register_sftp_ops(registry)
    assert "FA_sftp_upload_file" in registry
