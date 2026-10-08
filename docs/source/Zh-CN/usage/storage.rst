通用存储层
==========

``automation_file.storage`` 让每一种存储都使用同一套地址语法、同一组操作和同一组
异常。:class:`~automation_file.File` 与 :class:`~automation_file.Storage` 是应用层
API；:class:`~automation_file.StorageBackend` 则是后端需要实现的契约。

``FA_*`` 动作以及各后端原有的函数（``s3_upload_file``、``sftp_download_file`` ……）
完全不变，可以与本层同时使用。

.. note::

   本层是新功能，API 在 1.0 之前仍可能调整。目前内置十二种后端：本地文件系统、
   内存存储、S3、Azure Blob、Google Drive、Dropbox、OneDrive、SFTP、FTP / FTPS、
   WebDAV、SMB，以及 fsspec 能访问的任何存储。Box 没有适配器，只能通过它的
   ``FA_box_*`` 动作使用（见 :doc:`cloud`）。每个远端后端都需要安装对应的 extra
   （``pip install "automation_file[s3]"``）并初始化其客户端，详见 `内置后端`_
   中各自的条目。

快速开始
--------

.. code-block:: python

   from automation_file import File, Storage

   report = File("local:///data/reports/q1.csv")     # 也可以直接写 "reports/q1.csv"
   report.write("region,total\nEMEA,42\n")
   report.exists()                                    # True
   report.size                                        # 21
   report.read_text()
   report.checksum()                                  # Checksum("sha256", "…")
   report.verify("sha256:9f86d081…")                  # 常数时间比较

   archive = report.copy_to("memory://scratch/archive/q1.csv")
   report.move_to("local:///data/done/q1.csv")

   reports = Storage("local:///data/reports")
   for info in reports.list_dir(recursive=True):
       print(info.path, info.size, info.modified_at)
   reports.upload("q2.csv", "2026/q2.csv")
   reports.file("2026/q2.csv").download_to("copy-of-q2.csv")
   reports.delete("2026", recursive=True)

创建 ``File`` 或 ``Storage`` 对象不会触碰任何存储。每次调用时才查找后端，因此可以在
后端初始化或挂载之前先创建对象。

存储 URI
--------

.. code-block:: text

   <scheme>://<authority>/<path>

   local:///data/report.csv          s3://bucket/report.csv
   local:///C:/data/report.csv       azure://container/report.csv
   sftp://server/data/report.csv     dropbox:///reports/report.csv
   memory://scratch/report.csv       smb://server/share/report.csv

``scheme``
    决定使用哪个后端，一律转为小写。``file`` 是 ``local`` 的别名，``az`` 是
    ``azure`` 的别名。

``authority``
    后端找到自身根目录所需的信息：bucket、container 或主机名，保持原样。凭据
    不属于 URI，因此 ``user@host`` 与 ``user:password@host`` 会被拒绝，并且错误
    信息不会重复显示这些内容。

``path``
    按字面理解。不做百分号解码，``?`` 与 ``#`` 都是普通字符，所以
    ``s3://bucket/Q1 #3?.csv`` 指的就是那个 key。空段与 ``.`` 段会被丢弃；
    ``..`` 段视为错误，因此路径永远无法跳出它所拼接的根目录。

本地路径
    不含 ``://`` 的文本是文件系统路径，会先转换为绝对路径：``reports/a.csv``、
    ``/data/a.csv`` 与 ``C:\data\a.csv`` 都可以直接使用，:class:`pathlib.Path` 也
    一样。在 Windows 上，UNC 路径 ``\\server\share\a.csv`` 等同于
    ``local://server/share/a.csv``。

有歧义的文本
    ``sftp:/data/a.csv`` 可能是少写一个斜杠的 URI，也可能是名为 ``sftp:`` 的本地
    文件。这种写法会被拒绝，信息中会给出两种明确的写法：URI 写成 ``sftp://…``，
    本地文件写成 ``./sftp:/data/a.csv``。

:func:`~automation_file.parse_storage_uri` 返回不可变的
:class:`~automation_file.StorageURI`，具有 ``scheme``、``authority``、``path``、
``name``、``parent`` 与 ``joinpath()``。格式错误的输入会抛出
:class:`~automation_file.StorageURIException`。

操作
----

每个后端的方法都相同，``File`` 与 ``Storage`` 会转调它们。

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - 方法
     - 行为
   * - ``exists(path)``
     - 文件或目录存在时返回 ``True``。
   * - ``stat(path)``
     - 返回 :class:`~automation_file.FileInfo`。路径不存在时抛出
       ``StorageNotFoundException``。
   * - ``list_dir(path="", recursive=False)``
     - 按路径排序的条目。``recursive=True`` 返回所有后代条目，包含目录。对象是
       文件时抛出 ``StoragePathTypeException``。
   * - ``mkdir(path, parents=True, exist_ok=True)``
     - 创建目录。如果后端的目录只是由文件路径隐含而来，则不会创建任何东西，也不
       需要创建。
   * - ``upload(local_path, path, overwrite=True)``
     - 存入本地文件，并创建缺少的上级目录。``overwrite=False`` 时如果文件已存在，
       抛出 ``StorageAlreadyExistsException``。
   * - ``download(path, local_path, overwrite=True)``
     - 先写入同目录下的 ``.part`` 文件，完成后才替换目标，所以下载失败不会留下
       被截断的文件。
   * - ``delete(path, recursive=False, missing_ok=False)``
     - 目录内有条目时需要 ``recursive=True``（否则抛出
       ``StorageNotEmptyException``）。存储的根目录永远不会被删除。
   * - ``checksum(path, algorithm="sha256")``
     - 返回 :class:`~automation_file.Checksum`。支持 ``hashlib`` 中所有固定长度
       的算法：``sha256``、``sha512``、``blake2b``、``md5``（仅用于兼容，不用于
       安全目的）。
   * - ``read_bytes(path)`` / ``write_bytes(path, data)``
     - 读写整个文件的内容。
   * - ``open_read(path)`` / ``open_write(path, overwrite=True)``
     - 二进制文件对象，用于大到无法整个放进内存的内容。写入的内容在对象关闭时
       才会存入；如果因异常离开 ``with`` 块，则不会存入任何东西。
   * - ``copy_from(source, source_path, path)`` / ``move_from(…)``
     - 从任何后端（包含自己）传输。两个后端之间能直接完成时走原生方式（例如
       本地重命名），否则经由本地暂存文件。

``FileInfo`` 包含 ``path``、``name``、``is_dir``、``size``、``modified_at``（带
时区的 UTC 时间）、``etag``、``version``、``content_type`` 与 ``metadata``。后端
无法提供的字段为 ``None``。``FileInfo.to_dict()`` 与 ``Checksum.to_dict()`` 的结果
可以直接序列化为 JSON。

``backend.capabilities`` 是 :class:`~automation_file.StorageCapabilities`，说明后端
会填入哪些可选的 ``FileInfo`` 字段，以及它的目录是真实存在（``directories=True``，
文件系统）还是由文件路径隐含（``directories=False``，对象存储）。

动作
----

本层也可以从 JSON 动作列表使用，因此 CLI、TCP 与 HTTP 动作服务器以及 MCP 主机都能调用。
每个 ``FA_storage_*`` 动作都以字符串形式接收 URI，并返回可以序列化为 JSON 的值。

.. list-table::
   :header-rows: 1
   :widths: 28 40 32

   * - 动作
     - 参数
     - 返回值
   * - ``FA_storage_exists``
     - ``uri``
     - ``true`` / ``false``
   * - ``FA_storage_stat``
     - ``uri``
     - 文件信息
   * - ``FA_storage_list``
     - ``uri, recursive=False``
     - 文件信息的列表
   * - ``FA_storage_mkdir``
     - ``uri, parents=True, exist_ok=True``
     - ``True``
   * - ``FA_storage_upload``
     - ``local_path, uri, overwrite=True``
     - 文件信息
   * - ``FA_storage_download``
     - ``uri, local_path, overwrite=True``
     - 本地路径
   * - ``FA_storage_delete``
     - ``uri, recursive=False, missing_ok=False``
     - ``True``
   * - ``FA_storage_checksum``
     - ``uri, algorithm="sha256"``
     - ``{"algorithm": …, "value": …}``
   * - ``FA_storage_verify``
     - ``uri, expected, algorithm="sha256", strict=False``
     - ``true`` / ``false``；``strict=True`` 时，不匹配会抛出
       ``StorageChecksumException``
   * - ``FA_storage_copy``
     - ``source, target, overwrite=True``
     - 目标的文件信息
   * - ``FA_storage_move``
     - ``source, target, overwrite=True``
     - 目标的文件信息
   * - ``FA_storage_read_text``
     - ``uri, encoding="utf-8"``
     - 文本内容
   * - ``FA_storage_write_text``
     - ``uri, text, overwrite=True, encoding="utf-8"``
     - 文件信息
   * - ``FA_storage_copy_tree``
     - ``source, target, overwrite=True``
     - 摘要：``copied``、``skipped``、``deleted``、``errors``、``dry_run``
   * - ``FA_storage_sync``
     - ``source, target, delete=False, checksum=False, dry_run=False``
     - 摘要：``copied``、``skipped``、``deleted``、``errors``、``dry_run``
   * - ``FA_storage_schemes``
     - —
     - 已注册的 scheme

文件信息是 ``FileInfo.to_dict()`` 再加上 ``uri`` 键：``uri``、``path``、``name``、
``is_dir``、``size``、``modified_at``（ISO 8601）、``etag``、``version``、
``content_type`` 与 ``metadata``。在 ``FA_storage_list`` 中，每个 ``path`` 都相对于
被列出的 URI。失败时会抛出 `异常`_ 一节中的异常，执行器会把它记录在该动作上，
不会中断整份列表。

.. code-block:: json

   [
     ["FA_storage_copy", {"source": "s3://reports/2026/q1.csv",
                          "target": "local:///backup/2026/q1.csv"}],
     ["FA_storage_verify", {"uri": "local:///backup/2026/q1.csv",
                            "expected": "sha256:9f86d081884c7d65…"}],
     ["FA_storage_list", {"uri": "s3://reports/2026", "recursive": true}]
   ]

与其他文件动作一样，这些动作能访问进程所能访问的一切。在 TCP 或 HTTP 动作服务器上
请传入 :class:`~automation_file.ActionACL`，在 MCP 服务器上请使用
``--allowed-actions``，只开放客户端需要的动作。
:func:`~automation_file.register_storage_ops` 可以把它们加入你自己的注册表。

异常
----

全部派生自 :class:`~automation_file.StorageException`，而它本身是
``FileAutomationException`` 的子类。

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 异常
     - 抛出时机
   * - ``StorageURIException``
     - URI 或路径格式错误、有歧义，或没有后端能处理。
   * - ``StorageNotFoundException``
     - 路径或上传的本地源文件不存在。它同时是 ``FileNotExistsException``，所以
       已有的异常处理仍然有效。
   * - ``StorageAlreadyExistsException``
     - 写入会替换已有内容，而 ``overwrite`` / ``exist_ok`` 为关闭。
   * - ``StoragePathTypeException``
     - 对目录执行文件操作，或对文件执行目录操作。
   * - ``StorageNotEmptyException``
     - 删除内有条目的目录却没有指定 ``recursive=True``。
   * - ``StoragePermissionException``
     - 后端拒绝访问。
   * - ``StorageTransientException``
     - 值得重试的失败：超时、连接中断、被限流。可以作为 ``retry_on_transient`` 的
       ``retriable=`` 类型。
   * - ``StorageUnavailableException``
     - 后端尚未初始化，或其 SDK 未安装。
   * - ``StorageUnsupportedException``
     - 后端无法执行所要求的操作（未知的校验算法、删除根目录）。
   * - ``StorageChecksumException``
     - 严格验证（``FA_storage_verify`` 搭配 ``strict=True``）发现摘要与预期不同。

内置后端
--------

``LocalStorage``（``local://``，别名 ``file://``）
    ``LocalStorage()`` 覆盖整个文件系统，也就是 ``local:///…`` 解析的结果。
    ``LocalStorage(root)`` 则被限制在单个目录树内：每个路径都经过
    :func:`~automation_file.safe_join`，因此通过符号链接离开根目录的路径会抛出
    ``PathTraversalException``。只要路径来自进程之外，就应使用带根目录的实例。

    读写时会跟随符号链接；删除时绝不跟随：只移除链接本身，不动它指向的目标。
    递归列出时不会进入被链接的目录。写入会先写到同目录的临时文件，再以原子操作
    替换目标。

``MemoryStorage``（``memory://<name>/…``）
    保存在内存中的线程安全目录树，用于测试、试运行与示例。每个 ``<name>`` 是
    独立的存储，首次使用时创建。

``S3Storage``（``s3://<bucket>/<key>``）
    通过共用的 ``s3_instance`` 访问一个 bucket，初始化方式与以往相同：
    ``s3_instance.later_init(...)`` 或 ``FA_s3_later_init``。
    ``S3Storage(bucket, client=...)`` 可以改用另一个 boto3 客户端（其他账号、
    MinIO），``prefix=`` 则把后端限制在某个前缀之下的 key。上传时会按 key 的
    扩展名设置 ``ContentType``。``stat`` 报告大小、修改时间、ETag、内容类型、
    版本 ID 与元数据。共用同一个客户端的两个 S3 位置之间的复制由 S3 本身完成。

``AzureStorage``（``azure://<container>/<blob>``，别名 ``az://``）
    通过共用的 ``azure_blob_instance`` 访问一个 container
    （``azure_blob_instance.later_init(...)`` 或 ``FA_azure_blob_later_init``），
    或以 ``AzureStorage(container, service=...)`` 改用另一个
    ``BlobServiceClient``，例如 Azurite 模拟器。``prefix=`` 的用法与 S3 相同，
    ``stat`` 报告的字段也相同。

S3 与 Azure Blob 都是对象存储。目录只在其下还有 key 时才存在，因此 ``mkdir`` 不会
创建任何东西，空目录也无法存在（``capabilities.directories`` 为 ``False``）。其他
工具写入、以 ``/`` 结尾的文件夹占位 key 会显示为目录，绝不会显示为文件。校验码是
由内容计算而来，不取自 ETag，因为分段上传的 ETag 并不是摘要。客户端尚未初始化时，
每个调用都会抛出 ``StorageUnavailableException``。

.. code-block:: python

   from automation_file import File, azure_blob_instance, s3_instance

   s3_instance.later_init(region_name="us-east-1")
   azure_blob_instance.later_init(connection_string=connection_string)
   File("s3://reports/2026/q1.csv").copy_to("azure://backups/2026/q1.csv")

``SFTPStorage``（``sftp://<host>[:<port>]/<绝对路径>``）
    通过共用的 ``sftp_instance`` 访问一个 SFTP 会话所能到达的文件。打开会话的方式与
    以往相同：``sftp_instance.later_init(host=..., username=..., ...)`` 或
    ``FA_sftp_later_init``；主机密钥会与 ``known_hosts`` 比对，未知的主机一律拒绝。
    URI 的路径就是服务器上的绝对路径，因此 ``sftp://nas/data/q1.csv`` 指的是
    ``/data/q1.csv``，而不是登录目录之下的路径。

    主机可以省略（``sftp:///data/q1.csv``），代表“已打开的会话”。如果写出主机，
    它必须是会话所连接的那一台；比对时不区分大小写，如果同时写了端口，端口也必须
    一致。其他主机会抛出 ``StorageURIException``。要访问第二台主机，请另外连接一个
    ``SFTPClient`` 并为它挂载后端：
    ``Storage.mount("sftp://backup", SFTPStorage(client))``。
    ``SFTPStorage(client, root="/srv/data")`` 会把每个路径都接在某个远程目录之下。
    ``root`` 只是路径前缀，并不是隔离环境：服务器上的符号链接仍可能通往它之外。

    ``stat`` 报告服务器返回的大小与修改时间（UTC，精确到秒）。同一个会话内的移动
    是一次重命名；复制则经由本地临时文件，因为 SFTP 本身没有复制功能。

    读写时会跟随符号链接；删除时绝不跟随：只移除链接本身，不动它指向的目标。
    递归列出时不会进入被链接的目录。目标已不存在的链接仍会被列出，但 ``exists``
    与 ``stat`` 会报告它不存在。

``FTPStorage``（``ftp://<host>[:<port>]/<绝对路径>``、``ftps://…``）
    通过共用的 ``ftp_instance`` 访问一个 FTP 或 FTPS 会话所能到达的文件。打开会话的
    方式与以往相同：
    ``ftp_instance.later_init(host=..., username=..., password=..., tls=True)`` 或
    ``FA_ftp_later_init``。主机规则、``root=`` 与绝对路径都和 ``SFTPStorage``
    相同；要访问第二台主机，请用另一个已连接的 ``FTPClient`` 挂载
    ``FTPStorage(client)``。除非已打开的会话是以 ``tls=True`` 建立的，否则
    ``ftps://`` 会以 ``StorageURIException`` 拒绝；``ftp://`` 则两种会话都接受。
    未加密的 FTP 会以明文传送密码与文件内容。

    服务器如果提供 ``MLST`` / ``MLSD``（RFC 3659），``stat`` 会按服务器的 fact 报告
    类型、大小与修改时间（UTC）。其他服务器则以探测的方式判断：``CWD`` 进得去的是
    目录，``SIZE`` 与 ``MDTM`` 有应答的是文件，列出目录则是 ``NLST`` 再加上每个名称
    最多三条命令。这种方式比较慢，目录没有修改时间，而且服务器不在 ``NLST`` 中显示
    的文件（通常是名称以点开头的文件）不会被列出。每次探测后都会把会话的工作目录
    切回原处。

    FTP 对“没有这个文件”与“不允许”使用同一个应答码 550。``exists``、``stat``
    与列出目录会把它视为“不存在”；上传、下载与删除则把它视为
    ``StoragePermissionException``。含有换行符的路径会以 ``StorageURIException``
    拒绝。

    不论哪一种服务器，删除时都绝不跟随符号链接。列出时则视服务器而定：``MLSD``
    会标示链接的服务器，链接会列为文件且不会被进入；以探测方式处理的服务器则把
    指向目录的链接显示为目录，递归列出时会进入其中。

SFTP 与 FTP 都有真正的目录（``capabilities.directories`` 为 ``True``）：``mkdir``
会创建目录，空目录也可以存在。两者都不报告 ETag、版本、内容类型与元数据，校验码
则由下载回来的内容计算。上传时会先写入目标旁边的隐藏 ``.part`` 文件，再重命名覆盖
目标，因此失败的上传绝不会留下被截断的文件。如果服务器不允许重命名到已存在的文件
之上（没有 ``posix-rename@openssh.com`` 扩展的 SFTP、Windows 上的 FTP），会先把该
文件移到一旁，完成后再删除，如果重命名仍然失败则放回原处；这种替换方式不是原子
操作。

一个会话一次只能执行一个操作，因此同一个会话上的调用会互相等待。
``FA_sftp_*`` / ``FA_ftp_*`` 动作不受这个机制保护：其他线程正通过存储层使用某个
会话时，不要同时对它执行这些动作。在调用 ``later_init`` 之前，每个调用都会抛出
``StorageUnavailableException``。连接中断或超时会抛出
``StorageTransientException``；存储层不会自动重新连接，重试之前请再调用一次
``later_init``。

.. code-block:: python

   from automation_file import (
       File, SFTPClient, SFTPStorage, Storage, ftp_instance, sftp_instance,
   )

   sftp_instance.later_init(host="nas.example", username="ops",
                            key_filename="/home/ops/.ssh/id_ed25519")
   ftp_instance.later_init(host="files.example", username="ops",
                           password=password, tls=True)

   File("sftp://nas.example/exports/q1.csv").copy_to("ftps://files.example/incoming/q1.csv")
   File("sftp:///exports/q1.csv").move_to("sftp:///archive/2026/q1.csv")   # 一次重命名

   # 第二台主机：使用自己的客户端，挂载在自己的 authority 之下。
   backup = SFTPClient()
   backup.later_init(host="backup.example", username="ops")
   Storage.mount("sftp://backup.example", SFTPStorage(backup, root="/srv/backups"))
   File("sftp:///archive/2026/q1.csv").copy_to("sftp://backup.example/2026/q1.csv")

``DropboxStorage``（``dropbox:///<path>``）
    通过共用的 ``dropbox_instance`` 访问 Dropbox，初始化方式与以往相同：
    ``dropbox_instance.later_init(token)`` 或 ``FA_dropbox_later_init``。authority
    必须留空：``dropbox:///reports/q1.csv`` 就是文件 ``/reports/q1.csv``，而
    ``dropbox://reports/q1.csv`` 会被拒绝，并在错误信息中给出正确写法。
    ``DropboxStorage(client)`` 可以改用另一个 ``dropbox.Dropbox`` 客户端，``root=``
    则把后端限制在某个文件夹内；这样的实例要挂载后才有 URI。文件夹是真正的目录。

    ``stat`` 报告大小、服务器端的修改时间，并以修订版本（rev）作为 ``version``、
    以 Dropbox 的内容哈希作为 ``etag``。超过 8 MiB 的文件会通过上传会话、每次
    8 MiB 分段上传，因此不会整个读入内存。同一个客户端内两个路径之间的复制与
    移动由 Dropbox 本身完成，删除文件夹只需要一次请求。

    Dropbox 比较名称时不区分大小写。复制或移动时它不会替换已有文件，因此会先删除
    已存在的目标，这一步并非原子操作。客户端尚未初始化时，每个调用都会抛出
    ``StorageUnavailableException``。

``WebDAVStorage``（以挂载方式使用，例如挂在 ``webdav://<host>``）
    通过 :class:`~automation_file.WebDAVClient` 访问 WebDAV 服务器。基础 URL 与
    凭据都在客户端上，因此没有任何 URI 能自行解析：请把后端挂载到文件应该出现的
    位置。``root=`` 把后端限制在基础 URL 之下的某个集合（collection）内。集合是
    真正的目录。

    ``stat`` 是一次 ``Depth: 0`` 的 ``PROPFIND``，报告服务器提供的大小、修改时间
    （``getlastmodified``）、``getetag`` 与 ``getcontenttype``。同一个客户端内两个
    路径之间的复制与移动由服务器以 ``COPY`` 与 ``MOVE`` 完成；不支持这两个方法的
    服务器则改经本地暂存文件传输。删除目录只需要一次 ``DELETE``。HTTP 404 会抛出
    ``StorageNotFoundException``，401 与 403 抛出 ``StoragePermissionException``，
    408、429、5xx 与连接中断则抛出 ``StorageTransientException``。

    基础 URL 会经过 ``WebDAVClient`` 的 SSRF 检查（服务器位于私有网络时请传入
    ``allow_private_hosts=True``），而且默认会验证 TLS。路径不能以空白字符结尾。
    客户端由调用方负责关闭。

``SMBStorage``（以挂载方式使用，例如挂在 ``smb://<server>/<share>``）
    通过 :class:`~automation_file.SMBClient` 访问一个 SMB / CIFS 共享；服务器、
    共享名称与凭据都在客户端上。需要安装 ``smbprotocol``
    （``pip install smbprotocol``），未安装时每个调用都会抛出
    ``StorageUnavailableException``。请把后端挂载到文件应该出现的位置。``root=``
    把后端限制在共享内的某个目录。目录是真正的目录。

    ``stat`` 报告大小与修改时间。同一个客户端内两个路径之间的移动是服务器上的
    重命名；复制则经由本地暂存文件。``/`` 与 ``\`` 都是路径分隔符，不论用哪一种
    写法，``..`` 段都会被拒绝。客户端由调用方负责关闭。

``FsspecStorage``（可以挂载在任何 scheme 之下）
    把任何 `fsspec <https://filesystem-spec.readthedocs.io>`_ 文件系统（Google
    Cloud Storage、HDFS、FTP、压缩包……）放到存储契约之后。需要安装 ``fsspec`` 与
    该服务的驱动（``gcsfs``、``adlfs`` ……），缺少时会抛出
    ``StorageUnavailableException``。
    ``FsspecStorage(filesystem, root=..., scheme=..., directories=...)`` 包装一个
    文件系统对象；
    ``FsspecStorage.from_url(url, directories=..., **storage_options)`` 则由 fsspec
    URL 创建，URL 的路径会成为根目录。请用你选择的 scheme 挂载这个后端。

    ``directories`` 表示文件系统是否保留没有任何文件的目录。真正的文件系统保持
    ``True``；对象存储的目录只是 key 的前缀，请传入 ``False``。``stat`` 报告大小，
    并在文件系统提供时报告修改时间：``capabilities.modified_at`` 说明是否可以
    期待这个字段，而列出目录时只有在文件系统的列表本身带有时间时才会报告。同一个
    文件系统对象内的复制与移动由文件系统本身完成。

    路径一律按字面解读：名称中含有 ``*``、``?`` 或 ``[`` 时绝不会被当成通配符
    展开。fsspec 不在 SSRF 检查的范围内，因此后端应由配置创建，绝不要由请求输入
    创建。本地目录请使用 ``LocalStorage(root)``，它还能阻止符号链接离开根目录。

.. code-block:: python

   from automation_file import (
       DropboxStorage, File, FsspecStorage, SMBClient, SMBStorage, Storage,
       WebDAVClient, WebDAVStorage, dropbox_instance,
   )

   dropbox_instance.later_init(token)
   File("dropbox:///reports/q1.csv").copy_to("local:///backup/q1.csv")
   Storage.mount("dropbox://team", DropboxStorage(root="team/shared"))

   dav = WebDAVClient("https://files.example.com/remote.php/dav", "user", password)
   Storage.mount("webdav://files.example.com", WebDAVStorage(dav))

   nas = SMBClient("nas.example.com", "projects", "user", password)
   Storage.mount("smb://nas.example.com/projects", SMBStorage(nas, root="2026"))

   Storage.mount("gcs://reports", FsspecStorage.from_url("gcs://reports", directories=False))

   File("webdav://files.example.com/reports/q1.csv").copy_to("gcs://reports/2026/q1.csv")

``GoogleDriveStorage``（``gdrive://<root>/<path>``）
    通过共用的 ``driver_instance`` 访问“我的云端硬盘”，初始化方式与以往相同：
    ``driver_instance.later_init(token_path, credentials_path)`` 或
    ``FA_drive_later_init``。URI 的 authority 是作为根目录的文件夹 ID，留空或
    写成 ``root`` 则代表“我的云端硬盘”：``gdrive:///reports/q1.csv``、
    ``gdrive://<folder-id>/q1.csv``。在代码中即
    ``GoogleDriveStorage(root_id="<folder-id>")``；共享云端硬盘的 ID 也可以，
    ``GoogleDriveStorage(client)`` 则可以改用另一个 ``GoogleDriveClient``。

    Drive 以 ID 而非路径来寻址，因此每次调用都会逐层文件夹查找路径，调用之间
    不保留任何结果。名称采用完全匹配：``Report.txt`` 与 ``report.txt`` 是两个
    条目。Drive 也允许同一个文件夹内有多个同名条目；这样的路径无法指向单个
    条目，因此对它的每个调用都会抛出 ``StorageException``，并说明有几个条目
    共用该名称，绝不会从中挑选一个。列出目录时仍会显示每一个同名条目。名称
    含有 ``/`` 的条目同样无法写成路径，列出时会略过它，并在日志中留下警告。
    回收站中的条目对这个后端而言并不存在。

    文件夹是真实的目录。写入已有文件的路径时，会上传该文件的新修订版本，因此
    文件的 ID、链接与共享设置都会保留；复制或移动到已有文件上也是如此。在同一
    个客户端之内复制或移动到新路径时由 Drive 本身完成，移动会保留 ID。
    ``delete`` 是永久删除，不经过回收站，文件夹会连同其中所有内容一并删除。

    Google 文档、表格、幻灯片以及其他 ``application/vnd.google-apps.*`` 类型
    没有二进制内容。它们在列出时 ``size=None``，可以复制、移动与删除，但
    ``download``、``read_bytes`` 与 ``checksum`` 会抛出
    ``StorageUnsupportedException``，也不能用文件覆盖它们。不会导出为其他
    格式，也不会跟随快捷方式。

    ``stat`` 报告大小、修改时间、作为 ETag 的 Drive MD5、版本号与 MIME 类型。
    ``checksum`` 对 MD5、SHA-1 与 SHA-256 直接返回 Drive 为该文件保存的值，
    无需下载；其他算法则由内容计算。

    限制：路径的每一层都要一次请求；而且 Drive 不保证名称唯一，两个写入者若
    同时创建同一个新路径，会留下两个同名条目。

``OneDriveStorage``（``onedrive:///<path>``）
    通过共用的 ``onedrive_instance`` 访问已登录用户的 OneDrive，初始化方式
    与以往相同：``onedrive_instance.later_init(access_token)``、
    ``onedrive_instance.device_code_login(client_id)`` 或对应的
    ``FA_onedrive_*`` 动作。URI 的 authority 一律留空：
    ``onedrive:///reports/q1.csv``。在该位置写了东西
    （``onedrive://reports/q1.csv``）会被拒绝，并提示正确写法。
    ``OneDriveStorage(root="backups/2026")`` 把后端限制在某个文件夹内，该
    文件夹必须已经存在；``OneDriveStorage(client)`` 则可以改用另一个
    ``OneDriveClient``。

    文件夹是真实的目录。OneDrive 比较名称时不区分大小写，但会保留写入时的
    大小写，因此 ``Report.txt`` 与 ``report.txt`` 是同一个条目，名称在所属
    文件夹内是唯一的。名称含有 OneDrive 禁用的字符（``" * : < > ? \ |``）时会
    被服务拒绝，并抛出 ``StorageException``。

    4 MiB 以内的文件以单个请求上传。更大的文件通过上传会话，以 10 MiB 的
    分段边读边发；下载则以流式写入磁盘，因此两者都不会把整个文件放进内存。
    写入已有文件的路径时会替换其内容并保留该条目；复制或移动到已有文件上也是
    如此。在同一个客户端之内移动到新路径时由 OneDrive 本身完成，复制则经过
    本地临时文件。``delete`` 会把条目送进回收站，文件夹会连同其中所有内容
    一并送入。

    ``stat`` 报告大小、修改时间、ETag 与 MIME 类型，没有版本。校验码由内容
    计算。

    限制：只能访问已登录用户自己的云端硬盘；而且客户端不会刷新访问令牌，
    令牌过期后每个调用都会抛出 ``StoragePermissionException``，直到安装新的
    令牌为止。

Google Drive 与 OneDrive 都有真实的目录，因此 ``mkdir`` 会创建文件夹，空目录
也可以存在（``capabilities.directories`` 为 ``True``）。两个服务都会限流：收到
限流响应、服务器错误或连接中断时会抛出 ``StorageTransientException``，可以交给
``retry_on_transient`` 重试。客户端尚未初始化时，每个调用都会抛出
``StorageUnavailableException``。

.. code-block:: python

   from automation_file import File, driver_instance, onedrive_instance

   driver_instance.later_init("token.json", "credentials.json")
   onedrive_instance.later_init(access_token)
   File("gdrive:///reports/2026/q1.csv").copy_to("onedrive:///backups/2026/q1.csv")

流与目录树
----------

``File.open_read()`` 与 ``File.open_write()`` 返回二进制文件对象，
``File.iter_chunks()`` 则逐块产出内容。本地后端直接就地读取；其他后端提供一份
暂存的本地副本，对象关闭时即移除，因此两种情况下内存用量都有上限。

``Storage.copy_to(target)`` 会把目录下的每个文件复制到 ``target`` 之下相同的相对
路径，后端不限。``Storage.sync_to(target)`` 只复制有变动的部分：目标缺少的文件、
大小不同的文件，或来源版本较新的文件。``checksum=True`` 改为比较 SHA-256 摘要而非
时间，代价是两边都要读取一次。``delete=True`` 还会移除来源没有的条目，
``dry_run=True`` 只报告会发生什么而不做任何更改。两者都返回 ``TreeResult``，包含
``copied``、``skipped``、``deleted`` 与 ``errors``；失败的文件会记在 ``errors``
中，其余文件照常处理。

.. code-block:: python

   from automation_file import File, Storage

   with File("s3://logs/2026/big.log").open_read() as stream:
       for line in stream:
           ...

   with File("local:///exports/report.csv").open_write() as stream:
       stream.write(b"region,total\n")

   reports = Storage("s3://reports/2026")
   reports.copy_to("local:///backup/2026")                     # every file, any backend
   result = reports.sync_to("azure://backups/2026", delete=True, dry_run=True)
   result.copied, result.skipped, result.deleted, result.errors

挂载与注册后端
--------------

URI 的解析分两步。**挂载** 优先：挂载把一个后端实例绑定到某个 URI，位于该 URI
或其下的所有 URI 都交给这个后端，并去掉挂载点本身的路径；匹配的挂载中最长者
优先。没有任何挂载认领的 URI 则交给 **scheme 工厂**。

.. code-block:: python

   from automation_file import File, LocalStorage, Storage

   # 为某个目录树取一个自己的名称。通过 sandbox://jobs/… 访问的任何东西都离不开
   # /srv/jobs，即使经由符号链接也一样。
   Storage.mount("sandbox://jobs", LocalStorage("/srv/jobs"))
   File("sandbox://jobs/42/out.csv").write(b"done")   # /srv/jobs/42/out.csv

   # 整个 scheme：工厂收到解析后的 URI，返回 (backend, path)。
   Storage.register_scheme("vault", lambda uri: (vault_backend(uri.authority), uri.path))

   Storage.resolve("sandbox://jobs/42/out.csv")       # (LocalStorage('/srv/jobs'), '42/out.csv')
   Storage.schemes()                                  # ['azure', 'dropbox', 'ftp', 'ftps', 'gdrive', 'local', 'memory',
                                                      #  'onedrive', 's3', 'sandbox', 'sftp', 'vault']

``Storage.mount`` / ``unmount`` / ``register_scheme`` / ``schemes`` / ``resolve``
操作的是整个进程共用的表。需要私有的表时使用
:class:`~automation_file.StorageResolver`，并以 ``resolver=`` 传给 ``File`` 与
``Storage``。

挂载是按 URI 的文本匹配。因此把带根目录的后端挂在某个 ``local://`` 路径上，只会
路由该路径的那一种写法；同一个目录的另一种写法（例如指向它的符号链接）仍然会
连到整个文件系统。要限制不受信任的路径，请像上面那样给带根目录的后端一个专属的
scheme 或 authority，并且只接受其下的 URI。

编写后端
--------

继承 :class:`~automation_file.StorageBackend` 并实现基本操作即可。上述公开方法
都由基类提供：它们会规范化路径、检查已有内容、抛出共用的异常并创建上级目录。

.. code-block:: python

   from automation_file import FileInfo, StorageBackend, StorageCapabilities

   class VaultStorage(StorageBackend):
       scheme = "vault"
       capabilities = StorageCapabilities(directories=False, etag=True)

       def _stat(self, path): ...          # FileInfo；不存在时返回 None；"" 是根目录
       def _list_dir(self, path): ...      # 目录的直接子条目
       def _upload(self, source, path): ...
       def _download(self, path, target): ...
       def _delete_file(self, path): ...
       # 目录真实存在时（capabilities.directories=True）还需要：
       #   _mkdir(path)、_rmdir(path)
       # 可选择重写：_walk、_copy_from、_move_from、_checksum、_read_bytes

如果是对象存储，请改为继承 :class:`~automation_file.ObjectStorage`，并实现
``_head``、``_scan``、``_put``、``_get`` 与 ``_remove``。它提供 `内置后端`_ 一节
所述的目录行为，``S3Storage`` 与 ``AzureStorage`` 都建立在它之上。

请用契约测试套件检查。``tests/storage_contract.py`` 包含 88 个用例——嵌套目录、
空文件与大文件、Unicode 路径、二进制数据、覆盖与路径不存在时的行为、路径规范化、
流、复制与移动，以及后端声明会填入的 ``FileInfo`` 字段——并在后端确实有差异之处读取
``capabilities``。后端没有声明的字段必须不存在，因此这些标志所承诺的不会比 ``stat``
实际给出的多，也不会少：

.. code-block:: python

   import pytest
   from tests.storage_contract import StorageContract

   class TestVaultStorageContract(StorageContract):
       @pytest.fixture
       def backend(self):
           return VaultStorage(...)        # 每个测试都要是空的存储

       @pytest.fixture
       def break_storage(self, backend):
           def fail(kind, times=1):          # kind: "denied" or "transient"
               backend.client.fail_next(kind, times)
           return fail

四个失败用例（访问被拒、暂时性失败、重试后成功、被拒的调用不会重试）需要
``break_storage`` fixture，它会让接下来对服务的调用失败。没有它时，这四个用例会跳过，
其余用例照常运行。
