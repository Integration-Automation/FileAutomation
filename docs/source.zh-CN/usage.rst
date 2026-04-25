使用指南
========

JSON 动作列表
-------------

动作可采用三种形状之一：

.. code-block:: json

   ["FA_name"]
   ["FA_name", {"kwarg": "value"}]
   ["FA_name", ["positional", "args"]]

动作列表是动作的数组。执行器按顺序执行并返回
``"execute[<index>]: <action>" -> result | repr(error)`` 的映射表。

.. code-block:: python

   from automation_file import execute_action, read_action_json

   results = execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir", {"dir_we_want_to_zip": "build", "zip_name": "build_snapshot"}],
   ])

   # 或从文件读入：
   results = execute_action(read_action_json("actions.json"))

校验、dry-run、并行执行
-----------------------

.. code-block:: python

   from automation_file import (
       execute_action, execute_action_parallel, validate_action,
   )

   # Fail-fast 校验：若有未知名称，执行前即中止整批。
   execute_action(actions, validate_first=True)

   # Dry-run：记录将调用什么但不实际调用。
   execute_action(actions, dry_run=True)

   # 并行：通过线程池执行彼此独立的动作。
   execute_action_parallel(actions, max_workers=4)

   # 手动校验——返回已解析的名称列表。
   names = validate_action(actions)

CLI
---

执行 JSON 动作列表的旧式参数::

   python -m automation_file --execute_file actions.json
   python -m automation_file --execute_dir ./actions/
   python -m automation_file --execute_str '[["FA_create_dir",{"dir_path":"x"}]]'
   python -m automation_file --create_project ./my_project

一次性操作的子命令::

   python -m automation_file ui
   python -m automation_file zip ./src out.zip --dir
   python -m automation_file unzip out.zip ./restored
   python -m automation_file download https://example.com/file.bin file.bin
   python -m automation_file create-file hello.txt --content "hi"
   python -m automation_file server --host 127.0.0.1 --port 9943
   python -m automation_file http-server --host 127.0.0.1 --port 9944
   python -m automation_file drive-upload my.txt --token token.json --credentials creds.json

Google Drive
------------

.. code-block:: python

   from automation_file import driver_instance, drive_upload_to_drive

   driver_instance.later_init("token.json", "credentials.json")
   drive_upload_to_drive("example.txt")

TCP 动作服务器
--------------

.. code-block:: python

   from automation_file import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(
       host="localhost", port=9943, shared_secret="optional-secret",
   )
   # 稍后：
   server.shutdown()
   server.server_close()

设置 ``shared_secret`` 后，客户端必须在 JSON 动作列表之前加上
``AUTH <secret>\\n`` 前缀。服务器默认仍绑定 loopback，除非显式传入
``allow_non_loopback=True``，否则拒绝非 loopback 绑定。

HTTP 动作服务器
---------------

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(
       host="127.0.0.1", port=9944, shared_secret="optional-secret",
   )

   # 客户端：
   # curl -H 'Authorization: Bearer optional-secret' \
   #      -d '[["FA_create_dir",{"dir_path":"x"}]]' \
   #      http://127.0.0.1:9944/actions

HTTP 响应为 JSON。设置 ``shared_secret`` 后，客户端必须发送
``Authorization: Bearer <secret>``。

可靠性
------

对自定义的可调用对象应用重试：

.. code-block:: python

   from automation_file import retry_on_transient

   @retry_on_transient(max_attempts=5, backoff_base=0.5)
   def flaky_network_call(): ...

对单个动作应用配额限制：

.. code-block:: python

   from automation_file import Quota

   quota = Quota(max_bytes=50 * 1024 * 1024, max_seconds=30.0)
   with quota.time_budget("bulk-upload"):
       bulk_upload_work()

路径安全
--------

.. code-block:: python

   from automation_file import safe_join

   target = safe_join("/data/jobs", user_supplied_path)
   # -> 若解析后的路径逃出 /data/jobs，会抛出 PathTraversalException。

云端 / SFTP 后端
----------------

每个后端（S3、Azure Blob、Dropbox、SFTP）都随 ``automation_file`` 一并打包，
并由 :func:`~automation_file.core.action_registry.build_default_registry`
自动注册。不需要额外安装步骤——对单例调用 ``later_init`` 即可：

.. code-block:: python

   from automation_file import execute_action, s3_instance

   s3_instance.later_init(region_name="us-east-1")

   execute_action([
       ["FA_s3_upload_file", {"local_path": "report.csv", "bucket": "reports", "key": "report.csv"}],
   ])

所有后端都提供相同的五个操作：
``upload_file``、``upload_dir``、``download_file``、``delete_*``、``list_*``。
``register_<backend>_ops(registry)`` 依然公开，供自行建立注册表的调用方使用。

SFTP 特别使用 :class:`paramiko.RejectPolicy`——未知主机会被拒绝而非自动添加。
请显式提供 ``known_hosts``，或依赖 ``~/.ssh/known_hosts``。

文件监视触发器
--------------

当被监视路径发生文件系统事件时执行动作列表。模块级的
:data:`~automation_file.trigger.trigger_manager` 以名称为键维护一组活动
watcher，让 JSON 接口与 GUI 共享同一个生命周期。

.. code-block:: python

   from automation_file import watch_start, watch_stop

   watch_start(
       name="inbox-sweeper",
       path="/data/inbox",
       action_list=[["FA_copy_all_file_to_dir", {"source_dir": "/data/inbox",
                                                 "target_dir": "/data/processed"}]],
       events=["created", "modified"],
       recursive=False,
   )
   # 稍后：
   watch_stop("inbox-sweeper")

也可以通过 JSON 动作列表以 ``FA_watch_start`` / ``FA_watch_stop`` /
``FA_watch_stop_all`` / ``FA_watch_list`` 操作。

Cron 调度器
-----------

按周期性调度执行动作列表。5 字段 cron 解析器支持 ``*``、精确值、``a-b``
范围、逗号分隔列表与 ``*/n`` 步进语法，并能使用 ``jan``..``dec`` /
``sun``..``sat`` 别名。

.. code-block:: python

   from automation_file import schedule_add

   schedule_add(
       name="nightly-snapshot",
       cron_expression="0 2 * * *",           # 每日本地时间 02:00
       action_list=[["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                                    "zip_name": "/backup/data_nightly"}]],
   )

后台线程在分钟边界唤醒，因此不支持秒级精度的表达式。可通过 JSON 使用
``FA_schedule_add`` / ``FA_schedule_remove`` / ``FA_schedule_remove_all`` /
``FA_schedule_list``。

传输进度与取消
--------------

对 :func:`download_file`、:func:`s3_upload_file` 或 :func:`s3_download_file`
传入 ``progress_name="<label>"`` 即可把传输注册到共享进度注册表。GUI
的 **Progress** 标签页每半秒轮询注册表；``FA_progress_list``、
``FA_progress_cancel`` 与 ``FA_progress_clear`` 让 JSON 动作列表取得同样的视图。

.. code-block:: python

   from automation_file import download_file, progress_cancel

   # 一个线程：
   download_file("https://example.com/big.bin", "big.bin",
                 progress_name="big-download")

   # 另一线程 / GUI：
   progress_cancel("big-download")

取消会在传输循环中抛出 :class:`~automation_file.CancelledException`。
传输函数会捕捉该异常、将 reporter 标记为 ``status="cancelled"`` 并
返回 ``False``——调用方不需要自行处理异常。

快速文件搜索
------------

:func:`fast_find` 会挑选主机上最便宜的后端——优先使用 OS 索引，否则
流式 scandir 遍历——以最小能耗扫描大型目录树：

* macOS： ``mdfind`` （Spotlight）
* Linux： ``plocate`` / ``locate`` 数据库
* Windows：若已安装 Everything 的 ``es.exe`` CLI
* 兜底： ``os.scandir`` 生成器 + ``fnmatch`` 匹配，并以 ``limit=`` 提前终止

.. code-block:: python

   from automation_file import fast_find, scandir_find, has_os_index

   # 有索引时查询索引，否则退化到 scandir。
   results = fast_find("/var/log", "*.log", limit=100)

   # 强制走可移植路径（跳过 OS 索引）。
   results = fast_find("/data", "report_*.csv", use_index=False)

   # 流式生成器——无需扫描整棵树即可提前终止。
   for path in scandir_find("/data", "*.csv"):
       if "2026" in path:
           break

   # fast_find 会尝试哪个索引？返回 "mdfind" / "locate" /
   # "plocate" / "es" / None。
   has_os_index()

JSON 动作列表也可使用 ``FA_fast_find``：

.. code-block:: json

   [["FA_fast_find", {"root": "/var/log", "pattern": "*.log", "limit": 50}]]

校验和与完整性校验
------------------

以流式读取器（支持 :mod:`hashlib` 的任何算法）哈希任何文件，并以
常数时间比较来验证预期摘要：

.. code-block:: python

   from automation_file import file_checksum, verify_checksum

   digest = file_checksum("bundle.tar.gz")                 # 默认 sha256
   verify_checksum("bundle.tar.gz", digest)                # -> True
   verify_checksum("bundle.tar.gz", "deadbeef...", algorithm="blake2b")

相同函数在 JSON 动作列表中是 ``FA_file_checksum`` 与
``FA_verify_checksum``。

可续传 HTTP 下载
----------------

:func:`~automation_file.download_file` 接受 ``resume=True``。内容会写入
``<target>.part``；若临时文件已存在，下次调用会发送 ``Range: bytes=<n>-``
让传输从先前停止处续传。结合 ``expected_sha256=`` 可在最后一块写入后
立即校验下载：

.. code-block:: python

   from automation_file import download_file

   download_file(
       "https://example.com/big.bin",
       "big.bin",
       resume=True,
       expected_sha256="3b0c44298fc1...",
   )

文件去重
--------

:func:`~automation_file.find_duplicates` 以 ``os.scandir`` 遍历目录树一次，
并执行三阶段 size → partial-hash → full-hash 流水线。拥有唯一大小的文件
完全不会被哈希，因此数百万文件的树扫描仍然便宜：

.. code-block:: python

   from automation_file import find_duplicates

   groups = find_duplicates("/data", min_size=1024)
   # groups: list[list[str]]，每个内层列表为一组完全相同的文件，
   # 按大小降序排序。

``FA_find_duplicates`` 公开同一个调用给 JSON 动作列表使用。

目录增量同步
------------

:func:`~automation_file.sync_dir` 把 ``src`` 镜像到 ``dst``，只复制新的
或已变更的文件。变更检测默认为 ``(size, mtime)``；当 mtime 不可靠时
请传入 ``compare="checksum"``。``dst`` 下的额外文件默认不会动到，
需传入 ``delete=True`` 才会删除（并可用 ``dry_run=True`` 预览）：

.. code-block:: python

   from automation_file import sync_dir

   summary = sync_dir("/data/src", "/data/dst", delete=True)
   # summary: {"copied": [...], "skipped": [...], "deleted": [...],
   #           "errors": [...], "dry_run": False}

JSON 动作形式为 ``FA_sync_dir``。符号链接会以符号链接重建而非跟随，
因此指向目录树外的链接不会把镜像搞砸。

目录清单快照
------------

把目录树下所有文件的 JSON 清单写下来，稍后校验目录树未被变动。
适用于发布产物校验、备份完整性检查、移动前的飞行前检查：

.. code-block:: python

   from automation_file import write_manifest, verify_manifest

   write_manifest("/release/payload", "/release/MANIFEST.json")

   # 稍后……
   result = verify_manifest("/release/payload", "/release/MANIFEST.json")
   if not result["ok"]:
       raise SystemExit(f"manifest mismatch: {result}")

``result`` 分别报告 ``matched``、``missing``、``modified``、``extra`` 列表。
额外文件不算校验失败（与 ``sync_dir`` 的“默认不删除”行为一致）；
``missing`` 或 ``modified`` 则会。这两个操作以 ``FA_write_manifest``
与 ``FA_verify_manifest`` 暴露给 JSON 动作列表。

通知
----

通过 webhook、Slack 或 SMTP 推送一次性消息，或在触发器 / 调度器失败时
自动通知：

.. code-block:: python

   from automation_file import (
       SlackSink, WebhookSink, EmailSink,
       notification_manager, notify_send,
   )

   notification_manager.register(SlackSink("https://hooks.slack.com/services/T/B/X"))
   notify_send("deploy complete", body="rev abc123", level="info")

每个 sink 都实现同样的 ``send(subject, body, level)`` 接口，扇出
:class:`~automation_file.NotificationManager` 负责：

- 每个 sink 的错误隔离——一个故障 sink 不会让其他 sink 饿死。
- 滑动窗口去重——在 ``dedup_seconds`` 内，完全相同的
  ``(subject, body, level)`` 消息会被丢弃，避免卡住的触发器灌爆通道。
- 对每个 webhook / Slack URL 做 SSRF 校验。

调度器与触发器调度器会在失败时以 ``level="error"`` 自动通知——只要
注册 sink 即可获得生产告警。JSON 动作形式为 ``FA_notify_send`` 与
``FA_notify_list``。

配置文件与密钥提供者
--------------------

把通知 sink 与默认值一次写在 TOML 文件里。密钥引用在加载时会从环境变量
或文件根目录解析（Docker / K8s 风格）：

.. code-block:: toml

   # automation_file.toml

   [secrets]
   file_root = "/run/secrets"

   [defaults]
   dedup_seconds = 120

   [[notify.sinks]]
   type = "slack"
   name = "team-alerts"
   webhook_url = "${env:SLACK_WEBHOOK}"

   [[notify.sinks]]
   type = "email"
   name = "ops-email"
   host = "smtp.example.com"
   port = 587
   sender = "alerts@example.com"
   recipients = ["ops@example.com"]
   username = "${env:SMTP_USER}"
   password = "${file:smtp_password}"

.. code-block:: python

   from automation_file import AutomationConfig, notification_manager

   config = AutomationConfig.load("automation_file.toml")
   config.apply_to(notification_manager)

未解析的 ``${…}`` 引用会抛出
:class:`~automation_file.SecretNotFoundException` 而非悄悄变成空字符串。
自定义的 provider 链可通过 :class:`~automation_file.ChainedSecretProvider` /
:class:`~automation_file.EnvSecretProvider` /
:class:`~automation_file.FileSecretProvider` 组装，并传给
``AutomationConfig.load(path, provider=…)``。

DAG 动作执行器
--------------

:func:`~automation_file.execute_action_dag` 按依赖关系执行动作。每个节点
形如 ``{"id": str, "action": [name, ...], "depends_on": [id, ...]}``。
彼此独立的分支在线程池中扇出；当节点失败时，其后续依赖会被标记为
``skipped``（``fail_fast=True``，默认）或仍会执行（``fail_fast=False``）：

.. code-block:: python

   from automation_file import execute_action_dag

   results = execute_action_dag([
       {"id": "fetch",  "action": ["FA_download_file",
                                   ["https://example.com/src.tar.gz", "src.tar.gz"]]},
       {"id": "verify", "action": ["FA_verify_checksum",
                                   ["src.tar.gz", "3b0c44298fc1..."]],
                        "depends_on": ["fetch"]},
       {"id": "unpack", "action": ["FA_unzip_file", ["src.tar.gz", "src"]],
                        "depends_on": ["verify"]},
       {"id": "report", "action": ["FA_fast_find", ["src", "*.py"]],
                        "depends_on": ["unpack"]},
   ])

环路、未知依赖、自依赖与重复 id 会在任何节点执行前抛出
:class:`~automation_file.exceptions.DagException`。JSON 动作形式为
``FA_execute_action_dag``。

Entry-point 插件
----------------

第三方包可在自己的 ``pyproject.toml`` 中声明 ``automation_file.actions``
entry point，以注册自己的 ``FA_*`` 命令::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

其中 ``register`` 是零参数的可调用对象，返回
``Mapping[str, Callable]``。插件安装到同一个虚拟环境后，
:func:`~automation_file.core.action_registry.build_default_registry`
会自动采用——调用端无需任何修改：

.. code-block:: python

   # my_plugin/__init__.py
   def greet(name: str) -> str:
       return f"hello {name}"

   def register() -> dict:
       return {"FA_greet": greet}

.. code-block:: python

   # 消费端（执行 `pip install my_plugin` 之后）
   from automation_file import execute_action
   execute_action([["FA_greet", {"name": "world"}]])

插件失败（导入错误、factory 异常、返回形状错误、注册表拒绝）会被记录
并吞掉，一个坏插件不会破坏整个库。

GUI（PySide6）
--------------

标签式控制界面把每项功能都包起来：

.. code-block:: bash

   python -m automation_file ui
   # 或在 repo 根目录以开发模式执行：
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

标签页：Home、Local、Transfer、Progress、JSON actions、Triggers、Scheduler、
Servers。标签页下方的常驻 log panel 会实时流式推送每次调用的结果或错误。
后台工作通过 ``ActionWorker`` 在 ``QThreadPool`` 上执行，保持 UI 响应灵敏。

添加自定义命令
--------------

.. code-block:: python

   from automation_file import add_command_to_executor, execute_action

   def greet(name: str) -> str:
       return f"hello {name}"

   add_command_to_executor({"greet": greet})
   execute_action([["greet", {"name": "world"}]])

动态包注册
----------

.. code-block:: python

   from automation_file import package_manager, execute_action

   package_manager.add_package_to_executor("math")
   execute_action([["math_sqrt", [16.0]]])   # -> 4.0

.. warning::

   ``package_manager.add_package_to_executor`` 实际上会注册包中所有顶层
   函数 / 类 / 内置对象。切勿把它暴露给不受信任的输入（例如通过 TCP 或
   HTTP 服务器）。
