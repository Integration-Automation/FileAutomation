架构
====

``automation_file`` 采用分层架构，核心由五种设计模式组成：

**Facade（外观）**
   :mod:`automation_file`（顶层 ``__init__``）是使用者唯一需要导入的名称。
   所有公开函数与单例都从这里重新导出。

**Registry + Command（注册表 + 命令）**
   :class:`~automation_file.core.action_registry.ActionRegistry` 将动作名称
   （出现于 JSON 动作列表中的字符串）映射到 Python 可调用对象。一个动作是
   形如 ``[name]``、``[name, {kwargs}]`` 或 ``[name, [args]]`` 的命令对象。

**Template Method（模板方法）**
   :class:`~automation_file.core.action_executor.ActionExecutor` 定义单个动作
   的生命周期：解析名称 → 分派调用 → 捕捉返回值或异常。外层迭代模板保证一个
   错误动作不会中断整批执行，除非设置 ``validate_first=True``。

**Strategy（策略）**
   每个 ``local/*_ops.py``、``remote/*_ops.py`` 与云端子包都是一组独立的
   策略函数。所有后端——本地、HTTP、Google Drive、S3、Azure Blob、Dropbox、
   SFTP——由 :func:`automation_file.core.action_registry.build_default_registry`
   自动注册。``register_<backend>_ops(registry)`` 辅助函数仍保留为公开 API，
   供自行装配注册表的调用方使用。

**Singleton（模块级单例）**
   ``executor``、``callback_executor``、``package_manager``、``driver_instance``、
   ``s3_instance``、``azure_blob_instance``、``dropbox_instance``、
   ``sftp_instance`` 是在 ``__init__`` 中装配的共享实例，让插件与 CLI 看到
   相同的状态。

模块结构
--------

.. code-block:: text

   automation_file/
   ├── __init__.py           # Facade——所有公开名称
   ├── __main__.py           # 带子命令的 CLI
   ├── exceptions.py         # FileAutomationException 异常层次
   ├── logging_config.py     # file_automation_logger
   ├── core/
   │   ├── action_registry.py
   │   ├── action_executor.py   # 串行 / 并行 / dry-run / validate-first
   │   ├── dag_executor.py      # 具并行扇出的拓扑调度器
   │   ├── callback_executor.py
   │   ├── package_loader.py
   │   ├── plugins.py           # entry-point 插件发现
   │   ├── json_store.py
   │   ├── retry.py             # @retry_on_transient
   │   ├── quota.py             # Quota(max_bytes, max_seconds)
   │   ├── checksum.py          # file_checksum、verify_checksum
   │   ├── manifest.py          # write_manifest、verify_manifest
   │   ├── config.py            # AutomationConfig（TOML 加载器 + 密钥解析）
   │   ├── secrets.py           # Env/File/Chained 密钥提供者
   │   └── progress.py          # CancellationToken、ProgressReporter、progress_registry
   ├── local/
   │   ├── file_ops.py
   │   ├── dir_ops.py
   │   ├── zip_ops.py
   │   ├── sync_ops.py          # rsync 风格的增量同步
   │   └── safe_paths.py        # safe_join + is_within
   ├── remote/
   │   ├── url_validator.py     # SSRF 防护
   │   ├── http_download.py     # 带重试的 HTTP 下载
   │   ├── google_drive/
   │   ├── s3/                  # 由 build_default_registry() 自动注册
   │   ├── azure_blob/          # 由 build_default_registry() 自动注册
   │   ├── dropbox_api/         # 由 build_default_registry() 自动注册
   │   └── sftp/                # 由 build_default_registry() 自动注册
   ├── server/
   │   ├── tcp_server.py        # 仅限 loopback、可选共享密钥
   │   └── http_server.py       # POST /actions、Bearer 认证
   ├── trigger/
   │   └── manager.py           # FileWatcher + TriggerManager（基于 watchdog）
   ├── scheduler/
   │   ├── cron.py              # 5 字段 cron 表达式解析器
   │   └── manager.py           # Scheduler 后台线程 + ScheduledJob
   ├── notify/
   │   ├── sinks.py             # Webhook / Slack / Email sink
   │   └── manager.py           # NotificationManager（扇出 + 去重 + auto-notify hook）
   ├── project/
   │   ├── project_builder.py
   │   └── templates.py
   ├── ui/                      # PySide6 GUI
   │   ├── launcher.py          # launch_ui(argv)
   │   ├── main_window.py       # 标签式 MainWindow（Home、Local、Transfer、
   │   │                        #   Progress、JSON actions、Triggers、
   │   │                        #   Scheduler、Servers）
   │   ├── worker.py            # ActionWorker（QRunnable）
   │   ├── log_widget.py        # LogPanel
   │   └── tabs/                # 每个后端一个标签 + JSON runner + servers
   └── utils/
       ├── file_discovery.py
       ├── fast_find.py         # OS 索引（mdfind/locate/es）+ scandir 兜底
       └── deduplicate.py       # size → partial-hash → full-hash 去重流水线

执行模式
--------

共享执行器支持五种彼此正交的模式：

* ``execute_action(actions)``——默认的串行执行；每个错误都会被捕捉并记录，
  不会中断整批执行。
* ``execute_action(actions, validate_first=True)``——执行前先解析所有名称；
  发现拼写错误会在任何动作执行前立即中止。
* ``execute_action(actions, dry_run=True)``——解析每个动作并记录将调用的内容，
  但不实际调用底层函数。
* ``execute_action_parallel(actions, max_workers=4)``——通过线程池并行调度
  动作。调用方需自行确保所选动作彼此独立。
* ``execute_action_dag(nodes, max_workers=4, fail_fast=True)``——Kahn 风格的
  拓扑调度。每个节点形如 ``{"id": str, "action": [...], "depends_on":
  [id, ...]}``。彼此独立的分支会并行执行；失败分支的后续依赖会被标记为
  ``skipped``（或在 ``fail_fast=False`` 下仍会执行）。环路 / 未知依赖 /
  重复 id 会在任何节点执行前被拒绝。

可靠性工具
----------

* :func:`automation_file.core.retry.retry_on_transient`——装饰器，对
  ``ConnectionError`` / ``TimeoutError`` / ``OSError`` 执行带上限的指数退避
  重试，:func:`automation_file.download_file` 已应用。
* :class:`automation_file.core.quota.Quota`——数据类，整合可选的
  ``max_bytes`` 大小上限与 ``max_seconds`` 时间预算。
* :func:`automation_file.core.checksum.file_checksum` 与
  :func:`automation_file.core.checksum.verify_checksum`——流式文件哈希
  （支持 :mod:`hashlib` 的任何算法），以常数时间比较摘要。
  :func:`automation_file.download_file` 接受 ``expected_sha256=`` 参数，
  在 HTTP 传输结束后立即校验目标文件。
* 可续传下载：:func:`automation_file.download_file` 接受 ``resume=True``，
  会写入 ``<target>.part`` 并发送 ``Range: bytes=<n>-``，让中断的传输从
  已有字节数续传，而不是从零重新开始。
* :func:`automation_file.utils.deduplicate.find_duplicates`——三阶段
  size → partial-hash → full-hash 流水线；大多数文件根本不会被哈希，因为
  大小唯一的分组在读取任何摘要之前就会被丢弃。
* :func:`automation_file.sync_dir`——使用 ``(size, mtime)`` 或基于哈希的
  变更检测执行增量目录镜像，可选择删除多余文件并支持 dry-run。
* :func:`automation_file.write_manifest` /
  :func:`automation_file.verify_manifest`——为根目录下的每个文件摘要
  建立 JSON 快照，可用于发布产物校验与篡改检测。
* :class:`automation_file.core.progress.CancellationToken` 与
  :class:`automation_file.core.progress.ProgressReporter`——传输的可选
  仪表化。HTTP 下载与 S3 上传 / 下载接受 ``progress_name=`` 关键字参数，
  将两个组件串入传输循环；JSON 动作 ``FA_progress_list`` /
  ``FA_progress_cancel`` / ``FA_progress_clear`` 操作共享注册表。

事件驱动调度
------------

两个长时间运行的子系统共用主执行器，而非各自派生独立的调度路径：

* :mod:`automation_file.trigger` 包装 ``watchdog`` 观察者。每个
  :class:`~automation_file.trigger.FileWatcher` 会把匹配的文件系统事件
  转发给共享注册表调度的动作列表。
  :data:`~automation_file.trigger.trigger_manager` 持有 name → watcher
  映射，让 GUI 与 JSON 动作共享同一个生命周期。
* :mod:`automation_file.scheduler` 运行一个后台线程，在分钟边界唤醒、
  遍历已注册的 :class:`~automation_file.scheduler.ScheduledJob`，并在
  短生命周期的工作线程上调度每个匹配的任务，避免慢动作拖累后续任务。

当动作列表抛出 :class:`~automation_file.exceptions.FileAutomationException`
时，两个调度器都会调用
:func:`automation_file.notify.manager.notify_on_failure`。未注册任何 sink 时
该辅助函数不做任何事，因此自动通知只是在注册任何
:class:`~automation_file.NotificationSink` 后自然产生的副作用。

通知
----

:mod:`automation_file.notify` 内置三个具体 sink
（:class:`~automation_file.WebhookSink`、:class:`~automation_file.SlackSink`、
:class:`~automation_file.EmailSink`），共同藏于一个
:class:`~automation_file.NotificationManager` 扇出之后。管理器负责：

* 每个 sink 的错误隔离——一个故障的 sink 不会让其他 sink 失败。
* 基于 ``(subject, body, level)`` 的滑动窗口去重，避免卡住的触发器
  灌爆通道。
* 模块级单例 :data:`~automation_file.notification_manager`，让 CLI、GUI、
  长时间运行的调度器全部通过同一份状态发布。

每个 webhook / Slack URL 都会经由
:func:`~automation_file.remote.url_validator.validate_http_url` 阻断 SSRF 目标。
Email sink 永远不会在 ``repr()`` 中暴露密码。

配置与密钥
----------

:class:`automation_file.AutomationConfig` 会加载 ``automation_file.toml``
文档，并提供辅助方法来实例化 sink / 默认值。密钥占位符（``${env:NAME}`` /
``${file:NAME}``）在加载时通过
:class:`~automation_file.ChainedSecretProvider`（由
:class:`~automation_file.EnvSecretProvider` 与 / 或
:class:`~automation_file.FileSecretProvider` 组成）解析。未解析的引用会
抛出 :class:`~automation_file.SecretNotFoundException`，拼错的名称不会
悄悄变成空字符串。

安全边界
--------

* **SSRF 防护**：所有外发 HTTP URL 都经由
  :func:`automation_file.remote.url_validator.validate_http_url` 校验。
* **路径穿越**：
  :func:`automation_file.local.safe_paths.safe_join` 将用户提供的路径
  解析于指定根目录之下，并拒绝 ``..``、位于根目录外的绝对路径以及
  指向根目录外的符号链接。
* **TCP / HTTP 认证**：两个服务器都接受可选的 ``shared_secret``。设置后，
  TCP 服务器要求 payload 前缀 ``AUTH <secret>\\n``，HTTP 服务器要求
  ``Authorization: Bearer <secret>``。两者默认绑定 loopback，除非显式
  传入 ``allow_non_loopback=True``，否则拒绝非 loopback 绑定。
* **SFTP 主机验证**：SFTP 客户端使用 :class:`paramiko.RejectPolicy`，
  绝不自动添加未知的主机密钥。
* **插件加载**：:class:`automation_file.core.package_loader.PackageLoader`
  会注册任意模块成员；切勿将其暴露给不受信任的输入。Entry-point 的
  发现路径（:func:`automation_file.core.plugins.load_entry_point_plugins`）
  相对安全——只有用户自行安装的包才能贡献命令；但每个插件仍以库的
  完整权限运行，安装第三方插件前请务必审查。

Entry-point 插件
----------------

第三方包可在不需要 ``automation_file`` 导入它们的情况下提供额外动作。
插件在自己的 ``pyproject.toml`` 中声明::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

其中 ``register`` 是零参数的可调用对象，返回
``Mapping[str, Callable]``——与传入
:func:`automation_file.add_command_to_executor` 的数据形状相同。
:func:`automation_file.core.action_registry.build_default_registry`
会在内置命令装配完成后调用
:func:`automation_file.core.plugins.load_entry_point_plugins`，
因此每个新建的注册表都会自动填入已安装的插件。插件失败（导入错误、
factory 异常、返回形状错误、注册表拒绝）会被记录并吞掉，
一个坏插件不会破坏整个库。

共享单例
--------

``automation_file/__init__.py`` 创建以下进程级单例：

* ``executor``——:func:`execute_action` 使用的 :class:`ActionExecutor`。
* ``callback_executor``——与 ``executor.registry`` 绑定的
  :class:`CallbackExecutor`。
* ``package_manager``——同一个注册表的 :class:`PackageLoader`。
* ``driver_instance``、``s3_instance``、``azure_blob_instance``、
  ``dropbox_instance``、``sftp_instance``——各个云端后端的延迟初始化
  客户端。

所有 executor 共享同一个 :class:`ActionRegistry`，因此调用
:func:`add_command_to_executor`（或任一 ``register_*_ops`` 辅助函数）
会让新命令立即对所有调度器可见。
