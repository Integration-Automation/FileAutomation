Usage
=====

JSON action lists
-----------------

An action is one of three shapes:

.. code-block:: json

   ["FA_name"]
   ["FA_name", {"kwarg": "value"}]
   ["FA_name", ["positional", "args"]]

An action list is an array of actions. The executor runs them in order and
returns a mapping of ``"execute: <action>" -> result | repr(error)``.

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

CLI
---

Legacy flags for running JSON action lists::

   python -m automation_file --execute_file actions.json
   python -m automation_file --execute_dir ./actions/
   python -m automation_file --execute_str '[["FA_create_dir",{"dir_path":"x"}]]'
   python -m automation_file --create_project ./my_project

Subcommands for one-shot operations::

   python -m automation_file zip ./src out.zip --dir
   python -m automation_file unzip out.zip ./restored
   python -m automation_file download https://example.com/file.bin file.bin
   python -m automation_file create-file hello.txt --content "hi"
   python -m automation_file server --host 127.0.0.1 --port 9943
   python -m automation_file http-server --host 127.0.0.1 --port 9944
   python -m automation_file drive-upload my.txt --token token.json --credentials creds.json

Google Drive
------------

.. code-block:: python

   from automation_file import driver_instance, drive_upload_to_drive

   driver_instance.later_init("token.json", "credentials.json")
   drive_upload_to_drive("example.txt")

TCP action server
-----------------

.. code-block:: python

   from automation_file import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(
       host="localhost", port=9943, shared_secret="optional-secret",
   )
   # later:
   server.shutdown()
   server.server_close()

When ``shared_secret`` is supplied, the client must prefix each payload with
``AUTH <secret>\\n`` before the JSON action list. The server still binds to
loopback by default and refuses non-loopback binds unless
``allow_non_loopback=True`` is passed.

HTTP action server
------------------

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(
       host="127.0.0.1", port=9944, shared_secret="optional-secret",
   )

   # Client side:
   # curl -H 'Authorization: Bearer optional-secret' \
   #      -d '[["FA_create_dir",{"dir_path":"x"}]]' \
   #      http://127.0.0.1:9944/actions

HTTP responses are JSON. When ``shared_secret`` is set the client must send
``Authorization: Bearer <secret>``.

Reliability
-----------

Apply retries to your own callables:

.. code-block:: python

   from automation_file import retry_on_transient

   @retry_on_transient(max_attempts=5, backoff_base=0.5)
   def flaky_network_call(): ...

Enforce per-action limits:

.. code-block:: python

   from automation_file import Quota

   quota = Quota(max_bytes=50 * 1024 * 1024, max_seconds=30.0)
   with quota.time_budget("bulk-upload"):
       bulk_upload_work()

Path safety
-----------

.. code-block:: python

   from automation_file import safe_join

   target = safe_join("/data/jobs", user_supplied_path)
   # -> raises PathTraversalException if the resolved path escapes /data/jobs.

Optional cloud backends
-----------------------

.. code-block:: bash

   pip install "automation_file[s3]"
   pip install "automation_file[azure]"
   pip install "automation_file[dropbox]"
   pip install "automation_file[sftp]"

After installing, register the actions on the shared executor:

.. code-block:: python

   from automation_file import executor
   from automation_file.remote.s3 import register_s3_ops, s3_instance

   register_s3_ops(executor.registry)
   s3_instance.later_init(region_name="us-east-1")

All backends expose the same five operations:
``upload_file``, ``upload_dir``, ``download_file``, ``delete_*``, ``list_*``.

SFTP specifically uses :class:`paramiko.RejectPolicy` — unknown hosts are
rejected rather than auto-added. Provide ``known_hosts`` explicitly or rely on
``~/.ssh/known_hosts``.

Adding your own commands
------------------------

.. code-block:: python

   from automation_file import add_command_to_executor, execute_action

   def greet(name: str) -> str:
       return f"hello {name}"

   add_command_to_executor({"greet": greet})
   execute_action([["greet", {"name": "world"}]])

Dynamic package registration
----------------------------

.. code-block:: python

   from automation_file import package_manager, execute_action

   package_manager.add_package_to_executor("math")
   execute_action([["math_sqrt", [16.0]]])   # -> 4.0

.. warning::

   ``package_manager.add_package_to_executor`` effectively registers every
   top-level function / class / builtin of a package. Do not expose it to
   untrusted input (e.g. via the TCP or HTTP servers).
