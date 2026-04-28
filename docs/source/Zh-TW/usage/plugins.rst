外掛與動態註冊
==============

進入點外掛
----------

第三方套件可在 ``pyproject.toml`` 宣告
``automation_file.actions`` 進入點，註冊自家的 ``FA_*`` 命令::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

其中 ``register`` 是零參可呼叫物件，回傳
``Mapping[str, Callable]``。一旦外掛安裝到同一個 venv，
:func:`~automation_file.core.action_registry.build_default_registry`
會自動拾取——呼叫端無需任何更動：

.. code-block:: python

   # my_plugin/__init__.py
   def greet(name: str) -> str:
       return f"hello {name}"

   def register() -> dict:
       return {"FA_greet": greet}

.. code-block:: python

   # 安裝後的呼叫端：
   from automation_file import execute_action
   execute_action([["FA_greet", {"name": "world"}]])

外掛失敗（匯入錯誤、工廠例外、回傳形狀錯誤、被註冊表拒絕）
會被記錄並吞掉，單一壞外掛不會拖垮整個函式庫。

動態套件註冊
------------

.. code-block:: python

   from automation_file import package_manager, execute_action

   package_manager.add_package_to_executor("math")
   execute_action([["math_sqrt", [16.0]]])   # -> 4.0

.. warning::

   ``package_manager.add_package_to_executor`` 會註冊任意套件的所有
   頂層函式 / 類別 / 內建。**切勿** 暴露給不可信任的輸入
   （例如透過 TCP、HTTP 或 :doc:`mcp` 伺服器）。
