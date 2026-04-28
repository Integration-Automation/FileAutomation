Quickstart
==========

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
