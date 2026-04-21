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

CLI
---

.. code-block:: bash

   python -m automation_file --execute_file actions.json
   python -m automation_file --execute_dir ./actions/
   python -m automation_file --execute_str '[["FA_create_dir",{"dir_path":"x"}]]'
   python -m automation_file --create_project ./my_project

Google Drive
------------

Obtain OAuth2 credentials from Google Cloud Console, download
``credentials.json``, then:

.. code-block:: python

   from automation_file import driver_instance, drive_upload_to_drive

   driver_instance.later_init("token.json", "credentials.json")
   drive_upload_to_drive("example.txt")

After the first successful login the refresh token is stored at the path you
gave as ``token.json``; subsequent runs skip the browser flow.

TCP action server
-----------------

.. code-block:: python

   from automation_file import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(host="localhost", port=9943)
   # later:
   server.shutdown()
   server.server_close()

The server is **loopback-only** unless you pass ``allow_non_loopback=True``.
Each connection receives one JSON action list, executes it, streams results
back, then writes the end marker ``Return_Data_Over_JE\\n``.

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
   untrusted input (e.g. via the TCP server).
