快速开始
========

对象 API
--------

大多数程序只需要四个名称：``File`` 与 ``Storage``（:doc:`storage`）、
``IntegrityMonitor``（:doc:`integrity`）以及 ``Pipeline``（:doc:`pipeline`）。

.. code-block:: python

   from automation_file import File, IntegrityMonitor, Pipeline, Storage

   # 每一种后端都用同一套 API：普通路径或存储 URI。
   report = File("memory://demo/reports/q1.csv")
   report.write(b"region,total\nnorth,42\n")
   report.copy_to("/srv/demo/q1.csv")                          # 任何后端之间都能复制
   [entry.path for entry in Storage("/srv/demo").list_dir()]   # ['q1.csv']
   print(File("/srv/demo/q1.csv").checksum())                  # sha256:8372…

   # 这棵目录树是否仍与核准时相同？
   monitor = IntegrityMonitor("/srv/demo", baseline="/srv/demo.baseline.json")
   monitor.create_baseline()
   monitor.verify().ok                                         # True

   # 具有依赖关系、重试与运行记录的步骤。
   pipeline = Pipeline("publish")
   pipeline.task("copy", ["FA_storage_copy", {"source": "memory://demo/reports/q1.csv",
                                              "target": "memory://demo/published/q1.csv"}])
   pipeline.task("check", ["FA_storage_exists", {"uri": "memory://demo/published/q1.csv"}],
                 depends_on=["copy"])
   pipeline.run().status                                       # RunStatus.SUCCEEDED

只要安装了对应的 extra（``pip install "automation_file[s3]"``）并初始化其客户端，
就可以把 ``memory://`` 与本地路径换成 ``s3://bucket/key``、``sftp://host/path``
或任何其他后端。

下面的 JSON 动作列表是同一组操作的数据写法，可用于配置文件、动作服务器与命令行。

JSON 动作列表
-------------

动作可采用三种形状之一：

.. code-block:: json

   ["FA_name"]
   ["FA_name", {"kwarg": "value"}]
   ["FA_name", ["positional", "args"]]

动作列表是动作的数组。执行器按顺序执行并返回
``"execute[<index>]: <action>" -> result | repr(error)`` 的映射表。

.. code-block:: python

   from automation_file import execute_action, read_action_json

   results = execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir", {"dir_we_want_to_zip": "build", "zip_name": "build_snapshot"}],
   ])

   # 或从文件读入：
   results = execute_action(read_action_json("actions.json"))

校验、dry-run、并行执行
-----------------------

.. code-block:: python

   from automation_file import (
       execute_action, execute_action_parallel, validate_action,
   )

   # Fail-fast 校验：若有未知名称，执行前即中止整批。
   execute_action(actions, validate_first=True)

   # Dry-run：记录将调用什么但不实际调用。
   execute_action(actions, dry_run=True)

   # 并行：通过线程池执行彼此独立的动作。
   execute_action_parallel(actions, max_workers=4)

   # 手动校验——返回已解析的名称列表。
   names = validate_action(actions)

注册自定义动作
--------------

.. code-block:: python

   from automation_file import add_command_to_executor, execute_action

   def greet(name: str) -> str:
       return f"hello {name}"

   add_command_to_executor({"greet": greet})
   execute_action([["greet", {"name": "world"}]])

入口点打包与动态包注册详见 :doc:`plugins`。
