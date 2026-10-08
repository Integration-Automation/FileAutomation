通用存储层
==========

``automation_file.storage`` 让每一种存储都使用同一套地址语法、同一组操作和同一组
异常。:class:`~automation_file.File` 与 :class:`~automation_file.Storage` 是应用层
API；:class:`~automation_file.StorageBackend` 则是后端需要实现的契约。

``FA_*`` 动作以及各后端原有的函数（``s3_upload_file``、``sftp_download_file`` ……）
完全不变，可以与本层同时使用。

.. note::

   本层是新功能，API 在 1.0 之前仍可能调整。目前内置本地文件系统、内存存储、
   S3 与 Azure Blob 四种后端。Google Drive、Dropbox、SFTP、FTP、WebDAV、SMB 与
   fsspec 在各自的适配器完成之前，仍通过已有的客户端与动作使用（见 :doc:`cloud`）；
   你也可以现在就自行编写后端，把它们接到本层之后（见 `编写后端`_）。

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
     - ``uri, expected, algorithm="sha256"``
     - ``true`` / ``false``
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
   Storage.schemes()                                  # ['azure', 'local', 'memory', 's3', 'sandbox', 'vault']

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

请用契约测试套件检查。``tests/storage_contract.py`` 包含 81 个用例——嵌套目录、
空文件与大文件、Unicode 路径、二进制数据、覆盖与路径不存在时的行为、路径规范化、
流、复制与移动——并在后端确实有差异之处读取 ``capabilities``：

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
