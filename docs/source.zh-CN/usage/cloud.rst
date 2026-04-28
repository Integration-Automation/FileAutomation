云与 SFTP 后端
==============

每个后端（Google Drive、S3、Azure Blob、Dropbox、SFTP）都是
``automation_file`` 自带的，并由
:func:`~automation_file.core.action_registry.build_default_registry` 自动注册。
无需额外安装步骤——在单例上调用 ``later_init`` 即可使用：

.. code-block:: python

   from automation_file import execute_action, s3_instance

   s3_instance.later_init(region_name="us-east-1")

   execute_action([
       ["FA_s3_upload_file", {"local_path": "report.csv",
                              "bucket": "reports", "key": "report.csv"}],
   ])

所有后端都暴露同样的五种操作：``upload_file``、``upload_dir``、
``download_file``、``delete_*``、``list_*``。如需构建自定义注册表，
``register_<backend>_ops(registry)`` 仍然是公开 API。

Google Drive
------------

.. code-block:: python

   from automation_file import driver_instance, drive_upload_to_drive

   driver_instance.later_init("token.json", "credentials.json")
   drive_upload_to_drive("example.txt")

OAuth 凭证以 UTF-8 写在调用方提供的 ``token_path``。
切勿打印或记录该文件内容。

SFTP
----

:class:`~automation_file.SFTPClient` 使用 :class:`paramiko.RejectPolicy`——
未知主机会被拒绝，而不是自动加入。请显式提供 ``known_hosts=`` 或依赖
``~/.ssh/known_hosts``。不要为图省事改用 ``AutoAddPolicy``。

跨后端复制
----------

跨后端调度器接受 URI 语法：

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_cross_copy",
        {"src": "s3://reports/2026-04.csv",
         "dst": "drive:///Backups/april.csv"}],
   ])

URI 前缀：``local://``、``s3://``、``drive://``、``sftp://``、
``azure://``、``dropbox://``、``ftp://``。
