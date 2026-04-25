"""Tests for the cloud / SFTP backends.

The backends (S3, Azure Blob, Dropbox, SFTP) are first-class required
dependencies: importing ``automation_file`` must register every backend's
``FA_*`` operations in the default registry, and each ``register_<backend>_ops``
helper must plug its ops into an arbitrary registry. Integration against a
real cloud backend lives outside CI.
"""

from __future__ import annotations

import importlib

import pytest

_BACKENDS = [
    ("automation_file.remote.s3", "s3_instance"),
    ("automation_file.remote.azure_blob", "azure_blob_instance"),
    ("automation_file.remote.dropbox_api", "dropbox_instance"),
    ("automation_file.remote.sftp", "sftp_instance"),
    ("automation_file.remote.onedrive", "onedrive_instance"),
    ("automation_file.remote.box", "box_instance"),
]


@pytest.mark.parametrize("module_name,instance_attr", _BACKENDS)
def test_backend_module_imports(module_name: str, instance_attr: str) -> None:
    module = importlib.import_module(module_name)
    assert hasattr(module, instance_attr)


def test_default_registry_contains_every_backend() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    expected = [
        "FA_s3_upload_file",
        "FA_s3_list_bucket",
        "FA_azure_blob_upload_file",
        "FA_azure_blob_list_container",
        "FA_dropbox_upload_file",
        "FA_dropbox_list_folder",
        "FA_sftp_upload_file",
        "FA_sftp_list_dir",
        "FA_onedrive_upload_file",
        "FA_onedrive_list_folder",
        "FA_box_upload_file",
        "FA_box_list_folder",
    ]
    for name in expected:
        assert name in registry, f"{name} missing from default registry"


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


def test_register_onedrive_ops_adds_entries() -> None:
    from automation_file.core.action_registry import ActionRegistry
    from automation_file.remote.onedrive import register_onedrive_ops

    registry = ActionRegistry()
    register_onedrive_ops(registry)
    for name in ("FA_onedrive_upload_file", "FA_onedrive_list_folder", "FA_onedrive_close"):
        assert name in registry


def test_register_box_ops_adds_entries() -> None:
    from automation_file.core.action_registry import ActionRegistry
    from automation_file.remote.box import register_box_ops

    registry = ActionRegistry()
    register_box_ops(registry)
    for name in ("FA_box_upload_file", "FA_box_list_folder", "FA_box_delete_file"):
        assert name in registry
