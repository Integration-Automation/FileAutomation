Quickstart
==========

The object API
--------------

Four names carry most programs: ``File`` and ``Storage`` (:doc:`storage`),
``IntegrityMonitor`` (:doc:`integrity`) and ``Pipeline`` (:doc:`pipeline`).

.. code-block:: python

   from automation_file import File, IntegrityMonitor, Pipeline, Storage

   # One API for every backend: a plain path or a storage URI.
   report = File("memory://demo/reports/q1.csv")
   report.write(b"region,total\nnorth,42\n")
   report.copy_to("/srv/demo/q1.csv")                          # any backend to any other
   [entry.path for entry in Storage("/srv/demo").list_dir()]   # ['q1.csv']
   print(File("/srv/demo/q1.csv").checksum())                  # sha256:8372…

   # Is the tree still what was approved?
   monitor = IntegrityMonitor("/srv/demo", baseline="/srv/demo.baseline.json")
   monitor.create_baseline()
   monitor.verify().ok                                         # True

   # Steps with dependencies, retries and a recorded history.
   pipeline = Pipeline("publish")
   pipeline.task("copy", ["FA_storage_copy", {"source": "memory://demo/reports/q1.csv",
                                              "target": "memory://demo/published/q1.csv"}])
   pipeline.task("check", ["FA_storage_exists", {"uri": "memory://demo/published/q1.csv"}],
                 depends_on=["copy"])
   pipeline.run().status                                       # RunStatus.SUCCEEDED

Replace ``memory://`` and the local path with ``s3://bucket/key``,
``sftp://host/path`` or any other backend once its extra is installed
(``pip install "automation_file[s3]"``) and its client is initialised.

The JSON action lists below are the same operations written as data. Use them
from configuration files, the action servers and the command line.

JSON action lists
-----------------

An action is one of three shapes:

.. code-block:: json

   ["FA_name"]
   ["FA_name", {"kwarg": "value"}]
   ["FA_name", ["positional", "args"]]

An action list is an array of actions. The executor runs them in order and
returns a mapping of ``"execute[<index>]: <action>" -> result | repr(error)``.

.. code-block:: python

   from automation_file import execute_action, read_action_json

   results = execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir", {"dir_we_want_to_zip": "build", "zip_name": "build_snapshot"}],
   ])

   # Or load from a file:
   results = execute_action(read_action_json("actions.json"))

Validation, dry-run, parallel
-----------------------------

.. code-block:: python

   from automation_file import (
       execute_action, execute_action_parallel, validate_action,
   )

   # Fail-fast validation: aborts before any action runs if any name is unknown.
   execute_action(actions, validate_first=True)

   # Dry-run: log what would be called without invoking commands.
   execute_action(actions, dry_run=True)

   # Parallel: run independent actions through a thread pool.
   execute_action_parallel(actions, max_workers=4)

   # Manual validation — returns the list of resolved names.
   names = validate_action(actions)

Adding your own commands
------------------------

.. code-block:: python

   from automation_file import add_command_to_executor, execute_action

   def greet(name: str) -> str:
       return f"hello {name}"

   add_command_to_executor({"greet": greet})
   execute_action([["greet", {"name": "world"}]])

See :doc:`plugins` for entry-point packaging and dynamic package registration.
