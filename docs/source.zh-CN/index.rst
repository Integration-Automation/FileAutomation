###############
automation_file
###############

**以 JSON 动作列表为核心的模块化文件自动化框架。**

``automation_file`` 把本地文件 / 目录 / ZIP / tar 操作、经 SSRF 校验且
可续传的 HTTP 下载、十一种远端存储后端（Google Drive、S3、Azure Blob、
Dropbox、OneDrive、Box、SFTP、FTP / FTPS、WebDAV、SMB、fsspec）、
通过内建 TCP / HTTP / MCP 服务器执行的 JSON 动作列表、cron 调度器、
文件监控触发器、通知扇出、审计日志、AES-256-GCM 文件加密、Prometheus
指标，以及 PySide6 桌面图形界面，全部统合为单一框架——一切通过共享的
``ActionRegistry`` 调度，并由单一 ``automation_file`` 门面对外呈现。

* **PyPI**：https://pypi.org/project/automation_file/
* **GitHub**：https://github.com/Integration-Automation/FileAutomation
* **Issue / 未来规划**：https://github.com/Integration-Automation/FileAutomation/issues
* **许可**：MIT

语言：`English <https://fileautomation.readthedocs.io/en/latest/>`_ | `繁體中文 <https://fileautomation.readthedocs.io/zh_TW/latest/>`_ | **简体中文**

.. note::

   每个语言都是独立的 Read the Docs 项目，并挂在主项目
   ``fileautomation`` 下作为翻译。RTD 也会在每页右下角的版本菜单中
   自动提供语言切换器。

.. contents:: 本页目录
   :local:
   :depth: 1

----

安装
====

.. code-block:: bash

   pip install automation_file

每个后端（Google Drive、S3、Azure Blob、Dropbox、OneDrive、Box、SFTP、
FTP、WebDAV、SMB、fsspec）以及 PySide6 图形界面均为一级运行时依赖
包——无需记住任何可选 extra。

第一份动作
==========

一个动作是三种 JSON 形态之一——``[name]``、``[name, {kwargs}]`` 或
``[name, [args]]``。动作列表是动作的数组。共享的执行器会按序运行，
并返回每条动作的结果映射。

.. code-block:: python

   from automation_file import execute_action

   results = execute_action([
       ["FA_create_dir",  {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir",     {"dir_we_want_to_zip": "build", "zip_name": "build_snapshot"}],
   ])

同一份列表可从 CLI（``python -m automation_file run actions.json``）、
Loopback TCP / HTTP 服务器、MCP 主机，以及图形界面的 **JSON 动作** 分页
直接执行——无需改写。可参考 :doc:`usage/quickstart` 了解校验、Dry-run
与并行执行；:doc:`usage/cli` 介绍 argparse 派发器；:doc:`architecture`
说明注册器与执行器如何协作。

----

提供哪些功能
============

**本地操作**\ （:doc:`usage/local`）
   文件 / 目录 / ZIP / tar / 压缩档操作、``safe_join`` 路径穿越防护、
   感知 OS 索引的 ``fast_find``、流式 ``file_checksum`` 与
   ``find_duplicates``、``sync_dir`` rsync 风格镜像、目录差异比对、
   文本 patch、JSON / YAML / CSV / JSONL / Parquet 编辑、MIME 检测、
   模板渲染、回收站发送 / 还原、文件版本控制、条件式执行
   （``FA_if_exists`` / ``FA_if_newer`` / ``FA_if_size_gt``）、变量替换
   （``${env:…}`` / ``${date:%Y-%m-%d}`` / ``${uuid}``）、带超时的 shell
   子进程，以及 AES-256-GCM 文件加密。

**HTTP 传输**\ （:doc:`usage/transfer`）
   ``download_file`` 通过 ``validate_http_url`` 校验每个 URL（拒绝
   ``file://`` / ``ftp://`` / 私有 / loopback / link-local / 保留地址），
   设下大小与超时上限，支持通过 ``Range:`` 续传到 ``<target>.part``，
   传输后比对 ``expected_sha256``，并可整合进度注册器，提供实时传输
   快照与协作式取消。

**云端与远端存储**\ （:doc:`usage/cloud`）
   Google Drive（OAuth2）、S3（boto3）、Azure Blob、Dropbox、OneDrive、
   Box、SFTP（paramiko + ``RejectPolicy``）、FTP / FTPS、WebDAV、SMB /
   CIFS 与 fsspec 桥接——皆由 ``build_default_registry()`` 自动注册，
   并通过各自的共享单例访问。``copy_between`` 可按 URI 前缀在任意两个
   后端间搬运数据。

**动作服务器**\ （:doc:`usage/servers`）
   默认仅绑定 loopback 的 TCP 与 HTTP 服务器，接受 JSON 动作列表，可
   选择启用共享密钥认证、服务端 ``ActionACL`` 白名单、
   ``GET /healthz`` / ``GET /readyz`` 健康检查、``GET /openapi.json``、
   ``GET /progress`` WebSocket，以及带类型的 ``HTTPActionClient`` SDK。

**MCP 服务器**\ （:doc:`usage/mcp`）
   ``MCPServer`` 通过 stdio 上的换行分隔 JSON-RPC 2.0，把注册器桥接到
   任意 Model Context Protocol 主机（Claude Desktop、Claude Code、MCP
   CLI）。每个 ``FA_*`` 动作会变成带自动生成输入 schema 的 MCP 工具。

**桌面图形界面**\ （:doc:`usage/gui`）
   PySide6 分页控制界面——Home、Local、Transfer、Progress、JSON 动作、
   Triggers、Scheduler、Servers，加上每个云端后端各一个分页——共享
   相同的单例，并通过 ``ActionWorker`` 在全局线程池上派工。

**可靠性**\ （:doc:`usage/reliability`）
   ``retry_on_transient`` 带上限的指数退避、``Quota`` 大小与时间预算、
   ``CircuitBreaker``、``RateLimiter``、``FileLock`` / ``SQLiteLock``、
   持久化的 ``ActionQueue``、SQLite ``AuditLog``、用于周期清单比对的
   ``IntegrityMonitor``，以及带类型的 ``FileAutomationException`` 层级。

**触发器与调度**\ （:doc:`usage/events`）
   文件监控触发器（``FA_watch_*``）会在文件系统事件发生时运行动作列表；
   cron 风格调度器（``FA_schedule_*``）按调度周期性运行动作列表，并具
   重叠保护——两者均会在失败时回退到通知。

**通知**\ （:doc:`usage/notifications`）
   Slack、Email（SMTP）、Discord、Telegram、Microsoft Teams、PagerDuty
   与通用 Webhook 接收端，由 ``NotificationManager`` 组合，具备每接收端
   错误隔离与滑动窗口去重。

**配置与机密信息**\ （:doc:`usage/config`）
   在 ``automation_file.toml`` 中声明接收端与默认值；``${env:…}`` /
   ``${file:…}`` 引用通过链式 ``EnvSecretProvider`` / ``FileSecretProvider``
   解析；``ConfigWatcher`` 会轮询并热重载文件，无需重启。

**DAG 动作执行器**\ （:doc:`usage/dag`）
   以 DAG 形式运行动作列表，可声明依赖、进行拓扑式并行展开、按分支
   跳过失败节点。

**可观测性**
   ``start_metrics_server()`` 把每个动作以 Prometheus 计数器与直方图
   对外暴露；``start_web_ui()`` 提供仅依赖标准库的 HTMX 仪表板，
   呈现健康状态、进度与注册器。

**插件**\ （:doc:`usage/plugins`）
   第三方包可通过 ``[project.entry-points."automation_file.actions"]``
   注册自家 ``FA_*`` 动作；``PackageLoader`` 会导入一个 Python 包，
   并把其顶层成员以 ``<package>_<member>`` 名称注册进注册器。

----

阅读顺序
========

文档按语言与内容类型拆分。手册按典型读者旅程组织——安装、操作本地、
串接远端存储、对外开服务器、规模化自动化，最后深入可靠性、配置与
组合执行。API 参考则是每个公开模块的自动生成 Python 参考。

.. toctree::
   :maxdepth: 1
   :caption: 入门

   usage/quickstart
   usage/cli
   architecture

.. toctree::
   :maxdepth: 1
   :caption: 文件与存储操作

   usage/local
   usage/transfer
   usage/cloud

.. toctree::
   :maxdepth: 1
   :caption: 服务器与界面

   usage/servers
   usage/mcp
   usage/gui

.. toctree::
   :maxdepth: 1
   :caption: 运行时控制

   usage/reliability
   usage/events
   usage/notifications
   usage/config

.. toctree::
   :maxdepth: 1
   :caption: 组合与扩展

   usage/dag
   usage/plugins

.. toctree::
   :maxdepth: 1
   :caption: API 参考

   api/core
   api/local
   api/remote
   api/server
   api/client
   api/trigger
   api/scheduler
   api/notify
   api/progress
   api/project
   api/ui
   api/utils

----

索引
====

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
