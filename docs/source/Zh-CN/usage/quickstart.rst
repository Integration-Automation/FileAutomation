快速开始
========

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
