遠端操作
========

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

隨 ``automation_file`` 一併打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自動登錄。

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

隨 ``automation_file`` 一併打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自動登錄。

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

隨 ``automation_file`` 一併打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自動登錄。

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

隨 ``automation_file`` 一併打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自動登錄。
使用 :class:`paramiko.RejectPolicy`——未知主機不會被自動加入。

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

隨 ``automation_file`` 一併打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自動登錄。
支援純 FTP 與顯式 FTPS（透過 ``FTP_TLS`` + ``auth()``）。

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

以 HTTP 為基礎的遠端儲存客戶端。使用 PROPFIND 取得目錄列表；除非明確傳入
``allow_private_hosts=True``，否則拒絕連往私有 / loopback 目標。

.. automodule:: automation_file.remote.webdav.client
   :members:

SMB / CIFS
----------

建構於 ``smbprotocol`` 套件的高階 :mod:`smbclient` API 之上。底層採用 UNC
路徑（``\\\\server\\share\\path``），預設啟用加密連線。

.. automodule:: automation_file.remote.smb.client
   :members:

fsspec 橋接
-----------

以 `fsspec <https://filesystem-spec.readthedocs.io/>`_ 為基礎的薄包裝層，
讓其支援的任何檔案系統（memory、local、s3、gcs、abfs、…）皆可透過動作
登錄表驅動。未提供 SSRF 防護——僅建議作為開發輔助工具，切勿當作遠端接入介面。

.. automodule:: automation_file.remote.fsspec_bridge
   :members:

跨後端
------

.. automodule:: automation_file.remote.cross_backend
   :members:
