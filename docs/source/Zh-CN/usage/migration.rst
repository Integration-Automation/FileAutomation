迁移到 1.0
==========

为 0.0.x 写的代码仍然可以运行：没有任何 ``FA_*`` 动作、facade 名称或命令行选项被移除。
本页列出少数行为有所不同之处，并针对每一个旧接口，说明对应的新接口以及何时该优先采用。

你必须做的事
------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - 如果你
     - 那么
   * - 安装本包并使用云端后端、Parquet 或 GUI
     - 请写明 extra。基础安装不再附带各家 SDK：
       ``pip install "automation_file[s3,sftp]"``，或用 ``[all]`` 获得 0.0.x 所安装的
       全部内容。缺少 SDK 时，会在第一次调用时失败并指出要运行的命令。
   * - 在 Windows 上的调度使用时区
     - 不必做任何事：在 Windows 上 ``tzdata`` 会随包一起安装。
   * - 以 ``sftp://host/path`` 或 ``ftp://host/path`` 调用 ``copy_between``
     - 两个斜线现在代表主机与绝对路径，而且主机必须是会话实际连接的那一台。
       文档记载的单斜线写法（``sftp:/path``，相对于登录目录）没有改变。
   * - 依赖 ``copy_between`` 在后端尚未初始化时抛出 ``RuntimeError``
     - 请改为捕获 ``StorageUnavailableException``（属于 ``FileAutomationException``）。
   * - 把指向其他主机的完整 URL 当成路径传给 ``WebDAVClient``，或依赖它跟随重定向到
       其他主机
     - 现在会被拒绝。请为那台主机另外建立客户端。
   * - 读取或赋值调度作业的 ``job.cron``
     - 读取仍然可行。赋值不再会重新调度：请先移除作业，再重新加入。
   * - 依赖调度的动作列表在其中一个动作抛出异常时仍被记为已运行
     - 该次运行现在是 ``failed``，并发布 ``scheduler.error``。列表的其余部分仍会运行。
   * - 为动作服务器设置了 ``ActionACL``
     - 请检查你的允许列表：嵌套在另一个动作参数中的动作（``FA_execute_action``、
       流水线定义、调度的列表）现在也会被检查，因此同样必须被允许。
   * - 以 ``--allowed-actions`` 限缩了 MCP 服务器
     - 同样适用：工具不能再运行服务器没有开放的动作。
   * - 比对通知 sink 的错误文字
     - 其中的 URL 现在只保留主机部分，路径中的令牌不会显示出来。
   * - 导入 ``HomeTab`` 或 ``SchedulerTab`` 来嵌入它们
     - 它们仍然可以导入，但窗口不再挂载它们；Dashboard 与 Scheduler 页面取代了它们。

本次发布的其余内容都是新增的功能。

旧接口与新接口
--------------

两栏都受到支持。左栏没有任何东西被弃用。

.. list-table::
   :header-rows: 1
   :widths: 30 34 36

   * - 旧接口
     - 新接口
     - 何时优先采用新接口
   * - ``FA_s3_upload_file``、``FA_sftp_download_file`` 以及其他各后端专属的动作
     - ``File`` / ``Storage`` 与 ``FA_storage_*``（:doc:`storage`）
     - 同一份代码要能用在不止一种后端，或者你想要有类型的错误、审计轨迹与事件
   * - ``copy_between`` / ``FA_copy_between``
     - ``File(source).copy_to(target)``、``FA_storage_copy``
     - 你想要的是异常而不是 ``False``，并且想获得结果的描述
   * - ``write_manifest`` / ``verify_manifest``
     - ``IntegrityMonitor``（:doc:`integrity`）
     - 目录树不在本地，或者你需要检测重命名、元数据变更、监听，或经过核准的基准
   * - ``IntegrityMonitor(root, manifest_path, …)`` 与 ``check_once()``
     - ``IntegrityMonitor(target, baseline=…)`` 搭配 ``verify()``、``accept()``
     - 你想要 ``DriftReport`` 而不是摘要字典。由 ``accept()`` 或 ``create_baseline()``
       写出的基准，``verify_manifest`` 无法再读取
   * - ``execute_action_dag``
     - ``Pipeline``（:doc:`pipeline`）
     - 你需要重试、超时、崩溃后续跑，或运行历史
   * - ``AuditLog``
     - ``configure_audit`` 与 ``audit_search``（:doc:`audit`）
     - 你希望每个事件与每次存储操作都被记录，而不必自己调用 ``record``。
       ``SQLiteAuditStore.import_v1()`` 可以复制旧的行
   * - ``notification_manager.notify`` 与 ``notify_on_failure``
     - 通知路由（:doc:`notifications`）
     - 不同的事件要送到不同的 sink，并各有自己的去重与限流
   * - 以 cron 表达式调用 ``FA_schedule_add``
     - ``FA_schedule_job``、``FA_schedule_pipeline`` 与各种触发条件（:doc:`scheduler`）
     - 作业要按某个时区运行、由事件触发、接在另一条流水线之后，或要运行流水线
   * - MCP 服务器的 ``FA_*`` 工具
     - 语义化工具（:doc:`mcp`）
     - AI 宿主应该被限制在指定的位置之内，并从只读开始
   * - GUI 中各后端专属的页签
     - 按工作流组织的页面；原本的页签放在 Advanced 之下（:doc:`gui`）
     - 一律优先，除非你需要某个后端专属的操作

原本会收到的通知
----------------

有两个组件过去会直接通知整个进程共用的 ``notification_manager``，现在仍然如此：完整性
监控在检测到偏移时，以及 ``notify_on_failure`` 在触发或调度失败时。一旦你启动了通知
路由器，这些事件就改由它的路由送达，直接通知随之停止，因此同一件事不会被通知两次。
如果你启动了路由器，请为你原本会被告知的事件（``integrity.violation``、
``scheduler.error``、``system.error``）加上路由；否则它们会被发布，却送不到任何 sink。

升级生产环境之前
----------------

1. 在全新的环境中安装新版本以及你需要的 extra。
2. 以 ``-W error::DeprecationWarning`` 运行你的测试。
3. 运行 ``python -m automation_file storage schemes``，并对你使用的每一种后端做一次真实的
   传输。
4. 如果动作服务器设有 ``ActionACL``，请把你的客户端会发送的每一种请求各发送一次。
5. 按照 :doc:`deployment` 安排现在应该保存在文件中的状态（审计轨迹、流水线运行记录）。
