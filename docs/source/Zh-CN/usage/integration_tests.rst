集成测试
========

单元测试为每个存储后端准备了服务的替身。集成测试则把同一套契约测试
（``tests/storage_contract.py``，81 个用例）拿去对真正的服务运行：S3 用 MinIO、
Azure Blob 用 Azurite、SFTP 用 OpenSSH 服务器，另外还有 FTP、WebDAV 与 Samba 服务器。
这些测试放在 ``tests/integration/``。

除非你把它们指向某个服务，否则它们会被跳过，因此不论有没有这些测试，
``python -m pytest tests/`` 的行为都一样。

在本地运行其中一个
------------------

安装 Docker 之后，用一个脚本就能在容器中启动服务，并打印出该测试模块要读取的变量：

.. code-block:: bash

   eval "$(bash tests/integration/start_service.sh s3)"
   python -m pytest tests/integration/test_s3_minio.py -v
   docker rm -f fa-it-s3

参数可以是 ``s3``、``azure``、``sftp``、``ftp``、``webdav`` 或 ``smb``。脚本会为这一次
运行生成密码或密钥，不会存储任何东西。如果要对你自己的服务测试，请改为自行设置这些变量。

变量
----

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 模块
     - 变量
   * - ``test_s3_minio.py``
     - ``FA_IT_S3_ENDPOINT``、``FA_IT_S3_ACCESS_KEY``、``FA_IT_S3_SECRET_KEY``；
       可选 ``FA_IT_S3_REGION``（``us-east-1``）
   * - ``test_azure_azurite.py``
     - ``FA_IT_AZURE_CONNECTION_STRING``
   * - ``test_sftp_openssh.py``
     - ``FA_IT_SFTP_HOST``、``FA_IT_SFTP_USER``、``FA_IT_SFTP_PASSWORD``、
       ``FA_IT_SFTP_KNOWN_HOSTS``（内含服务器主机密钥的文件；未知的主机会被拒绝）；
       可选 ``FA_IT_SFTP_PORT``（``22``）、``FA_IT_SFTP_ROOT``（``/upload``）
   * - ``test_ftp_server.py``
     - ``FA_IT_FTP_HOST``、``FA_IT_FTP_USER``、``FA_IT_FTP_PASSWORD``；可选
       ``FA_IT_FTP_PORT``（``21``）、``FA_IT_FTP_ROOT``（``/``）、``FA_IT_FTP_TLS``
       （``1`` 代表 FTPS）
   * - ``test_webdav_server.py``
     - ``FA_IT_WEBDAV_URL``、``FA_IT_WEBDAV_USER``、``FA_IT_WEBDAV_PASSWORD``
   * - ``test_smb_samba.py``
     - ``FA_IT_SMB_SERVER``、``FA_IT_SMB_SHARE``、``FA_IT_SMB_USER``、
       ``FA_IT_SMB_PASSWORD``；可选 ``FA_IT_SMB_PORT``（``445``）、
       ``FA_IT_SMB_ENCRYPT``（``1``）

第一个变量没有设置的模块会被跳过。设置 ``FA_IT_REQUIRED=1`` 时则改为失败，CI 就是用
这个方式确保作业不是靠着跳过所有测试而通过。

每个测试都在自己专属、名称随机的 bucket、container 或目录中运行，结束后会把它删除。
即使如此，仍请把测试指向一个你承担得起写入的账号。

在 CI 中
--------

``.github/workflows/integration.yml`` 会在每个 pull request、每次推送到 ``dev``、每晚
以及手动触发时运行。其中的 ``services`` 作业会用同一个脚本，为矩阵中的每个条目启动一个
服务，并运行该服务的模块。``platforms`` 作业则在 Linux 与 macOS 上运行单元测试；
Windows 由主要流程的 ``pytest`` 作业负责。两者都不会阻挡发布。

Google Drive、OneDrive 与 Dropbox 没有模拟器，因此只由它们的替身覆盖。如果要对真正的
服务检查其中之一，请按同样的模式编写模块：先检查变量，再写一个 ``StorageContract``
子类，让它的 ``backend`` fixture 产生以某个临时文件夹为根目录的适配器。

新增后端
--------

新的后端会附上一个针对替身的契约类（:doc:`storage` 的“编写后端”），而且只要它的
服务能在容器中运行，就会在这里附上一个模块，并在脚本与流程矩阵中各加上一个条目。

出现问题时
----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 你看到的
     - 代表什么、该怎么做
   * - ``SKIPPED … set FA_IT_S3_ENDPOINT to run against an S3 service``
     - 这个模块的变量没有设置。请用脚本启动服务，或自行设置变量。
   * - ``FA_IT_REQUIRED is set, but FA_IT_… is not``
     - 当前是 CI 模式，而服务没有启动，或没有导出它的变量。请查看“Start the service”
       步骤，以及失败后打印的服务日志。
   * - ``nothing is listening on 127.0.0.1:<port>``
     - 容器在 90 秒内没有启动完成。脚本会打印 ``docker ps -a`` 与该容器的日志。
   * - 每个测试都出现 ``StorageUnavailableException``
     - 服务连得上，但拒绝了凭据；或者对 SFTP 而言，它的主机密钥不在 known-hosts 文件中。
