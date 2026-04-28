============================
automation_file 简体中文文档
============================

简中手册按典型读者旅程拆分为章节：安装 → 执行 JSON 动作 → 操作本地文件
→ 串接远端存储 → 对外开服务器 → 规模化自动化。可使用左侧目录，或直接
跳到下方任一章节。

.. contents:: 本页目录
   :local:
   :depth: 1

----

.. _zh-cn-getting-started:

第 1 章 — 入门
==============

安装 ``automation_file``、执行第一份 JSON 动作列表，并理解注册器与
执行器之间的分工。

.. toctree::
   :maxdepth: 2
   :caption: 入门

   usage/quickstart

.. _zh-cn-cli:

第 2 章 — CLI
=============

使用 ``python -m automation_file`` argparse 派发器驱动框架——子命令、
旧版标志与 JSON 文件执行。

.. toctree::
   :maxdepth: 2
   :caption: CLI

   usage/cli

.. _zh-cn-architecture:

第 3 章 — 架构
==============

分层架构、设计模式（Facade、Registry、Command、Strategy、Template
Method、Singleton、Builder），以及执行器与注册器的交互方式。

.. toctree::
   :maxdepth: 2
   :caption: 架构

   architecture

.. _zh-cn-local:

第 4 章 — 本地操作
==================

由 ``local/`` 策略模块提供的文件、目录、ZIP、tar 与压缩档操作；
``safe_join`` 路径穿越防护；感知 OS 索引的 ``fast_find``；流式
``file_checksum`` 与 ``find_duplicates``；``sync_dir`` rsync 风格镜像；
目录差异比对与文本 patch；JSON / YAML / CSV / JSONL / Parquet 编辑;
MIME 检测；模板渲染；回收站发送 / 还原；文件版本控制；条件式执行；
变量替换；带超时的 shell 子进程；以及 AES-256-GCM 文件加密。

.. toctree::
   :maxdepth: 2
   :caption: 本地操作

   usage/local

.. _zh-cn-transfer:

第 5 章 — HTTP 传输
===================

经 SSRF 校验的对外 HTTP 下载，并通过 ``http_download`` 设下大小、
超时、重试与 ``expected_sha256`` 上限。可通过 ``Range:`` 续传到
``<target>.part``，并提供实时进度快照。

.. toctree::
   :maxdepth: 2
   :caption: HTTP 传输

   usage/transfer

.. _zh-cn-cloud:

第 6 章 — 云端与 SFTP 后端
==========================

Google Drive、S3、Azure Blob、Dropbox、OneDrive、Box、SFTP、FTP / FTPS、
WebDAV、SMB 与 fsspec——皆由 ``build_default_registry`` 自动注册。
``copy_between`` 可按 URI 前缀在不同后端间搬运数据。

.. toctree::
   :maxdepth: 2
   :caption: 云端与 SFTP 后端

   usage/cloud

.. _zh-cn-servers:

第 7 章 — 动作服务器
====================

默认仅绑定 loopback 的 TCP 与 HTTP 服务器，接受 JSON 动作列表，可
选择启用共享密钥认证、``ActionACL`` 白名单、``GET /healthz`` /
``GET /readyz`` 健康检查、``GET /openapi.json``、``GET /progress``
WebSocket，以及带类型的 ``HTTPActionClient`` SDK。

.. toctree::
   :maxdepth: 2
   :caption: 动作服务器

   usage/servers

.. _zh-cn-mcp:

第 8 章 — MCP 服务器
====================

``MCPServer`` 通过 stdio 上的换行分隔 JSON-RPC 2.0，把注册器桥接到
任意 Model Context Protocol 主机（Claude Desktop、Claude Code、MCP
CLI）。

.. toctree::
   :maxdepth: 2
   :caption: MCP 服务器

   usage/mcp

.. _zh-cn-gui:

第 9 章 — 图形界面
==================

PySide6 桌面控制界面——分页布局、日志面板，以及 ``ActionWorker`` 线程
池模型。

.. toctree::
   :maxdepth: 2
   :caption: 图形界面

   usage/gui

.. _zh-cn-reliability:

第 10 章 — 可靠性
=================

带上限的指数退避 ``retry_on_transient``、``Quota`` 大小与时间预算、
``CircuitBreaker``、``RateLimiter``、``FileLock`` / ``SQLiteLock``、
持久化的 ``ActionQueue``、SQLite ``AuditLog``、用于周期清单比对的
``IntegrityMonitor``，以及带类型的 ``FileAutomationException`` 层级。

.. toctree::
   :maxdepth: 2
   :caption: 可靠性

   usage/reliability

.. _zh-cn-events:

第 11 章 — 触发器与调度
=======================

文件监控触发器（``FA_watch_*``）会在文件系统事件发生时运行动作列表；
cron 风格调度器（``FA_schedule_*``）按调度周期性运行动作列表，并具备
重叠保护。

.. toctree::
   :maxdepth: 2
   :caption: 触发器与调度

   usage/events

.. _zh-cn-notifications:

第 12 章 — 通知
===============

Slack、Email（SMTP）、Discord、Telegram、Microsoft Teams、PagerDuty
与通用 Webhook 接收端，由 ``NotificationManager`` 组合，具备每接收端
错误隔离与滑动窗口去重。

.. toctree::
   :maxdepth: 2
   :caption: 通知

   usage/notifications

.. _zh-cn-config:

第 13 章 — 配置与机密信息
=========================

在 ``automation_file.toml`` 中声明接收端与默认值；``${env:…}`` /
``${file:…}`` 引用会通过链式 ``EnvSecretProvider`` /
``FileSecretProvider`` 解析；``ConfigWatcher`` 会轮询并热重载文件，
无需重启。

.. toctree::
   :maxdepth: 2
   :caption: 配置与机密信息

   usage/config

.. _zh-cn-dag:

第 14 章 — DAG 动作执行器
=========================

以 DAG 形式运行动作列表，可声明依赖、进行拓扑式并行展开、按分支
跳过失败节点。

.. toctree::
   :maxdepth: 2
   :caption: DAG 动作执行器

   usage/dag

.. _zh-cn-plugins:

第 15 章 — 插件
===============

第三方包可通过 ``[project.entry-points."automation_file.actions"]``
注册自家 ``FA_*`` 动作；``PackageLoader`` 会导入一个 Python 包，
并把其顶层成员以 ``<package>_<member>`` 名称注册进注册器。

.. toctree::
   :maxdepth: 2
   :caption: 插件

   usage/plugins
