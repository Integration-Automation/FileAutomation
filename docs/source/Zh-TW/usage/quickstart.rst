快速開始
========

物件 API
--------

大多數程式只需要四個名稱：``File`` 與 ``Storage``（:doc:`storage`）、
``IntegrityMonitor``（:doc:`integrity`）以及 ``Pipeline``（:doc:`pipeline`）。

.. code-block:: python

   from automation_file import File, IntegrityMonitor, Pipeline, Storage

   # 每一種後端都用同一套 API：一般路徑或儲存 URI。
   report = File("memory://demo/reports/q1.csv")
   report.write(b"region,total\nnorth,42\n")
   report.copy_to("/srv/demo/q1.csv")                          # 任何後端之間都能複製
   [entry.path for entry in Storage("/srv/demo").list_dir()]   # ['q1.csv']
   print(File("/srv/demo/q1.csv").checksum())                  # sha256:8372…

   # 這棵目錄樹是否仍與核可時相同？
   monitor = IntegrityMonitor("/srv/demo", baseline="/srv/demo.baseline.json")
   monitor.create_baseline()
   monitor.verify().ok                                         # True

   # 具有相依關係、重試與執行紀錄的步驟。
   pipeline = Pipeline("publish")
   pipeline.task("copy", ["FA_storage_copy", {"source": "memory://demo/reports/q1.csv",
                                              "target": "memory://demo/published/q1.csv"}])
   pipeline.task("check", ["FA_storage_exists", {"uri": "memory://demo/published/q1.csv"}],
                 depends_on=["copy"])
   pipeline.run().status                                       # RunStatus.SUCCEEDED

只要安裝了對應的 extra（``pip install "automation_file[s3]"``）並初始化其用戶端，
就可以把 ``memory://`` 與本機路徑換成 ``s3://bucket/key``、``sftp://host/path``
或任何其他後端。

下面的 JSON 動作清單是同一組操作的資料寫法，可用於設定檔、動作伺服器與命令列。

JSON 動作清單
-------------

動作可採用三種形狀之一：

.. code-block:: json

   ["FA_name"]
   ["FA_name", {"kwarg": "value"}]
   ["FA_name", ["positional", "args"]]

動作清單是動作的陣列。執行器依序執行並回傳
``"execute[<index>]: <action>" -> result | repr(error)`` 的對應表。

.. code-block:: python

   from automation_file import execute_action, read_action_json

   results = execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir", {"dir_we_want_to_zip": "build", "zip_name": "build_snapshot"}],
   ])

   # 或從檔案載入：
   results = execute_action(read_action_json("actions.json"))

驗證、dry-run、平行執行
-----------------------

.. code-block:: python

   from automation_file import (
       execute_action, execute_action_parallel, validate_action,
   )

   # Fail-fast 驗證：若有未知名稱，執行前即中止整批。
   execute_action(actions, validate_first=True)

   # Dry-run：記錄將呼叫什麼但不實際呼叫。
   execute_action(actions, dry_run=True)

   # 平行：透過執行緒池執行彼此獨立的動作。
   execute_action_parallel(actions, max_workers=4)

   # 手動驗證——回傳已解析的名稱清單。
   names = validate_action(actions)

註冊自訂動作
------------

.. code-block:: python

   from automation_file import add_command_to_executor, execute_action

   def greet(name: str) -> str:
       return f"hello {name}"

   add_command_to_executor({"greet": greet})
   execute_action([["greet", {"name": "world"}]])

進入點打包與動態套件註冊請見 :doc:`plugins`。
