云与 SFTP 后端
==============

每个后端的动作都由
:func:`~automation_file.core.action_registry.build_default_registry` 注册，无论其
SDK 是否已安装。SDK 本身则由 extra 提供：``pip install "automation_file[s3]"``
（另有 ``azure``、``gdrive``、``dropbox``、``sftp``、``onedrive``、``box``、
``smb``、``fsspec``），或用 ``[all]`` 安装所有后端。使用缺少 extra 的后端时会抛出
``OptionalDependencyException``，信息中附有要执行的命令。SDK 就绪后，在单例上调用
``later_init`` 即可使用：

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

``FA_copy_between``（``copy_between(source, target)``）把一个文件从某个位置复制到
另一个位置，传输完成时返回 ``True``。它是 ``File(source).copy_to(target)`` 的旧写法，
建立在存储层之上（:doc:`storage`）：两个后端能直接互传时会采用原生复制，目标位置已有
的文件会被替换，而且这次操作会送达存储观察者与审计轨迹。

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_copy_between",
        {"source": "s3://reports/2026-04.csv",
         "target": "azure://backups/april.csv"}],
   ])

它接受：

* 任何存储 URI：``s3://bucket/key``、``azure://container/blob``（或 ``az://``）、
  ``gdrive:///path``、``onedrive:///path``、``dropbox:///path``、
  ``sftp://host/absolute/path``、``memory://name/path``，或挂载的前缀；
* 普通的文件系统路径、``local:<path>`` 或 ``local:/path``；
* 它一直以来接受的写法：``s3:bucket/key``、``azure:container/blob`` 与
  ``dropbox:/path``；
* 只有一个斜线或没有斜线的 ``sftp:/path`` 与 ``ftp:/path``，路径相对于会话登录时
  所在的目录，与以往相同。写成两个斜线（``sftp://host/path``）时，URI 指定的是主机
  与绝对路径，而且主机必须是会话实际连接的那一台；
* ``http://`` / ``https://`` 只能作为来源，通过经过验证的下载器获取（:doc:`transfer`）。

每个后端都必须先初始化（``s3_instance.later_init(...)`` 等）。传输本身失败时（来源不
存在、写入被拒、把文件复制到它自己）函数返回 ``False`` 并记录原因；无法理解的位置会
抛出 ``CrossBackendException``，尚未初始化的后端会抛出
``StorageUnavailableException``。

新的代码建议使用 ``FA_storage_copy``（:doc:`storage`）：它接受存储 URI，会报告复制的
结果，失败时抛出明确的异常，而不是返回 ``False``。
