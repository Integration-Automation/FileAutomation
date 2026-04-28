DAG 動作執行器
==============

:func:`~automation_file.execute_action_dag` 依相依順序執行動作。
每個節點形如 ``{"id": str, "action": [name, ...], "depends_on":
[id, ...]}``。互不相依的分支會透過執行緒池平行展開；
當節點失敗時，其遞移相依的下游會被標記為 ``skipped``
（預設 ``fail_fast=True``）或仍然執行（``fail_fast=False``）：

.. code-block:: python

   from automation_file import execute_action_dag

   results = execute_action_dag([
       {"id": "fetch",  "action": ["FA_download_file",
                                   ["https://example.com/src.tar.gz", "src.tar.gz"]]},
       {"id": "verify", "action": ["FA_verify_checksum",
                                   ["src.tar.gz", "3b0c44298fc1..."]],
                        "depends_on": ["fetch"]},
       {"id": "unpack", "action": ["FA_unzip_file", ["src.tar.gz", "src"]],
                        "depends_on": ["verify"]},
       {"id": "report", "action": ["FA_fast_find", ["src", "*.py"]],
                        "depends_on": ["unpack"]},
   ])

迴圈、未知相依、自相依與重複 id 都會在任何節點執行前擲出
:class:`~automation_file.exceptions.DagException`。
JSON 形式：``FA_execute_action_dag``。
