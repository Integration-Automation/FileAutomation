automation_file
===============

语言：`English <../html/index.html>`_ | `繁體中文 <../html-zh-TW/index.html>`_ | **简体中文**

以自动化为核心的模块化框架，涵盖本地文件 / 目录 / ZIP 操作、经 SSRF 校验的
HTTP 下载、远程存储（Google Drive、S3、Azure Blob、Dropbox、SFTP、FTP、
WebDAV、SMB、fsspec），以及通过内建 TCP / HTTP 服务器执行的 JSON 动作。
内置 PySide6 图形界面，把每一项功能以标签页形式呈现；所有公开功能统一从
顶层 ``automation_file`` 外观模块重新导出。

功能亮点
--------

**核心原语**

* JSON 动作列表由共享的
  :class:`~automation_file.core.action_executor.ActionExecutor` 执行，支持
  校验、dry-run、并行、DAG。
* 路径穿越防护（:func:`~automation_file.local.safe_paths.safe_join`）、
  对外 URL 的 SSRF 校验、默认仅绑定 loopback 的 TCP / HTTP 服务器，
  可选共享密钥验证与每动作 ACL。
* 可靠性辅助：``retry_on_transient`` 装饰器、``Quota`` 流量与时间预算、
  流式 checksum、可续传 HTTP 下载。

**后端集成**

* 本地文件 / 目录 / ZIP / tar 操作。
* HTTP 下载：SSRF 防护、大小 / 超时上限、重试、续传、可选 SHA-256 校验。
* 一等公民后端：Google Drive、S3、Azure Blob、Dropbox、SFTP、FTP / FTPS、
  WebDAV、SMB / CIFS、fsspec — 全部自动注册。
* 跨后端复制，使用 URI 语法（``local://``、``s3://``、``drive://``、
  ``sftp://``、``azure://``、``dropbox://``、``ftp://`` …）。

**事件驱动**

* 文件监听触发器 ``FA_watch_*`` — 路径变动时自动执行动作列表。
* Cron 调度（``FA_schedule_*``）采用纯标准库的 5 字段解析器，
  提供重叠保护，失败时自动通知。
* 传输进度与取消 Token，通过 ``progress_name`` 对外暴露。

**可观测性与集成**

* 通知 Sink — webhook / Slack / SMTP / Telegram / Discord / Teams /
  PagerDuty，每个 Sink 独立隔离错误，并采用滑动窗口去重。
* Prometheus 指标导出器（``start_metrics_server``）、SQLite 审计日志、
  文件完整性监视器。
* HTMX 网页面板（``start_web_ui``）、MCP 服务器将注册表桥接到
  Claude Desktop / MCP CLI，走 JSON-RPC 2.0。
* PySide6 桌面 GUI（``python -m automation_file ui``）。

**供应链**

* 配置文件与机密信息 — 在 ``automation_file.toml`` 声明 sink 与默认值；
  ``${env:…}`` / ``${file:…}`` 引用通过 Env / File / Chained provider
  解析，避免把密钥写死在文件中。
* 入口点插件 — 第三方包通过
  ``[project.entry-points."automation_file.actions"]``
  注册自己的 ``FA_*`` 动作。

架构鸟瞰
--------

.. code-block:: text

   用户 / CLI / JSON batch
          │
          ▼
   ┌─────────────────────────────────────────┐
   │  automation_file（外观）                │
   │  execute_action、driver_instance、      │
   │  start_autocontrol_socket_server、      │
   │  start_http_action_server、Quota …      │
   └─────────────────────────────────────────┘
          │
          ▼
   ┌──────────────┐     ┌────────────────────┐
   │  core        │────▶│ ActionRegistry     │
   │  executor、  │     │ （FA_* 指令）      │
   │  retry、     │     └────────────────────┘
   │  quota、     │              │
   │  progress    │              ▼
   └──────────────┘     ┌────────────────────┐
                        │ local / remote /   │
                        │ server / triggers /│
                        │ scheduler / ui     │
                        └────────────────────┘

完整的模块树与设计模式见 :doc:`architecture`。

安装
----

.. code-block:: bash

   pip install automation_file

所有后端（S3、Azure Blob、Dropbox、SFTP、PySide6）都是一等运行期
依赖，常见使用场景不需要额外的 extras。

快速开始
--------

用 CLI 执行 JSON 动作列表：

.. code-block:: bash

   python -m automation_file --execute_file my_actions.json

直接从 Python 调用：

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir", {"source": "build", "target": "build.zip"}],
   ])

执行前先校验动作列表，或并行执行：

.. code-block:: python

   from automation_file import executor

   problems = executor.validate(actions)
   if problems:
       raise SystemExit("\n".join(problems))
   executor.execute_action_parallel(actions, max_workers=4)

启动 PySide6 图形界面：

.. code-block:: bash

   python -m automation_file ui

以共享密钥在 loopback 提供 HTTP 动作服务器：

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(port=8765, shared_secret="s3kret")

动作列表的格式
--------------

一个动作是三种 list 形式之一，按名称通过注册表调度：

.. code-block:: python

   ["FA_create_dir"]                                  # 无参数
   ["FA_create_dir", {"dir_path": "build"}]           # 关键字参数
   ["FA_copy_file", ["src.txt", "dst.txt"]]           # 位置参数

JSON 动作列表就是上述 list 的 list。

.. toctree::
   :maxdepth: 2
   :caption: 架构

   architecture

.. toctree::
   :maxdepth: 3
   :caption: 使用指南

   usage/index

.. toctree::
   :maxdepth: 2
   :caption: API 参考

   api/index

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
