DAG action executor
===================

:func:`~automation_file.execute_action_dag` runs actions in dependency
order. Each node is ``{"id": str, "action": [name, ...], "depends_on":
[id, ...]}``. Independent branches fan out across a thread pool; when a
node fails, its transitive dependents are marked ``skipped``
(``fail_fast=True``, the default) or still run (``fail_fast=False``):

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

Cycles, unknown dependencies, self-dependencies, and duplicate ids raise
:class:`~automation_file.exceptions.DagException` before any node runs.
The JSON-action form is ``FA_execute_action_dag``.
