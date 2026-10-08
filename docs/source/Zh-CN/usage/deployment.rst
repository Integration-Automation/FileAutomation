部署到生产环境
==============

本页说明如何让 FileAutomation 在无人值守的情况下运行：要安装什么、它的状态存放在哪里、
如何把它作为一个长时间运行的进程启动、在网络上要开放什么，以及该监控什么。其中每个
部分都是普通的 Python；没有另外需要运维的服务器产品。

安装
----

请固定版本，并写明你用到的 extra。基础包不含任何云端 SDK 与 GUI 工具包：

.. code-block:: bash

   python -m venv /opt/fileautomation/venv
   /opt/fileautomation/venv/bin/pip install "automation_file[s3,sftp]==1.0.0"

在任何东西依赖它之前，先确认这份安装能连到哪些存储::

   /opt/fileautomation/venv/bin/python -m automation_file storage schemes

缺少 extra 的后端会在第一次调用时失败，并指出安装它的命令
（``pip install "automation_file[azure]"``），而不是在导入时失败。

请用专属的账号运行。那个账号在文件系统上的权限，加上你交给它的凭据，就是一个动作
所能做到的范围。

配置与机密
----------

把配置放在 ``automation_file.toml``，并把机密留在文件之外：

.. code-block:: toml

   [secrets]
   file_root = "/run/secrets"

   [[notify.sinks]]
   type = "slack"
   name = "team-alerts"
   webhook_url = "${env:SLACK_WEBHOOK}"

   [[notify.routes]]
   name = "failures"
   sinks = ["team-alerts"]
   types = ["pipeline.failed", "task.failed", "integrity.violation", "scheduler.error"]
   min_severity = "error"
   dedup_seconds = 600

``${env:NAME}`` 与 ``${file:name}`` 会在加载文件时解析，无法解析的引用会抛出异常，
而不是变成空字符串（:doc:`config`）。各后端的凭据来自环境变量，或来自该账号读得到的
文件，再传给各客户端的 ``later_init``。不要把机密写进动作列表、流水线定义或命令行：
这三者都会被记录、被存储，或被同一台机器上的其他用户看到。

单一进程
--------

调度器、完整性监控、通知路由器、审计轨迹与各个服务器，都是启动它们的那个进程中的
线程。因此生产环境的部署就是一个脚本：启动需要的东西，然后等待：

.. code-block:: python

   # /opt/fileautomation/service.py
   import os
   import signal
   import threading

   from automation_file import (
       ActionACL, AutomationConfig, IntegrityMonitor, SQLiteRunStore, configure_audit,
       install_operational_metrics, notification_manager, notification_router,
       s3_instance, start_http_action_server, start_metrics_server,
   )
   from automation_file.pipeline import set_default_run_store

   STATE = "/var/lib/fileautomation"

   # 1. 配置、sink 与通知路由。
   AutomationConfig.load("/etc/fileautomation/automation_file.toml").apply_to(
       notification_manager, notification_router
   )

   # 2. 重启之后必须还在的状态。
   configure_audit(f"{STATE}/audit.sqlite")
   set_default_run_store(SQLiteRunStore(f"{STATE}/runs.sqlite"))

   # 3. 后端。
   s3_instance.later_init(region_name=os.environ["AWS_REGION"])

   # 4. 会自行运行的部分。
   monitor = IntegrityMonitor("s3://reports/2026", baseline=f"{STATE}/reports.baseline.json")
   monitor.start()

   # 5. 对外监听的部分：只绑定 loopback、需要密钥，而且只开放客户端需要的动作。
   install_operational_metrics()
   start_metrics_server(port=9945)
   start_http_action_server(
       port=9944,
       shared_secret=os.environ["FA_SHARED_SECRET"],
       action_acl=ActionACL.build(allowed=["FA_pipeline_run", "FA_storage_copy", "FA_storage_list"]),
   )

   # 6. 持续存活，直到被要求停止。
   stop = threading.Event()
   signal.signal(signal.SIGTERM, lambda *_: stop.set())
   signal.signal(signal.SIGINT, lambda *_: stop.set())
   stop.wait()
   monitor.stop()

请用你的服务管理器来运行它。以 systemd 为例：

.. code-block:: ini

   [Unit]
   Description=FileAutomation
   After=network-online.target

   [Service]
   User=fileautomation
   EnvironmentFile=/etc/fileautomation/environment
   Environment=FILE_AUTOMATION_LOG_FILE=/var/log/fileautomation/FileAutomation.log
   ExecStart=/opt/fileautomation/venv/bin/python /opt/fileautomation/service.py
   Restart=on-failure
   StateDirectory=fileautomation
   LogsDirectory=fileautomation

   [Install]
   WantedBy=multi-user.target

在 Windows 上，同一个脚本可以通过 NSSM 之类的包装程序作为服务运行，或由任务计划程序以
“不论用户是否登录都运行”的方式启动。

只需要运行一次的作业（由系统本身的 cron 启动的夜间流水线、CI 步骤中的一次验证）不需要
这个服务：命令行就能完成，并以你可以据此处理的退出码结束（:doc:`cli`）::

   python -m automation_file pipeline --audit /var/lib/fileautomation/audit.sqlite \
       run /etc/fileautomation/daily.yaml --store /var/lib/fileautomation/runs.sqlite

磁盘上的状态
------------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - 项目
     - 位置与处理方式
   * - 审计轨迹
     - 你交给 ``configure_audit`` 的 SQLite 文件。它采用 WAL 模式，进程运行期间请用
       ``sqlite3 audit.sqlite ".backup …"`` 复制，不要用 ``cp``。按你的策略保留足够久，
       再运行 ``python -m automation_file audit purge --db … --older-than-days 365``。
   * - 流水线运行记录
     - ``SQLiteRunStore`` 的 SQLite 文件。崩溃之后 ``resume`` 读的就是它；没有它，进程
       结束时运行记录就被遗忘了。
   * - 完整性基准
     - 每棵受监控的目录树一个 JSON 文件。请把它放在它所描述的目录树之外，最好放在能
       修改该目录树的账号写不到的地方：谁能改写基准，谁就能掩盖变更。
   * - OAuth 令牌
     - 你交给 Google Drive 客户端的 ``token_path``。只允许服务账号读取。
   * - 日志
     - ``~/.automation_file/logs/FileAutomation.log``，除非 ``FILE_AUTOMATION_LOG_FILE``
       指定了其他路径。超过 10 MB 的文件会在进程打开它时被移到 ``.1``；需要更多轮转
       时请自行处理。
   * - 版本快照、回收站、内容存储库
     - 你交给这些功能的目录。在你清理之前，它们会持续增长。

网络暴露面
----------

每个服务器都只绑定 loopback 接口，除非你传入 ``allow_non_loopback=True``；这个默认值
也就是推荐做法：动作服务器会执行任何已注册的东西，所以连得到它，就等于连得到服务
账号的 Python 提示符。

* 同一台机器上的客户端使用 loopback 地址与共享密钥。
* 其他地方的客户端要经过某个负责终结 TLS 并验证身份的组件（反向代理、SSH 隧道、
  service mesh）。服务器本身使用的是明文 HTTP 与明文 TCP。
* 为每个服务器设置带有允许列表的 ``ActionACL``。ACL 也会检查嵌套在另一个动作参数中
  的动作。它看不到某个动作被指示去执行的文件内容，所以对必须留在列表之内的客户端，
  不要开放 ``FA_execute_files``，也不要开放以路径指定的流水线。
* MCP 服务器通过启动它的进程的标准流通信，不需要任何端口；它的允许列表请见
  :doc:`mcp`。

对外连往调用方提供的 URL 的请求，会经过 SSRF 防护：只允许 ``http`` 与 ``https``，
而且不允许私有、loopback 或 link-local 地址。有了这道防护，才能安全地接受客户端提供
的 URL；请不要绕过它。

该监控什么
----------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - 信号
     - 位置
   * - 健康状态
     - HTTP 动作服务器的 ``GET /healthz`` 与 ``GET /readyz``。
   * - 指标
     - ``start_metrics_server()`` 提供 Prometheus 文本格式。``automation_file_actions_total``
       及其耗时直方图一直都有；``install_operational_metrics()`` 会加上事件、通知与
       存储操作的计数器。
   * - 失败
     - 事件：``pipeline.failed``、``task.failed``、``integrity.violation``、
       ``storage.error``、``scheduler.error``、``system.error``。把你想被告知的事件
       路由到某个 sink（:doc:`notifications`）。
   * - 历史
     - 审计轨迹：``python -m automation_file audit search --db … --status error``，或用
       ``--correlation-id <run id>`` 查看一次运行所做的一切。
   * - 日志
     - INFO 以上的消息也会写到标准错误输出，由服务管理器收集。

承受失败
--------

* 为流水线任务设置 ``RetryPolicy`` 来应对会自行消失的错误（连接中断、被限流），并设置
  ``timeout`` 来应对永远不返回的情况。
* 为不可以发生两次的任务设置 ``idempotency_key``，并把运行记录保存在
  ``SQLiteRunStore``：重启之后，``pipeline resume <run id>`` 只会重做没有成功的部分。
* 调度作业在前一次运行尚未结束时不会启动，除非你允许重叠。
* 完整性监控的修复功能默认是关闭的，除非你配置了它。请先从告警开始，等你信任基准
  之后，再加上隔离或还原。

升级
----

1. 阅读版本说明。修订版只做修复；次版本可能会把东西标为弃用；只有主版本才会移除
   （:doc:`api_policy`）。
2. 在新版本进入生产环境之前，先用 ``-W error::DeprecationWarning`` 对它运行你自己的
   测试。
3. 备份那两个 SQLite 文件。会改变存储格式的版本仍然读得懂前一种格式，并说明如何转换。
4. 安装到旧环境旁边的一个全新虚拟环境，再把服务切换过去；这样要回滚时，再切换一次
   即可。

检查清单
--------

* 服务以专属账号运行，而且只有那个账号能读取机密与令牌文件。
* 版本与 extra 都已固定。
* 审计轨迹与运行记录存储库都是位于有备份的磁盘上的文件。
* 每个服务器都绑定在 loopback 接口、设有共享密钥与允许列表；任何远程连接都经过 TLS。
* 失败会传达给人：至少有一条针对错误的通知路由。
* 基准存放在受监控目录树的写入者无法修改的位置。
* 日志与持续增长的目录都有你自己决定的保留期限。
