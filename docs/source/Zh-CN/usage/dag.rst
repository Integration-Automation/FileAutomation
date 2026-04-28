DAG 动作执行器
==============

:func:`~automation_file.execute_action_dag` 按依赖顺序运行动作。
每个节点形如 ``{"id": str, "action": [name, ...], "depends_on":
[id, ...]}``。互不依赖的分支通过线程池并行展开；
当节点失败时，其传递依赖的下游会被标记为 ``skipped``
（默认 ``fail_fast=True``）或仍然继续运行（``fail_fast=False``）：

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

环、未知依赖、自环依赖与重复 id 都会在任何节点运行前抛出
:class:`~automation_file.exceptions.DagException`。
JSON 形式：``FA_execute_action_dag``。
