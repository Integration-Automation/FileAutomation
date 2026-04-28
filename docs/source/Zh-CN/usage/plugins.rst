插件与动态注册
==============

入口点插件
----------

第三方包可以通过在 ``pyproject.toml`` 声明
``automation_file.actions`` 入口点，注册自己的 ``FA_*`` 命令::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

其中 ``register`` 是一个零参可调用对象，返回
``Mapping[str, Callable]``。一旦插件安装到同一个 venv，
:func:`~automation_file.core.action_registry.build_default_registry`
会自动拾取——调用方无需任何改动：

.. code-block:: python

   # my_plugin/__init__.py
   def greet(name: str) -> str:
       return f"hello {name}"

   def register() -> dict:
       return {"FA_greet": greet}

.. code-block:: python

   # 安装后的消费方代码：
   from automation_file import execute_action
   execute_action([["FA_greet", {"name": "world"}]])

插件失败（导入错误、工厂异常、返回形状不对、被注册表拒绝）
会被记录并吞掉，单个坏插件不会拖垮整个库。

动态包注册
----------

.. code-block:: python

   from automation_file import package_manager, execute_action

   package_manager.add_package_to_executor("math")
   execute_action([["math_sqrt", [16.0]]])   # -> 4.0

.. warning::

   ``package_manager.add_package_to_executor`` 会注册任意包的全部
   顶层函数 / 类 / 内置。**切勿** 暴露给不可信输入
   （例如通过 TCP、HTTP 或 :doc:`mcp` 服务器）。
