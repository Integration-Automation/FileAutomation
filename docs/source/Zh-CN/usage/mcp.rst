MCP 服务器
====================

``automation_file`` 内置一个 Model Context Protocol（MCP）服务器，让 **Claude Desktop**
或 **Claude Code** 这类 AI 客户端可以通过它处理文件。传输方式是 stdio：每行一条
JSON-RPC 2.0 消息。

服务器提供两组工具：

* **语义工具**：十四个名称稳定、以任务为单位的工具（``file_read``、``file_copy``、
  ``pipeline_run`` ……），操作对象是 :doc:`存储 URI <storage>`，并受一份权限策略
  约束。这是为 AI 客户端设计的接口；
* **桥接**：每个已注册的 ``FA_*`` 动作各自成为一个工具，与之前的版本相同。为了兼容，
  它默认开启，而且 **不受** 策略约束。

语义工具的默认值是安全的：不允许任何位置、不能改动任何东西，每个响应的大小也都有
上限。

最小配置
----------------

给服务器一个可以读取的目录。写在 ``claude_desktop_config.json``\ （Claude Desktop）或
``.mcp.json``\ （Claude Code）里：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp", "--root", "/srv/reports", "--no-bridge"]
       }
     }
   }

客户端现在会看到十四个语义工具。它可以列出、读取、搜索 ``/srv/reports`` 下面的
内容并计算校验和，除此之外什么都不能做：写入会被拒绝，该目录以外的每个路径也一样。
在 Windows 上路径要写成 ``"C:\\data\\reports"``。如果 ``PATH`` 上的 ``python`` 不是
安装本包的那一个，请改用该环境的解释器
（``"command": "C:\\envs\\fa\\Scripts\\python.exe"``）。

使用 Claude Code 时，同一个服务器可以从 shell 添加::

   claude mcp add automation_file -- python -m automation_file mcp --root /srv/reports --no-bridge

生产环境配置
------------------------

列出每一个位置、只开启工作需要的权限、把流水线的定义存在磁盘上，并且关闭桥接：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "/opt/fa/bin/python",
         "args": [
           "-m", "automation_file", "mcp",
           "--root", "/srv/reports/inbox",
           "--root", "/srv/reports/outbox",
           "--allow-write",
           "--max-read-bytes", "65536",
           "--max-results", "100",
           "--pipeline-dir", "/var/lib/automation_file/pipelines",
           "--tools", "file_read,file_write,file_copy,file_search,file_checksum,file_verify,storage_list,storage_copy",
           "--no-bridge"
         ]
       }
     }
   }

远端后端必须先初始化客户端，审计轨迹与通知路由也要在服务器启动之前配置好。这需要
几行 Python，所以请用一个启动脚本来启动服务器，再把宿主的 ``command`` 指向它：

.. code-block:: python

   # /opt/fa/mcp_server.py
   import os

   from automation_file import (
       MCPServer, Route, Severity, SlackSink, configure_audit,
       notification_manager, notification_router, s3_instance, sftp_instance,
   )
   from automation_file.server.mcp_policy import MCPPolicy

   s3_instance.later_init(region_name="eu-west-1")              # 凭据：AWS 的默认来源链
   sftp_instance.later_init(host="sftp.example.com", username="reports",
                            key_filename="/etc/fa/id_ed25519",
                            known_hosts="/etc/fa/known_hosts")
   configure_audit("/var/lib/automation_file/audit.sqlite")     # audit_search 读的就是这里
   notification_manager.register(SlackSink(os.environ["SLACK_WEBHOOK"], name="ops"))
   notification_router.add_route(Route(
       "mcp-failures", sinks=("ops",),
       types=("mcp.tool.failed", "pipeline.failed", "storage.error"),
       min_severity=Severity.WARNING,
   ))
   notification_router.start()

   policy = MCPPolicy(
       roots=["s3://reports-export/daily", "sftp://sftp.example.com/inbound/reports"],
       allow_write=True,
       allow_delete=True,                # file_move 会删除来源
       max_read_bytes=64 * 1024,
       pipeline_dir="/var/lib/automation_file/pipelines",
   )
   MCPServer(policy=policy, bridge=False).serve_stdio()

.. code-block:: json

   {"mcpServers": {"automation_file": {"command": "/opt/fa/bin/python",
                                       "args": ["/opt/fa/mcp_server.py"]}}}

``stdout`` 上除了协议之外什么都不能写：库的日志写到 ``stderr`` 与它的日志文件，
启动脚本也不可以 ``print``。

语义工具
----------------

每个位置都是一个存储 URI，``<scheme>://<authority>/<path>``
（``local:///srv/reports/a.csv``、``s3://bucket/2026/a.csv``、
``sftp://host/inbox/a.csv``），或者是本地的绝对路径。“需要”一栏列出：除了要有一个
涵盖这次调用所有位置的根位置之外，策略还必须允许什么。

.. list-table::
   :header-rows: 1
   :widths: 14 30 36 20

   * - 工具
     - 参数
     - 结果
     - 需要
   * - ``file_read``
     - ``uri``、``offset=0``、``max_bytes``、``encoding="utf-8"``\ （文本编码，或
       ``base64``）
     - ``content``、``encoding``、``size``、``offset``、``bytes``、
       ``truncated``、``next_offset``
     - —
   * - ``file_write``
     - ``uri``、``content``、``encoding="utf-8"``、``overwrite=false``、
       ``dry_run=false``
     - ``size``、``sha256``、``overwrites``、``replaced_size``、``written``
     - 写入；要替换文件时还需要覆盖
   * - ``file_copy``
     - ``source``、``target``、``overwrite=false``、``verify=false``、
       ``dry_run=false``
     - ``source``、``target``、``size``、``overwrites``、``replaced_size``、
       ``deletes_source``、``done``；使用 ``verify`` 时另有 ``sha256``、
       ``verified``
     - 写入；要替换文件时还需要覆盖
   * - ``file_move``
     - 与 ``file_copy`` 相同
     - 与 ``file_copy`` 相同；``deletes_source`` 为 true
     - 写入与删除；要替换文件时还需要覆盖
   * - ``file_search``
     - ``uri``、``pattern="*"``、``content``、``recursive=true``、
       ``case_sensitive=false``、``max_results``
     - ``matches``\ （``uri``、``path``、``name``、``size``、``modified_at``；
       内容搜索另有 ``line``、``snippet``、``matching_lines``）、``count``、
       ``candidates``、``truncated``；内容搜索另有 ``searched_files``、
       ``searched_bytes``、``skipped``、``complete``
     - —
   * - ``file_checksum``
     - ``uri``、``algorithm="sha256"``
     - ``algorithm``、``value``、``size``
     - —
   * - ``file_verify``
     - ``uri``、``expected``\ （十六进制，或 ``sha256:<hex>``）、
       ``algorithm="sha256"``
     - ``match``、``expected``、``actual``、``algorithm``
     - —
   * - ``storage_list``
     - ``uri``、``recursive=false``、``max_results``
     - ``entries``\ （``uri``、``path``、``name``、``is_dir``、``size``、
       ``modified_at``）、``count``、``total``、``truncated``
     - —
   * - ``storage_copy``
     - ``source``、``target``、``overwrite=false``、``verify=false``、
       ``dry_run=false``
     - 文件：``kind="file"`` 加上 ``file_copy`` 的结果。目录：``kind="tree"``、
       ``planned``\ （``copy``、``overwrite``、``skip``、``bytes``）、``paths``、
       ``existing``、``truncated``、``done``，复制之后另有 ``copied``、
       ``skipped``、``failed``、``errors``、``ok``
     - 写入；要替换文件时还需要覆盖
   * - ``pipeline_create``
     - ``name``、``definition``、``overwrite=false``、``dry_run=false``
     - ``name``、``location``、``persistent``、``tasks``、``actions``、
       ``overwrites``、``stored``
     - 写入；要替换定义时还需要覆盖
   * - ``pipeline_run``
     - ``name``、``params``、``dry_run=false``、``background=false``
     - ``run_id``、``status``、``ok``、``run``\ （这次运行与它的每个任务）
     - 写入；每个任务需要它的动作所需要的权限
   * - ``pipeline_status``
     - ``run_id``，或 ``name`` 与 ``limit=5``
     - ``runs``、``count``
     - 不需要根位置
   * - ``integrity_status``
     - ``name``
     - ``monitors``\ （``name``、``target``、``running``、``last_run``、
       ``last_error``、``last_report``）、``count``
     - 不需要根位置
   * - ``audit_search``
     - ``actor``、``source``、``pipeline``、``task``、``action``、``backend``、
       ``status``、``correlation_id``、``resource_prefix``、``text``、``since``、
       ``until``、``limit=50``、``offset=0``
     - ``records``、``count``、``total``、``limit``、``offset``、``truncated``
     - 不需要根位置；需要已配置的审计轨迹

各个工具的说明：

``file_read``
    每次调用最多返回 ``--max-read-bytes`` 个字节。``truncated`` 为 true 时，把
    ``offset`` 设成 ``next_offset`` 再调用一次；字符绝不会被切成两半。内容不是所选
    编码的文本时会报告错误，并要求改用 ``encoding="base64"``。

``file_copy``、``file_move`` 与 ``verify``
    ``verify=true`` 时会比较来源与副本的 SHA-256。此时移动会先复制、再比较，只有在
    两个摘要一致时才删除来源；不一致时来源保留，调用以 ``checksum_mismatch`` 失败。

``file_verify``
    不一致是一个结果（``match`` 为 false），不是错误。

``file_search``
    ``pattern`` 是匹配文件名的 shell 模式（``*.csv``）；模式里有 ``/`` 时，匹配的是
    ``uri`` 下面的相对路径（``2026/*/*.csv``）。``content`` 是普通的子串，不是正则
    表达式。一次内容搜索最多读取 ``--max-search-bytes`` 个字节。超过剩余额度的
    文件不会被打开，而是列在 ``skipped`` 里；二进制文件与读不到的文件也一样。只有在
    每个候选文件都搜索过时，``complete`` 才是 true。

``storage_copy``
    像 ``file_copy`` 一样复制一个文件，或复制某个目录下面的所有文件。对目录而言，
    除非 ``overwrite`` 为 true，否则目标已有的文件会被跳过。失败的文件记在
    ``errors`` 里，其他文件照样复制；这时调用是一个错误，但结果里仍有各项数量。

``pipeline_run``
    在这次请求里运行，并返回已结束的运行。``background=true`` 时立刻返回
    ``status="running"``；请用 ``run_id`` 轮询 ``pipeline_status``。失败的运行是
    一个错误，但结果里仍带有这次运行。

结果与错误
~~~~~~~~~~~~~~~~~~~~

语义工具以一份 JSON 文档作为结果的文本响应。其中一定有 ``tool`` 与
``correlation_id``。调用被拒绝或失败时，``isError`` 为 true，文档里会有 ``error``：

.. code-block:: json

   {
     "tool": "file_write",
     "correlation_id": "27acff55529c4317b74de6ea98759f42",
     "error": {
       "type": "permission_denied",
       "code": "read_only",
       "message": "file_write changes something and this server is read-only: start it with --allow-write, or pass MCPPolicy(allow_write=True)"
     }
   }

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - ``error.type``
     - 含义
   * - ``permission_denied``
     - 策略拒绝了这次调用。``code`` 指出是哪一条规则：``no_root``、
       ``outside_root``、``read_only``、``overwrite_not_allowed``、
       ``delete_not_allowed``、``tool_disabled``、``action_not_allowed`` 或
       ``limit_exceeded``。
   * - ``invalid_arguments``
     - 参数缺少、未知、类型错误或超出范围。每个问题都会列出。
   * - ``invalid_uri``
     - 位置不是存储 URI，或它的路径含有 ``..`` 段。
   * - ``not_found``、``already_exists``
     - 没有这个文件、流水线、运行或监控器；或目标已存在而没有给 ``overwrite``。
   * - ``checksum_mismatch``
     - ``verify`` 发现两边的摘要不同。
   * - ``invalid_definition``
     - 流水线定义有误；``problems`` 列出每一项发现与它的路径。
   * - ``not_configured``
     - 服务器没有保存审计轨迹。
   * - ``failed``
     - 库报告的其他错误；``exception`` 是异常类的名称。
   * - ``internal_error``
     - 非预期的异常。请报告。

权限模型
----------------

:class:`~automation_file.server.mcp_policy.MCPPolicy` 在服务器启动时创建，之后无法
更改。它的文字描述会放在握手响应的 ``instructions`` 里发给客户端，所以模型在第一次
调用之前就知道边界在哪里。

.. list-table::
   :header-rows: 1
   :widths: 24 24 14 38

   * - 字段
     - 命令行参数
     - 默认值
     - 含义
   * - ``roots``
     - ``--root``\ （可重复）
     - 无
     - 工具可以工作的位置：存储 URI 或本地目录。一个都没有时，每个会碰到存储的
       工具都会拒绝，并说明如何添加根位置。
   * - ``allow_write``
     - ``--allow-write``
     - 关闭
     - 没有它，``file_write``、``file_copy``、``file_move``、``storage_copy``、
       ``pipeline_create`` 与 ``pipeline_run`` 都会被拒绝，试运行也一样。
   * - ``allow_overwrite``
     - ``--allow-overwrite``
     - 关闭
     - 替换已有的文件或定义。调用本身也必须提出要求（``overwrite=true``）。需要
       ``allow_write``。
   * - ``allow_delete``
     - ``--allow-delete``
     - 关闭
     - 删除。``file_move`` 会删除来源，所以需要它。需要 ``allow_write``。
   * - ``max_read_bytes``
     - ``--max-read-bytes``
     - 262144
     - ``file_read`` 一次调用最多返回的字节数，也是流水线工具返回的任务结果的
       大小上限。
   * - ``max_write_bytes``
     - ``--max-write-bytes``
     - 1048576
     - ``file_write`` 接受的内容大小上限，以及 ``pipeline_create`` 存储的定义大小
       上限。
   * - ``max_results``
     - ``--max-results``
     - 200
     - 列表、搜索、目录复制计划或 ``audit_search`` 最多返回的条目数。调用里较大的
       ``max_results`` 或 ``limit`` 会被降到这个值。
   * - ``max_search_bytes``
     - ``--max-search-bytes``
     - 8388608
     - 一次内容搜索最多读取的字节数。
   * - ``pipeline_dir``
     - ``--pipeline-dir``
     - 内存
     - ``pipeline_create`` 存放定义的地方：存储 URI 或本地目录，每条流水线一个
       ``<name>.json``。没有配置时定义保存在内存里，服务器停止就消失。
   * - ``pipeline_actions``
     - ``--pipeline-actions``
     - 按权限而定
     - 通过 MCP 创建或运行的流水线可以调用的动作。见 `流水线`_。
   * - ``tools``
     - ``--tools``
     - 全部十四个
     - 要提供的语义工具。没有列入的工具不会出现在列表里，调用它也会被拒绝。
       ``--tools none`` 一个都不提供。
   * - ``actor``
     - （仅限 Python）
     - ``mcp``
     - 事件与审计记录里每次调用的 actor。握手时客户端报告的名称会接在后面：
       ``mcp:claude-desktop``。

位置
~~~~~~~~

调用里提到的每个位置都在某个根位置之内（或就是根位置本身）时，调用才被允许。

* **本地根位置** 由存储层自己把关。该位置由一个限制在根位置内的 ``LocalStorage``
  提供服务，所以每个操作都会经过 ``safe_join``：指向根位置之外的符号链接（或
  Windows 的 junction），以及夹带到根位置下面的绝对路径，都会以 ``outside_root``
  被拒绝。留在根位置之内的链接则会被跟随。在 Windows 上比较不区分大小写，也接受
  反斜杠；名称是设备（``CON``、``NUL``、``COM1``）或备用数据流
  （``a.txt:stream``）的路径同样会被拒绝。
* **其他后端** 按 scheme、authority 与完整的路径段比较。``s3://bucket/team`` 允许
  ``s3://bucket/team/2026/a.csv``，并拒绝 ``s3://bucket/team-b/a.csv`` 与
  ``s3://other/team/a.csv``。authority 必须完全相同，包括大小写。根位置只是路径的
  前缀，仅此而已：服务器上已有的链接（例如 SFTP 的符号链接）会由服务器跟随。请给
  后端一个无法离开该目录树的账号。
* 含有 ``..`` 段的路径根本不是存储 URI（``invalid_uri``）。
* 用 ``Storage.mount`` 挂载的后端要通过它的挂载 URI 来指定；位于已挂载的
  ``LocalStorage`` 之下的根位置，会被限制在该根位置之内。

位置的写法要和根位置的写法一致。以 ``/srv/reports`` 给出的根位置不会匹配
``local:///mnt/disk2/reports``，即使两者是同一个目录。

流水线
~~~~~~~~~~~~

``pipeline_create`` 存储一份定义（:doc:`pipeline`，``schema_version: 1``），
``pipeline_run`` 则运行它。两者都需要 ``allow_write``。

定义可以调用什么，在创建时检查一次，运行时再检查一次，因为这段时间文件可能被别的
东西改写。默认情况下，流水线可以调用权限所涵盖的 ``FA_storage_*`` 动作：

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 权限
     - 动作
   * - 始终可用
     - ``FA_storage_exists``、``FA_storage_stat``、``FA_storage_list``、
       ``FA_storage_checksum``、``FA_storage_verify``、``FA_storage_read_text``、
       ``FA_storage_schemes``
   * - ``allow_write``
     - ``FA_storage_mkdir``、``FA_storage_write_text``、``FA_storage_copy``、
       ``FA_storage_copy_tree``
   * - ``allow_overwrite``
     - ``FA_storage_sync``\ （它会替换有变动的文件）
   * - ``allow_delete``
     - ``FA_storage_move``、``FA_storage_delete``

在这样的流水线里，这些名称运行的不是原本的动作，而是受防护的版本：它们在任务运行的
当下检查根位置与权限，也就是在 ``${params.<name>}`` 与 ``${tasks.<id>.result}``
填入之后，所以参数无法把任务带到根位置之外。它们的行为与原本的动作相同，区别如下：

* ``overwrite`` 的默认值是策略所允许的，而不是 ``true``；在不允许覆盖的地方，显式
  写出的 ``overwrite: true`` 会被拒绝；
* ``FA_storage_verify`` 的 ``expected`` 也接受 ``FA_storage_checksum`` 的结果，所以
  ``"${tasks.<id>.result}"`` 可以用来比较两个文件；
* ``FA_storage_read_text`` 与 ``FA_storage_write_text`` 遵守读取与写入的上限；
* ``FA_storage_sync`` 需要 ``allow_overwrite``，``delete: true`` 还需要
  ``allow_delete``；
* ``FA_storage_delete`` 绝不会移除根位置本身；
* 没有 ``FA_storage_upload`` 与 ``FA_storage_download``：它们接受的是文件系统路径，
  不是存储 URI。请改为复制到 ``local://`` URI，或从它复制出来。

``--pipeline-actions a,b,c`` 会替换默认的列表。上面的 ``FA_storage_*`` 动作被列入时
仍然受到防护。**其他动作则照原样运行，不受根位置与权限约束**：只列出你本来就愿意
让客户端直接调用的动作，而且绝不要列出会运行其他动作的动作
（``FA_execute_action``、``FA_pipeline_run``、``FA_run_shell``）。每个名称都必须是
服务器提供的动作，否则服务器不会启动。出现在另一个动作的参数里、或运行参数里的动作
会被拒绝，除非列表里有它；存储动作在那里则一律被拒绝，因为嵌套运行时它不受防护。

通过 MCP 创建的定义不能带有 ``schedule``：流水线何时自行运行，由运维服务器的人决定。
定义的 ``name`` 就是它存储时使用的名称；省略时会自动填入。

运行记录存在默认的运行记录存储里，``pipeline_status`` 与 ``FA_pipeline_status`` 都
从那里查找。除非启动脚本调用 ``set_default_run_store(SQLiteRunStore(path))``，否则
它只存在内存里。

试运行
------------

每个会改动东西的工具都接受 ``dry_run``。这时它会做完真正调用要做的每一项检查，
不改动任何东西，并返回计划：

.. code-block:: json

   {
     "tool": "file_move",
     "correlation_id": "bb62a807d4f64bf3b666d00d3b4f410f",
     "source": "s3://reports-export/daily/2026-10-07.csv",
     "target": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
     "size": 48211,
     "overwrites": false,
     "replaced_size": null,
     "deletes_source": true,
     "dry_run": true,
     "done": false
   }

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 工具
     - 试运行报告的内容
   * - ``file_write``
     - 内容的大小与 SHA-256、是否会替换某个文件，以及该文件的大小。
   * - ``file_copy``、``file_move``
     - 来源、目标、大小、目标是否会被替换、来源是否会被删除。
   * - ``storage_copy``
     - 对目录：会复制、替换与跳过多少文件与字节，以及路径（受 ``max_results``
       限制）。
   * - ``pipeline_create``
     - 定义是否有效且被允许、它的任务与动作，以及是否会替换已存储的定义。
   * - ``pipeline_run``
     - 按依赖顺序排列、状态为 ``planned`` 的任务；如果任务指定了未知的动作，或用到
       这次运行没有给的参数，会在该任务上附 ``error``。不会执行也不会记录任何
       东西。

试运行需要的权限与真正的调用相同：只读的服务器同样会拒绝它，所以服务器不会做的事，
也不会给出计划。

可追溯性
----------------

每次语义调用都在 ``correlation_scope()`` 与 ``actor_scope(...)`` 之内运行。结果带有
``correlation_id``，这次调用所做的一切也都带有它：存储操作，以及每次调用一条的
事件：``mcp.tool.completed`` 或 ``mcp.tool.failed``\ （source 为 ``mcp``）。

.. list-table::
   :header-rows: 1
   :widths: 26 14 60

   * - 结果
     - 严重级别
     - 事件
   * - 完成
     - info
     - ``mcp.tool.completed``，``status="ok"``
   * - 被策略拒绝
     - warning
     - ``mcp.tool.failed``，``status="refused"``，``code`` 指出规则
   * - 请求本身有误：文件不存在、目标已存在、参数错误、定义无效
     - info
     - ``mcp.tool.failed``，``status="error"``，``code`` 就是 ``error.type``
   * - 失败：后端错误、目录复制中有文件失败、流水线运行失败
     - warning
     - ``mcp.tool.failed``，``status="error"``。失败的后端另外以
       ``storage.error`` 报告，失败的运行则以 ``pipeline.failed`` 报告。
   * - ``verify`` 发现摘要不同
     - error
     - ``mcp.tool.failed``，``status="error"``，``code="checksum_mismatch"``
   * - 非预期的异常
     - error
     - ``mcp.tool.failed``，``status="error"``，``code="internal_error"``

因此，一条针对 ``mcp.tool.failed``、``min_severity=Severity.WARNING`` 的通知路由会
收到拒绝与真正的失败，而不会收到“模型要了一个不存在的文件”这种事。

事件的 payload 记有工具名称（``action``）、这次调用涉及的存储 URI（``resource``、
``source_uri``）、``duration_ms``，流水线工具另有 ``pipeline`` 与 ``run_id``。它绝不
包含内容、参数或摘要。被拒绝的调用也会以 warning 写进日志，内容是工具、规则与关联
ID，不含任何参数值。

配置了 :doc:`审计轨迹 <audit>` 之后，一次搜索就能看到某次调用做了什么：

.. code-block:: python

   audit_search(correlation_id="7dc51e94bd3b494eae8e6b6f3f3b150b")
   # [{"source": "mcp", "action": "mcp.tool.completed", "actor": "mcp:claude-desktop", ...},
   #  {"source": "storage", "action": "copy", "resource": "sftp://...", "status": "ok", ...}]

流水线的一次运行有它自己的关联 ID，也就是它的 ``run_id``。``pipeline_run`` 那次调用的
事件里记有这个 ``run_id``，两者由此关联起来。

示例：从 S3 到 SFTP，经过验证与审计，失败时发出告警
------------------------------------------------------------------------

任务内容：*把昨天的 CSV 从 S3 移到公司的 SFTP 服务器，验证它的 SHA-256，审计这次
传输，失败时通知 Slack*。`生产环境配置`_ 的启动脚本已经准备好所需的一切：两个后端都
已初始化、两个根位置、允许写入与删除、一份审计轨迹，以及一条把失败发到 Slack 的
路由。接着客户端进行这些调用：

.. code-block:: text

   1. storage_list   {"uri": "s3://reports-export/daily"}
        -> 条目列表；客户端选出 2026-10-07.csv

   2. file_move      {"source": "s3://reports-export/daily/2026-10-07.csv",
                      "target": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
                      "verify": true, "dry_run": true}
        -> 计划：size、overwrites=false、deletes_source=true

   3. file_move      同样的参数，去掉 dry_run
        -> done=true、verified=true、sha256="9f86d0..."、correlation_id="7dc5..."
           两个 SHA-256 摘要一致之后，来源才被删除。

   4. file_verify    {"uri": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
                      "expected": "sha256:9f86d0..."}
        -> match=true（独立的检查，留作记录）

   5. audit_search   {"correlation_id": "7dc5..."}
        -> 第 3 步的 mcp.tool.completed 记录，以及存储记录（copy、delete），
           附有资源、耗时与状态

**失败时。** 第 3 步失败时，客户端会收到 ``error``，来源仍然在 S3 里。服务器会发布
``mcp.tool.failed``\ （摘要不同时是 error，传输失败时是 warning），后端失败时另外
发布 ``storage.error``，启动脚本配置的路由再把它们发到 Slack。通知不是由任何工具
发出的，所以客户端无法跳过它。

同一件工作也可以写成流水线，创建一次、每天运行：

.. code-block:: text

   pipeline_create {
     "name": "export-daily",
     "definition": {
       "schema_version": 1,
       "description": "Move the daily export from S3 to SFTP and verify it",
       "tasks": {
         "digest": {"action": ["FA_storage_checksum",
                               {"uri": "s3://reports-export/daily/${params.date}.csv"}]},
         "copy":   {"action": ["FA_storage_copy",
                               {"source": "s3://reports-export/daily/${params.date}.csv",
                                "target": "sftp://sftp.example.com/inbound/reports/${params.date}.csv"}],
                    "depends_on": ["digest"],
                    "retry": {"max_attempts": 3, "backoff": 5}, "timeout": 600},
         "verify": {"action": ["FA_storage_verify",
                               {"uri": "sftp://sftp.example.com/inbound/reports/${params.date}.csv",
                                "expected": "${tasks.digest.result}", "strict": true}],
                    "depends_on": ["copy"]},
         "remove": {"action": ["FA_storage_delete",
                               {"uri": "s3://reports-export/daily/${params.date}.csv"}],
                    "depends_on": ["verify"]}
       }
     }
   }
   pipeline_run    {"name": "export-daily", "params": {"date": "2026-10-07"}, "dry_run": true}
   pipeline_run    {"name": "export-daily", "params": {"date": "2026-10-07"}}
   audit_search    {"correlation_id": "<the run_id>"}

``"${tasks.digest.result}"`` 把来源的校验和交给 ``FA_storage_verify``。加上
``strict: true`` 之后，不一致会让任务失败，于是 ``remove`` 被跳过，来源保留。失败的
运行会发布 ``pipeline.failed``，同一条路由会把它发到 Slack。

``FA_*`` 桥接
--------------------

桥接开启时，``tools/list`` 先返回语义工具，接着是每个已注册的动作各一个工具，按名称
排序，其 JSON Schema 由 Python 签名派生而来。对这类工具调用 ``tools/call`` 会通过
注册表派发，并以 JSON 编码的返回值响应；失败则是 JSON-RPC 错误。之前的版本就是这样
工作的，已有的配置可以继续使用。

.. code-block:: text

   python -m automation_file mcp                                    # 语义工具 + 每个 FA_* 动作
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum
   python -m automation_file mcp --root /srv/reports --no-bridge    # 只有语义工具

``--allowed-actions`` 把桥接缩小到指定的动作。参数里提到列表以外动作的调用会被拒绝
（无法用 ``FA_execute_action`` 绕过去）。``--no-bridge`` 或
``MCPServer(bridge=False)`` 会关闭桥接；此时 ``FA_*`` 名称是未知的工具。

**策略不约束桥接。** 通过桥接调用的 ``FA_storage_copy`` 可以到达进程能到的任何
位置，不管 ``--root`` 怎么配置。面对 AI 客户端请使用 ``--no-bridge``；桥接只留给
那些即使没有策略你也愿意让客户端调用的工具。

从 Python 使用：

.. code-block:: python

   from automation_file import MCPServer, executor, tools_from_registry
   from automation_file.server.mcp_policy import MCPPolicy
   from automation_file.server.mcp_tools import SemanticToolkit

   MCPServer().serve_stdio()                                  # 和以前一样：桥接开启
   MCPServer(policy=MCPPolicy(roots=["/srv/reports"]), bridge=False).serve_stdio()

   for tool in tools_from_registry(executor.registry):        # 桥接的工具目录
       print(tool["name"], "->", tool["description"])

   toolkit = SemanticToolkit(MCPPolicy(roots=["/srv/reports"]))   # 不经 JSON-RPC 使用工具
   outcome = toolkit.call("file_checksum", {"uri": "/srv/reports/a.csv"})
   outcome.is_error, outcome.payload["value"], outcome.correlation_id

命令行参数
--------------------

``python -m automation_file mcp`` 与 ``automation_file_mcp`` 控制台脚本接受相同的
命令行参数。

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - 命令行参数
     - 含义
   * - ``--name``、``--version``
     - 握手时的 ``serverInfo``。默认值：``automation_file``、``1.0.0``。
   * - ``--allowed-actions a,b``
     - 桥接提供的已注册动作。默认：全部。
   * - ``--no-bridge``
     - 只提供语义工具。
   * - ``--root URI``
     - 一个允许的位置；可重复。
   * - ``--allow-write``、``--allow-overwrite``、``--allow-delete``
     - 三项权限。后两项需要第一项。
   * - ``--max-read-bytes N``、``--max-write-bytes N``、``--max-results N``、
       ``--max-search-bytes N``
     - 各项上限。
   * - ``--pipeline-dir URI``
     - 流水线定义存放的地方。
   * - ``--pipeline-actions a,b``
     - 通过 MCP 运行的流水线可以调用的动作。
   * - ``--tools a,b``
     - 要提供的语义工具，或 ``none``。

错误的命令行参数（未知的工具名称、没有 ``--allow-write`` 的 ``--allow-overwrite``、
带有凭据的根位置）会让命令在开始服务之前就以用法错误结束。

安全指引
----------------

* **进程的权限就是外部边界。** 服务器以启动它的用户身份运行，使用后端被给予的
  凭据。策略为语义工具缩小这个范围；它不能替代账号、bucket policy 或 SFTP 用户
  上的最小权限。
* **面对 AI 客户端请关闭桥接**\ （``--no-bridge``）。桥接提供每个已注册的动作，
  包括 ``FA_run_shell`` 与 ``FA_storage_delete``，而策略对它不适用。
* **根位置要尽量小。** 根位置是对其下所有内容的授权。不要使用 ``local:///`` 或主
  目录。客户端可以写入的东西，请放在它专属的目录里。
* **从只读开始。** 工作需要时才加上 ``--allow-write``，确实需要时才加上
  ``--allow-overwrite`` 与 ``--allow-delete``。能写入但不能覆盖或删除的客户端，
  无法破坏原本就在那里的东西。
* **文件的内容不是指令。** 模型通过 ``file_read`` 与 ``file_search`` 读到文件内容，
  并可能按照读到的东西行动。策略限制了这样被劫持的会话能做的事；宿主的确认提示
  也是。对重要的操作，先要求一次 ``dry_run``。
* **流水线。** 默认的动作留在根位置之内。你用 ``--pipeline-actions`` 添加的每个动作
  都不受限制地运行。流水线目录里放的是 AI 客户端写下的定义：只有 ``pipeline_run``
  会对它们应用策略，所以不要用 ``FA_pipeline_run`` 或 ``Pipeline.from_file`` 运行
  它们，也不要让调度器指向那个目录。
* **报告类工具不受根位置约束。** ``audit_search``、``integrity_status`` 与
  ``pipeline_status`` 会显示整个进程里的资源名称、错误与运行参数。对于不该看到这些
  的客户端，请不要把它们列入 ``--tools``。
* **客户端的名称不能证明任何事。** 它只是审计轨迹里 actor 的标签，而且由客户端
  自己提供。stdio 没有认证机制：能启动这个进程的人，就拥有它的能力。
* **机密。** 凭据绝不该放在存储 URI 里（带有凭据的 URI 会被拒绝），也不该放在流水线
  参数里，因为参数会随运行一起被记录。日志不含参数值，也不含文件内容。
* **网络。** 语义工具本身不发出任何 HTTP 请求。存储后端保有各自的检查：TLS 验证、
  SFTP 主机密钥，以及会抓取 URL 的动作所用的 SSRF 防护。
* 不要在提供桥接的进程里调用 ``PackageLoader.add_package_to_executor``：它会把包的
  每个成员注册成动作。

出问题时
----------------

``no storage location is allowed on this server``
    没有配置任何根位置。加上 ``--root <存储 URI 或目录>``，或传入
    ``MCPPolicy(roots=[...])``。

``... is outside the allowed locations (...)``
    位置不在任何根位置之内；消息里会列出根位置。请对照根位置检查写法：另一个
    bucket 或主机、相邻的目录（``reports`` 旁边的 ``reports-old``）、authority 的
    大小写不同，或通往同一个目录的另一条路径。

``... leaves the allowed location through a link or an absolute path``
    本地根位置下面的符号链接或 junction 指向根位置之外。如果客户端应该能到达那里，
    请把链接的目标加为根位置。

``this server is read-only``、``does not allow it``
    权限没有开启：``--allow-write``、``--allow-overwrite`` 或 ``--allow-delete``。
    ``file_move`` 需要写入与删除。

``already exists``
    传入 ``overwrite=true``；服务器也必须允许覆盖。

``file_read`` 只返回文件的一部分
    ``truncated`` 为 true：以 ``offset=next_offset`` 再调用一次，或调高
    ``--max-read-bytes``。对于不支持范围读取的后端，每次调用都会把整个文件暂存到
    本地，所以翻阅很大的远端文件时请节制。

``file_search`` 漏掉某个文件
    检查 ``complete`` 与 ``skipped``。超过 ``--max-search-bytes`` 剩余额度的文件
    不会被搜索；请缩小 ``pattern`` 或调高额度。内容是按 UTF-8 文本匹配的。

``... is not allowed in a pipeline``
    定义提到了允许范围以外的动作；消息里会列出允许的动作。请使用存储动作，或用
    ``--pipeline-actions`` 添加该动作。

流水线任务以 ``MCPLocationException`` 或 ``MCPPermissionException`` 失败
    任务在运行时到达了根位置以外的位置，或需要一项没有开启的权限。定义之所以被
    接受，是因为位置来自参数。

``no pipeline named ... is stored``
    消息里会列出已存储的名称。没有 ``--pipeline-dir`` 时，服务器重新启动后定义就
    不在了。

``pipeline_status`` 找不到某次运行
    运行记录默认存在内存里。请在启动脚本里调用
    ``set_default_run_store(SQLiteRunStore(path))``。

``this server keeps no audit trail``
    请在启动脚本里于 ``serve_stdio()`` 之前调用 ``configure_audit(path)``。

``sftp://`` 或 ``s3://`` 位置明明在根位置之内却失败
    这个进程里的后端没有初始化。请在启动脚本里调用它的 ``later_init``；见
    `生产环境配置`_ 与 :doc:`storage`。

宿主列出数百个工具，或完全没有语义工具
    前者是桥接：加上 ``--no-bridge`` 或 ``--allowed-actions``。后者是
    ``--tools none``，或包的版本早于语义工具。

宿主在启动时报告连接中断
    有东西写到了 ``stdout``，或命令以用法错误结束。请在终端里运行同一条命令：
    错误会写到 ``stderr``。手动检查服务器的方法::

       printf '%s\n%s\n' \
         '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
         '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
         | python -m automation_file mcp --root /srv/reports --no-bridge

语义工具的每个异常都派生自 ``MCPServerException``，因此也派生自
``FileAutomationException``：``MCPPermissionException``\ （带有 ``code``）、它的子类
``MCPLocationException``，以及 ``MCPToolException``\ （带有 ``kind``）。
