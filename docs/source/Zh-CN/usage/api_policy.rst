公开 API 与兼容性
==================

本页说明哪些东西可以依赖、版本号如何告诉你改了什么，以及一个名称如何退场。
这是 1.0 版背后的契约。

哪些是公开的
------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 接口
     - 涵盖范围
   * - Python 名称
     - ``automation_file.__all__`` 中的所有名称，以及下列已写入文档的包其
       ``__all__`` 中的所有名称：``automation_file.storage``、
       ``automation_file.events``、``automation_file.pipeline``、
       ``automation_file.integrity``、``automation_file.audit``、
       ``automation_file.notify``、``automation_file.scheduler``。这包含名称本身、
       它的参数、返回值，以及文档中记载的异常。
   * - 动作
     - 每一个 ``FA_*`` 动作的名称、参数与结果的形状。今天写下的动作列表之后仍然能运行。
   * - 命令行
     - ``python -m automation_file`` 的子命令与选项、JSON 输出的形状，以及退出码。
   * - 存储 URI
     - 语法（:doc:`storage`）、内置的 scheme 及其别名。
   * - 数据格式
     - 流水线定义（``schema_version: 1``）、完整性 manifest（``schema_version: 2``）、
       审计记录及其 SQLite 结构（第 2 版）、配置文件。
   * - 事件
     - 每一种核心事件的类型名称（``pipeline.failed`` 等）、严重程度与 payload 的键
       （:doc:`event_bus`）。
   * - 异常
     - ``FileAutomationException`` 之下的层级：一个错误属于哪个类，以及它继承自
       哪些类。
   * - 扩展点
     - ``StorageBackend`` 子类要重写的方法，``AuditStore``、``RunStore`` 与
       ``NotificationSink`` 接口，以及 ``automation_file.actions`` 入口点。

哪些不是公开的
--------------

* 任何模块中以下划线开头的名称。
* 公开名称所在的模块。请从 ``automation_file`` 或 ``automation_file.storage`` 导入
  ``S3Storage``；``automation_file.storage.s3_storage`` 这个路径可能会变。
* 错误消息与日志的确切文字。请依赖异常类与它的属性。
* GUI 的 widget 类。
* ``tests/`` 之下的一切，包含各种替身。存储契约测试套件
  （``tests/storage_contract.py``）是提供给后端作者使用的，但它是测试代码，
  随着代码仓库而不是随着包的发行版本演进。

稳定等级
--------

稳定（Stable）
    受以下所有规则保障。自 1.0 起包含：``StorageBackend`` 与存储 URI 语法、
    ``File`` 与 ``Storage``、``Pipeline`` 及其定义格式、``IntegrityMonitor`` 及其
    manifest、事件模型、审计记录与 ``AuditStore``、``FA_*`` 动作，以及命令行。

暂定（Provisional）
    新功能，仍可能在次版本中变动，变动会列在版本说明中。暂定的功能会在其手册页面
    开头标示。在 1.0 之前，存储层、事件总线、流水线运行环境、完整性监控、审计轨迹、
    通知路由器与语义化 MCP 工具都属于暂定。

私有（Private）
    `哪些不是公开的`_ 列出的一切。它们会在没有通知的情况下变动。

版本号
------

版本采用语义化版本，``MAJOR.MINOR.PATCH``。

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - 部分
     - 何时递增
   * - ``PATCH``
     - 修复错误。没有任何公开的东西被新增、移除或改变含义。
   * - ``MINOR``
     - 新增功能、暂定功能有所变动，或有东西被标为弃用。为前一个次版本写的代码仍然
       能运行。
   * - ``MAJOR``
     - 稳定的东西被移除，或以既有代码能察觉的方式改变。版本说明会附上迁移指南。

有两种情况各值得一句话。**安全修复** 可以在修订版中改变行为，只要保留原行为就等于
保留漏洞；版本说明会注明。而 **0.x 版** 还在契约之前：下一个次版本可以改动任何东西，
不过 ``FA_*`` 动作一路以来都保持兼容。

支持的 Python 版本是上游仍提供安全修复的 CPython 版本。停止支持已到生命周期终点的
版本属于次版本变动。

名称如何退场
------------

1. 某个次版本把名称标为弃用。它的运行与以往完全相同，每次使用都会发出
   ``DeprecationWarning``，说明它在哪个版本被弃用、哪个版本会移除，以及替代方案。
   同一条消息在每个进程中也会写入日志一次，因为 Python 在 ``__main__`` 之外会隐藏
   这种警告，而由 JSON 运行的动作列表永远看不到它。被弃用的 ``FA_*`` 动作仍然保持
   注册。
2. 手册与版本说明会列出它以及替代方案。
3. 它至少保留两个次版本。
4. 只有主版本才会移除它。

整个代码库都用同一种方式发出这个警告：

.. code-block:: python

   from automation_file.core.deprecation import deprecated, warn_deprecated

   @deprecated(since="1.2", removal="2.0", replacement="automation_file.File.copy_to")
   def copy_between(source, target):
       ...

   def start(self, *, legacy_flag=None):
       if legacy_flag is not None:
           warn_deprecated("the 'legacy_flag' argument", since="1.2", removal="2.0")

要找出你自己的代码用到哪些已弃用的名称，请把警告当成错误来运行测试::

   python -W error::DeprecationWarning -m pytest

撰写本文时没有任何东西被弃用。已有较新对应物的旧接口（``copy_between`` 与
``File.copy_to``、``AuditLog`` 与审计轨迹、``execute_action_dag`` 与 ``Pipeline``）
全部并行支持。

数据格式
--------

写入磁盘的格式都带有版本，读取端遇到不认识的版本会直接拒绝而不是猜测：
``schema_version: 3`` 的 manifest 目前会抛出 ``IntegrityException``，
``schema_version`` 不明的流水线定义会由 ``validate_definition`` 报告。当某个格式推出新
版本时，引入它的那个发行版本仍然读得懂前一个版本，并说明如何转换。

出现问题时
----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 你看到的
     - 代表什么、该怎么做
   * - ``DeprecationWarning: … is deprecated since 1.2 and will be removed in 2.0; use … instead``
     - 这个名称仍然可用。请在消息所说的版本之前改用替代方案。
   * - 升级后某个模块路径的导入失败
     - 那个路径不是公开的。请从 ``automation_file`` 或它已写入文档的包导入该名称。
   * - 升级后，一个比对错误消息的测试失败
     - 消息文字不属于契约。请比对异常类，或只比对你真正依赖的部分。
   * - ``… has manifest schema version 3``
     - 这个文件是由较新的版本写出的。请升级读取它的包。
