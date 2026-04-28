automation_file
===============

语言：`English <../html/index.html>`_ | `繁體中文 <../html-zh-TW/index.html>`_ | **简体中文**

以 JSON 动作列表为核心的模块化文件自动化框架。

``automation_file`` 把本地文件 / 目录 / ZIP 操作、经 SSRF 校验的 HTTP 下载、
远端存储后端（Google Drive、S3、Azure Blob、Dropbox、OneDrive、Box、SFTP、
FTP、WebDAV、SMB、fsspec）以及通过内建 TCP / HTTP / MCP 服务器执行的 JSON
动作列表统合为单一框架——全部通过共享的 ``ActionRegistry`` 调度，并由
PySide6 桌面图形界面对外呈现。

文档按语言与内容类型拆分。每个语言手册以章节组织：入门、CLI、架构、
本地操作、HTTP 传输、云端与 SFTP 后端、动作服务器、MCP 服务器、图形界面、
可靠性、触发器与调度、通知、配置、DAG、插件。API 参考则是自动生成的
Python 参考资料。

未来规划
--------

项目跟踪：https://github.com/Integration-Automation/FileAutomation/issues

.. toctree::
   :maxdepth: 2
   :caption: 手册

   第 1 章 — 入门 <usage/quickstart>
   第 2 章 — CLI <usage/cli>
   第 3 章 — 架构 <architecture>
   第 4 章 — 本地操作 <usage/local>
   第 5 章 — HTTP 传输 <usage/transfer>
   第 6 章 — 云端与 SFTP 后端 <usage/cloud>
   第 7 章 — 动作服务器 <usage/servers>
   第 8 章 — MCP 服务器 <usage/mcp>
   第 9 章 — 图形界面 <usage/gui>
   第 10 章 — 可靠性 <usage/reliability>
   第 11 章 — 触发器与调度 <usage/events>
   第 12 章 — 通知 <usage/notifications>
   第 13 章 — 配置与机密信息 <usage/config>
   第 14 章 — DAG 动作执行器 <usage/dag>
   第 15 章 — 插件 <usage/plugins>

.. toctree::
   :maxdepth: 2
   :caption: API 参考

   第 A 章 — 核心 <api/core>
   第 B 章 — 本地操作 <api/local>
   第 C 章 — 远端操作 <api/remote>
   第 D 章 — 服务器 <api/server>
   第 E 章 — 客户端 SDK <api/client>
   第 F 章 — 触发器 <api/trigger>
   第 G 章 — 调度器 <api/scheduler>
   第 H 章 — 通知 <api/notify>
   第 I 章 — 进度与取消 <api/progress>
   第 J 章 — 项目脚手架 <api/project>
   第 K 章 — 图形界面 <api/ui>
   第 L 章 — 工具 <api/utils>

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
