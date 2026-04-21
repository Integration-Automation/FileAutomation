远程操作
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

随 ``automation_file`` 一并打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自动注册。

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

随 ``automation_file`` 一并打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自动注册。

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

随 ``automation_file`` 一并打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自动注册。

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

随 ``automation_file`` 一并打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自动注册。
使用 :class:`paramiko.RejectPolicy`——未知主机不会被自动添加。

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

随 ``automation_file`` 一并打包；由
:func:`automation_file.core.action_registry.build_default_registry` 自动注册。
支持纯 FTP 与显式 FTPS（通过 ``FTP_TLS`` + ``auth()``）。

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

跨后端
------

.. automodule:: automation_file.remote.cross_backend
   :members:
