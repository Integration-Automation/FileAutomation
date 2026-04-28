Remote operations
=================

.. automodule:: automation_file.remote.url_validator
   :members:

.. automodule:: automation_file.remote.http_download
   :members:

Google Drive
------------

.. automodule:: automation_file.remote.google_drive.client
   :members:

.. automodule:: automation_file.remote.google_drive.delete_ops
   :members:

.. automodule:: automation_file.remote.google_drive.folder_ops
   :members:

.. automodule:: automation_file.remote.google_drive.search_ops
   :members:

.. automodule:: automation_file.remote.google_drive.share_ops
   :members:

.. automodule:: automation_file.remote.google_drive.upload_ops
   :members:

.. automodule:: automation_file.remote.google_drive.download_ops
   :members:

S3
---

Bundled with ``automation_file``; registered automatically by
:func:`automation_file.core.action_registry.build_default_registry`.

.. automodule:: automation_file.remote.s3.client
   :members:

.. automodule:: automation_file.remote.s3.upload_ops
   :members:

.. automodule:: automation_file.remote.s3.download_ops
   :members:

.. automodule:: automation_file.remote.s3.delete_ops
   :members:

.. automodule:: automation_file.remote.s3.list_ops
   :members:

Azure Blob
----------

Bundled with ``automation_file``; registered automatically by
:func:`automation_file.core.action_registry.build_default_registry`.

.. automodule:: automation_file.remote.azure_blob.client
   :members:

.. automodule:: automation_file.remote.azure_blob.upload_ops
   :members:

.. automodule:: automation_file.remote.azure_blob.download_ops
   :members:

.. automodule:: automation_file.remote.azure_blob.delete_ops
   :members:

.. automodule:: automation_file.remote.azure_blob.list_ops
   :members:

Dropbox
-------

Bundled with ``automation_file``; registered automatically by
:func:`automation_file.core.action_registry.build_default_registry`.

.. automodule:: automation_file.remote.dropbox_api.client
   :members:

.. automodule:: automation_file.remote.dropbox_api.upload_ops
   :members:

.. automodule:: automation_file.remote.dropbox_api.download_ops
   :members:

.. automodule:: automation_file.remote.dropbox_api.delete_ops
   :members:

.. automodule:: automation_file.remote.dropbox_api.list_ops
   :members:

SFTP
----

Bundled with ``automation_file``; registered automatically by
:func:`automation_file.core.action_registry.build_default_registry`. Uses
:class:`paramiko.RejectPolicy` — unknown hosts are never auto-added.

.. automodule:: automation_file.remote.sftp.client
   :members:

.. automodule:: automation_file.remote.sftp.upload_ops
   :members:

.. automodule:: automation_file.remote.sftp.download_ops
   :members:

.. automodule:: automation_file.remote.sftp.delete_ops
   :members:

.. automodule:: automation_file.remote.sftp.list_ops
   :members:

FTP / FTPS
----------

Bundled with ``automation_file``; registered automatically by
:func:`automation_file.core.action_registry.build_default_registry`.
Supports plain FTP and explicit FTPS (via ``FTP_TLS`` + ``auth()``).

.. automodule:: automation_file.remote.ftp.client
   :members:

.. automodule:: automation_file.remote.ftp.upload_ops
   :members:

.. automodule:: automation_file.remote.ftp.download_ops
   :members:

.. automodule:: automation_file.remote.ftp.delete_ops
   :members:

.. automodule:: automation_file.remote.ftp.list_ops
   :members:

WebDAV
------

HTTP-based remote storage client. Uses PROPFIND for directory listings and
rejects private/loopback targets unless ``allow_private_hosts=True``.

.. automodule:: automation_file.remote.webdav.client
   :members:

SMB / CIFS
----------

Built on the high-level :mod:`smbclient` API from ``smbprotocol``. Uses UNC
paths (``\\\\server\\share\\path``) under the hood and defaults to
encrypted sessions.

.. automodule:: automation_file.remote.smb.client
   :members:

fsspec bridge
-------------

Thin wrapper over `fsspec <https://filesystem-spec.readthedocs.io/>`_ so any
filesystem it knows about (memory, local, s3, gcs, abfs, …) can be driven
through the action registry. No SSRF guard — treat as a developer helper,
not a remote-ingestion surface.

.. automodule:: automation_file.remote.fsspec_bridge
   :members:

Cross-backend
-------------

.. automodule:: automation_file.remote.cross_backend
   :members:
