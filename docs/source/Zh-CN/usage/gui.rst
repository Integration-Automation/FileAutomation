GUI（PySide6）
==============

桌面窗口按“你想完成什么事”来组织，而不是按后端：侧边栏有九个工作流页面，另有一个
**Advanced** 条目，保留那些直接操作单个动作或单个后端的工具。

每个页面都只是应用层（:doc:`app_layer`）某一个服务的薄薄一层视图。窗口本身不带任何
逻辑，所以它显示的内容，就是 Web UI（:doc:`servers`）、CLI 与你自己的 Python 代码
看到的内容。

.. code-block:: bash

   pip install "automation_file[gui]"      # PySide6 是 extra，不是基础依赖
   python -m automation_file ui
   # 或在仓库根目录开发时：
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

没有安装 PySide6 时，``launch_ui`` 会抛出 ``OptionalDependencyException``，消息中
带有上面那行 ``pip install`` 命令。

导航
--------

.. list-table::
   :header-rows: 1
   :widths: 18 12 70

   * - 条目
     - 快捷键
     - 用途
   * - Dashboard
     - ``Ctrl+1``
     - 一眼看完健康状态、运行中与最近的流水线运行、完整性漂移、最近的事件与存储状态。
   * - Files
     - ``Ctrl+2``
     - 浏览存储 URI、预览文件、复制、移动、删除、创建目录。
   * - Storage
     - ``Ctrl+3``
     - 有哪些后端、每个后端能不能用，以及挂载点。
   * - Pipelines
     - ``Ctrl+4``
     - 可视化流水线编辑器：构建、验证、试运行、测试、运行、续跑。
   * - Scheduler
     - ``Ctrl+5``
     - Cron 作业：列出、添加、移除。
   * - Integrity
     - ``Ctrl+6``
     - 为目录树建立基线、验证与接受；启动与停止监控器。
   * - Audit
     - ``Ctrl+7``
     - 把审计轨迹指向数据库，搜索并统计其中的记录。
   * - Notifications
     - ``Ctrl+8``
     - 已注册的 sink、路由，以及测试消息。
   * - Settings
     - ``Ctrl+9``
     - 配置文件、可选的 extra、运行环境。
   * - Advanced
     - ``Ctrl+0``
     - Local、Transfer、Progress、JSON actions、Triggers 与 Servers：旧版窗口的
       页签。见 `旧页签去了哪里`_。

窗口
--------

侧边栏在左，选中的页面在右。两者下方是所有页面共用的 **活动日志**：每个动作开始时写
一行、得到结果时再写一行，并以页面名称开头。最新的一行也会在状态栏显示几秒钟。

每个页面的底部都有一行 **状态文字**，显示你在这个页面上最后做的那件事的结果：成功是
绿色，失败是红色。

没有任何操作会卡住窗口。页面把每一次调用交给线程池（``QThreadPool`` 上的
``ActionWorker``），结果回来时才显示。页面在你打开它时读取数据，按下它的 **Refresh**
按钮时再读一次。有两个视图会自己刷新：Dashboard 在可见时每五秒刷新一次；被跟踪的
流水线运行每秒刷新两次，直到它结束。

窗口与库的其余部分共用进程内的单例。从 Python 注册的 sink、通过 HTTP 动作服务器启动
的流水线，或由 JSON 动作启动的监控器，都会在下一次刷新后出现。

Dashboard
---------

**All clear** 或 **Needs attention**，旁边列出原因。只要最新的五十次运行中有一次
失败、某个监控器发现漂移或无法验证，或事件总线上有严重程度为 ``error`` 及以上的近期
事件，仪表板就会要求关注。

* **Health**：已注册的动作、运行中的运行、调度作业、完整性监控器、通知 sink 与路由、
  路由器是否启用，以及审计轨迹是否正在记录。
* **Pipeline runs**：最新几次运行的结局、仍在进行的运行，以及最近的结果与错误。
* **Integrity drift**：每个具名监控器、它的目标，以及它上次发现了什么。
* **Storage status**：每个后端以及能不能用。
* **Recent events**：总线上最新的二十个事件，新的在前。

**Refresh every 5 s** 开关定时器；**Refresh** 立即读取。仪表板只读取：不启动任何
东西，也不改变任何东西。

Files
-----

输入存储 URI 或本地路径（``s3://reports/2026``、``local:///data``、``C:\data``、
``memory://demo``）后按 **Open**。**Up** 回到上一级，**Browse local…** 选择目录。
在目录上双击会进入该目录，在文件上双击会预览它。

预览是有上限的：最多显示 64 KiB，而远程后端上超过 16 MiB 的文件根本不会被获取（状态
文字会说明）。二进制内容以前 256 个字节的十六进制转储显示。

各项操作都作用在选中的条目上：

* **Copy** / **Move** 到目标 URI，可以在同一个后端或另一个后端。目标若是已有的目录，
  文件会以原来的名称放进去。目录会连同其下的一切一起复制；目录不能移动（请先复制、
  检查副本，再删除原来的）。
* **Create directory** 在当前位置下创建目录。
* **Delete selected** 会先询问。有内容的目录需要勾选 **Delete a directory with its
  contents**。

每个路径都经过存储层（:doc:`storage`）：``..`` 会被拒绝，URI 中的凭据会被拒绝，挂载
的目录无法被跳出。

Storage
-------

每个后端一行：

.. list-table::
   :header-rows: 1
   :widths: 14 86

   * - Kind
     - 含义
   * - ``scheme``
     - 有工厂函数的 URI scheme：``local``、``memory``、``s3``、``azure``、
       ``gdrive``、``dropbox``、``onedrive``、``sftp``、``ftp``、``ftps``。
   * - ``mount``
     - 挂载在某个 URI 上的后端。它的名称就是那个 URI。
   * - ``client``
     - 有 ``FA_*`` 动作但没有存储 scheme 的共享 client（Box）。

本地与内存后端、挂载点，以及 client 已初始化的云端后端，**Usable** 为 ``yes``。
**Detail** 说明缺了什么：如何初始化 client；若该 extra 的包没有安装，则是
``pip install`` 命令。

**Mount a local directory** 以你选的 URI 提供某个目录，并把它限制在那个目录内
（把 ``sandbox://jobs`` 挂在 ``/srv/jobs``）。来自进程外部的路径请用这种方式处理。
**Unmount selected** 移除挂载点。选中挂载点、``local`` 或 ``memory`` 时，会显示该
后端提供哪些能力（目录、修改时间、ETag……）。

Pipelines
---------

这个页面是流水线定义（:doc:`pipeline`）的编辑器，也是它的运行控制台。

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 区域
     - 内容
   * - 最上面一行
     - **New**、**Open…**、**Save**、**Save as…**、**Auto layout**，以及文件名
       （有未保存的更改时会加上 ``(modified)``）。
   * - 第二行
     - 流水线名称、**Max workers**、描述、默认参数（JSON）与调度（cron 表达式，留给
       调度器使用）。
   * - Actions（左）
     - 所有已注册的动作，附筛选框。
   * - 画布（中）
     - 每个任务一个节点、每个依赖一条箭头，上方有 **Connect**、**Disconnect** 与
       **Remove selected**。
   * - Selected task（右）
     - 画布上选中的任务的表单。
   * - 运行栏
     - 运行参数（JSON）以及 **Validate**、**Dry run**、**Test task**、**Run**、
       **Resume**、**Retry**、**Cancel**、**Refresh history**、
       **Follow selected run**。
   * - 底部的页签
     - **Problems**、**Tasks**、**Log**、**History**。

流水线编辑器分步说明
----------------------------------------

1. **开始。** 按 **New** 创建空白定义，或按 **Open…** 打开 ``.yaml`` / ``.yml`` /
   ``.json`` 文件。不是有效定义的文件仍然打得开：形状正确的部分会显示出来，
   **Problems** 页签则列出它哪里有问题。

2. **命名。** 填入名称、worker 数量，需要的话再填描述、JSON 对象形式的默认参数与
   调度。

3. **添加任务。** 把 **Actions** 列表中的动作拖到画布上：任务会出现在你松开的位置。
   在动作上双击，或选中它再按 **Add task**，会把它加在最下面的任务之下。筛选框可以
   缩小列表（输入 ``storage`` 会显示 ``FA_storage_*`` 动作）。任务的 ID 由动作名称
   推导而来；可以在表单中修改。

4. **排列。** 把节点拖到你想要的位置。**Auto layout** 按依赖深度把每个任务放进对应的
   列。位置是编辑器的元数据：它存在定义旁边，绝不会存进定义里。

5. **连接。** 先点上游任务，再按住 ``Ctrl`` 点依赖它的任务，然后按 **Connect**。
   按钮会显示它将采用的方向（``Connect download -> publish``）：你选中这两个任务的
   顺序，就是箭头的方向。会形成依赖环的箭头会被拒绝。你也可以在任务表单的
   **Depends on** 中勾选上游任务。

   要移除依赖，请点它的箭头（或选中它两端的任务），再按 **Disconnect**。
   **Remove selected** 会移除选中的箭头；没有选中箭头时，则移除选中的任务与它们的
   箭头。

6. **编辑选中的任务。** 表单显示最后选中的任务：

   .. list-table::
      :header-rows: 1
      :widths: 24 76

      * - 字段
        - 含义
      * - Task ID
        - 在流水线中唯一。改名会保留箭头，并改写指向该任务的
          ``${tasks.<id>.result}`` 占位符。
      * - Action
        - 已注册的动作。它的签名与摘要显示在下方。
      * - Arguments
        - 动作的每个参数一行，并附上默认值。值若能解析成 JSON 就是 JSON
          （``12``、``true``、``["a", "b"]``、``"12"``），否则就是文本，所以 URI 或
          ``${params.date}`` 不需要加引号。留空的行不会被传入，因此使用默认值。
          **Add argument** 为接受 ``**kwargs`` 的动作添加一行。**Edit as JSON**
          把调用参数显示成一份 JSON 文档；位置参数（JSON 数组）只能用这种方式编辑。
      * - Depends on
        - 勾选必须先结束的任务。
      * - Attempts、Back-off、Back-off cap、Retry on
        - 总尝试次数、第一次退避时间与其上限，以及值得再试一次的异常名称（留空：
          瞬时性的那几种）。
      * - Timeout
        - 整个任务的秒数；留空表示不限。
      * - Run when
        - ``on_success``、``on_failure`` 或 ``always``。
      * - Idempotency key
        - 带有 ``${params.<name>}`` 占位符的文本；留空表示没有。

   在你按下 **Apply changes** 之前，什么都不会改变。**Revert** 会丢掉你输入的内容，
   选中另一个任务也一样。草稿拒绝某个值时，表单会说明原因，并保留你输入的内容。

7. **验证。** **Problems** 页签列出每一项发现，并附上所指条目的路径
   （``tasks.publish.depends_on[0]: unknown task 'x'``），包括注册表不认识的动作
   名称。点某个问题会选中它的任务。**Dry run**、**Test task**、**Run**、**Resume**
   与 **Retry** 都会先验证，有问题就停下来。

8. **试运行。** 以 JSON 对象输入运行参数，然后按 **Dry run**。不会执行也不会记录任何
   东西。**Tasks** 页签把每个任务显示为 ``planned`` 并附上层级；无法按计划运行的任务
   会说明原因（例如这次运行没有提供某个参数）。

9. **测试单个任务。** 选中一个任务再按 **Test task**。它的动作会真的执行，并应用它的
   重试策略与超时。它的上游任务则不会执行：每一个都换成不返回任何东西的替身，所以
   ``${tasks.<id>.result}`` 占位符会得到 ``null``。测试不会记录到任何 run store，
   也不会发布到共享的事件总线。

10. **运行。** **Run** 在后台启动流水线并跟踪它：**Tasks** 页签显示每个任务的状态、
    尝试次数、耗时与错误，**Log** 页签显示这次运行的事件，每个节点则换成它的状态
    颜色（灰色 pending、蓝色 running、绿色 succeeded、红色 failed 或超时、橙色
    cancelled、黄色 skipped）。**Cancel** 要求这次运行停下来。

11. **续跑或重试。** 失败之后，先排除原因。**Resume** 接续同一次运行：已成功的任务
    会保留，其余的重新运行，运行 ID 与参数都不变。**Retry** 以被跟踪的那次运行的
    参数启动一次新的运行。

12. **回顾。** **History** 页签列出已记录的运行，新的在前。在某一条上双击，或选中
    它再按 **Follow selected run**，就能再看到它的任务与事件；之后 **Resume** 与
    **Retry** 会作用在它身上。

13. **保存。** **Save as…** 把定义写成 ``.yaml``、``.yml`` 或 ``.json``，并把画布
    布局写进旁边的 ``<file>.layout.json``。定义文件正是 ``Pipeline.from_file`` 与
    ``FA_pipeline_run`` 所接受的文件。

Scheduler
---------

**Schedule a job** 需要唯一的名称、五个字段的 cron 表达式，以及 JSON 形式的动作
列表，按 **Add job** 注册。勾选复选框可以让新的一次运行在前一次还没结束时启动；否则
那次触发会被跳过，并计入 **Skipped**。表格显示每个作业的运行次数与上次运行时间；
**Remove selected** 与 **Remove all** 移除作业。要让流水线按调度运行，请调度
``FA_pipeline_run`` 并给它定义文件的路径。

窗口关闭时，这些作业会被移除。

Integrity
---------

输入 **Target**（要检查的目录树）与 **Baseline**（已核准状态存放的位置），两者都是
存储 URI 或本地路径。

* **Create baseline** 核准当前的内容。
* **Verify** 把目录树与基线比较，并列出每一项变更的种类与路径。关闭 **Deep** 时，只有
  大小或时间改变的文件会被哈希，摘要会注明这是快速检查。
* **Accept current state** 会先询问，然后把当前的目录树存成新的基线。

在 **Monitors** 下，给一个名称与间隔，按 **Start monitor** 就会在线程上持续验证
目标；表格显示每个监控器上次发现了什么。从窗口启动的监控器会在窗口关闭时停止。见
:doc:`integrity`。

Audit
-----

审计轨迹在取得 store 之前什么都不记录。输入 SQLite 数据库的路径（不存在时会创建），
按 **Configure**；之后 **State** 会显示记录写到哪里。

填入任何筛选条件，按 **Search**（新的在前，最多 **Limit** 条）或 **Count**。留空的
筛选条件不会限制搜索。**Since** 与 **Until** 接受带时区偏移的 ISO 8601 时间。选中
一条记录可以看到它的全部内容（JSON）。见 :doc:`audit`。

Notifications
-------------

**Sinks** 按名称、类型与送达位置列出已注册的 sink。Sink 是在代码中或从配置文件
（Settings）注册的；这个页面不会创建它们。选一个 sink（或 **All sinks**），需要的话
填入主题，按 **Send test message**；状态文字会显示每个 sink 的结果。

**Routes** 列出哪些事件送到哪些 sink。**Add or replace a route** 需要名称、sink
名称、事件类型（``pipeline.*``、``task.failed``）、来源、最低严重程度与节流数值；列表
以逗号分隔。路由若指名未注册的 sink 会被拒绝。路由器随第一条路由启动，最后一条路由
被移除时停止。见 :doc:`notifications`。

Settings
--------

输入 ``automation_file.toml`` 的路径（:doc:`config`）。

* **Preview** 读取文件并显示摘要。不会改变任何东西。
* **Apply** 注册它的通知 sink 与路由。

**Optional extras** 列出每个 extra、它启用的功能、是否已安装，以及未安装时的
``pip install`` 命令。**Environment** 显示包与 Python 版本、平台、日志文件，以及
最后应用的配置文件。

旧页签去了哪里
----------------------------

什么都没有移除。**Advanced** 条目保留了旧的页签，原封不动：

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - 旧页签
     - 现在
   * - Home
     - **Dashboard**（后端是否就绪在 *Storage status* 下，也在 **Storage** 页面）。
   * - Local
     - **Advanced** → *Local*。浏览与复制也可以在 **Files** 进行。
   * - Transfer（HTTP、Google Drive、S3、Azure Blob、Dropbox、SFTP、OneDrive、
       Box）
     - **Advanced** → *Transfer*。云端 client 的凭据就是在这里提供。
   * - Progress
     - **Advanced** → *Progress*。
   * - JSON actions
     - **Advanced** → *JSON actions*。
   * - Triggers
     - **Advanced** → *Triggers*。
   * - Scheduler
     - **Scheduler**。
   * - Servers
     - **Advanced** → *Servers*。

机密信息
----------------

没有任何页面会显示机密信息。Sink 以名称、类型与送达位置描述；配置文件摘要中的密码与
token 会换成 ``********``，webhook URL 只留下主机；事件、审计记录与运行参数在显示前
也以同样方式屏蔽；URL 中的凭据与 bearer token 会从页面显示的消息中移除。

值是否被屏蔽，取决于存放它的 *名称* 是否表明它是机密信息（``password``、``token``、
``api_key``、``authorization``……）。任务的结果则按任务返回的样子显示。所以请给机密
参数取这样的名称，并且不要把机密信息放进结果里。

在没有显示器的环境运行
------------------------------------------

Qt 需要显示器才能打开窗口。在没有显示器的服务器上：

* 只读视图请用 Web UI（:doc:`servers`）；它由同一个应用层渲染。
* 从 Python 直接使用应用层（:doc:`app_layer`），或通过 CLI 与动作服务器使用
  ``FA_*`` 动作。窗口做的每一件事，都是对其中之一的调用。
* 要构造窗口但不显示它（测试、CI 中的截图），请在导入 Qt 之前设置
  ``QT_QPA_PLATFORM=offscreen``：

  .. code-block:: python

     import os
     os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

     from PySide6.QtWidgets import QApplication
     from automation_file.app import build_services
     from automation_file.ui.main_window import MainWindow

     app = QApplication([])
     window = MainWindow(build_services())     # 或以 MainWindow() 使用共享的服务
     window.navigate("Pipelines")
     window.close()

``import automation_file`` 与 ``import automation_file.app`` 绝不会导入 PySide6；
只有 ``automation_file.ui`` 会。

出问题时
----------------

按钮好像没有反应
    请看页面底部的状态文字与活动日志。每一次拒绝与每一次失败都会在那里报告，并附上
    原因。

``launch_ui`` 抛出 ``OptionalDependencyException``
    没有安装 PySide6：``pip install "automation_file[gui]"``。

窗口打不开：“could not load the Qt platform plugin”
    没有显示器。见 `在没有显示器的环境运行`_。

云端后端显示“not initialised”
    它的共享 client 还没有凭据。打开 **Advanced** → *Transfer*，选择该后端并填写
    *Credentials*，或运行它的 ``FA_*_later_init`` 动作。

Detail 说某个包“is not installed”
    安装该行指名的 extra；**Settings** 列出每个 extra 与它的命令。

**Connect** 被拒绝
    这条箭头会形成依赖环，或是选中的任务不是恰好两个。

**Run** 停在“problem(s): see the Problems tab”
    定义无效。每个问题都以所指条目的路径开头；点它就会选中该任务。

按了 **Cancel** 之后运行仍是 ``running``
    运行中的动作无法被中断。尚未开始的任务会立刻被取消；运行中的任务返回后，这次运行
    才会结束。

**Resume** 被拒绝
    这次运行仍在进行、属于另一个名称的流水线，或是定义现在需要已存储的运行所没有的
    参数。

重启后历史是空的
    运行记录默认保存在内存中。在 ``launch_ui()`` 之前调用
    ``set_default_run_store(SQLiteRunStore(path))``，就能把它们保存在文件里。

**Search** 说 audit is not configured
    请先在同一个页面为审计轨迹指定数据库。

测试消息失败
    状态文字会显示每个 sink 的错误，URL 只留下主机。Sink 本身的说明见
    :doc:`notifications`。

页面显示的是旧数据
    按 **Refresh**。只有 Dashboard 与被跟踪的运行会自己刷新。

窗口关闭后还有东西在运行
    关闭窗口会移除调度作业，并停止它启动的监控器、动作服务器与触发器，但不会动流水线
    运行：已启动的运行会跑到结束，进程在那之前不会退出。
