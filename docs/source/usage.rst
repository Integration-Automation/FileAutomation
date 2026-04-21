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

   python -m automation_file ui
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

Cloud / SFTP backends
---------------------

Every backend (S3, Azure Blob, Dropbox, SFTP) is bundled with ``automation_file``
and auto-registered by :func:`~automation_file.core.action_registry.build_default_registry`.
There is no extra install step — call ``later_init`` on the singleton and go:

.. code-block:: python

   from automation_file import execute_action, s3_instance

   s3_instance.later_init(region_name="us-east-1")

   execute_action([
       ["FA_s3_upload_file", {"local_path": "report.csv", "bucket": "reports", "key": "report.csv"}],
   ])

All backends expose the same five operations:
``upload_file``, ``upload_dir``, ``download_file``, ``delete_*``, ``list_*``.
``register_<backend>_ops(registry)`` is still public for callers that build
custom registries.

SFTP specifically uses :class:`paramiko.RejectPolicy` — unknown hosts are
rejected rather than auto-added. Provide ``known_hosts`` explicitly or rely on
``~/.ssh/known_hosts``.

File-watcher triggers
---------------------

Run an action list whenever a filesystem event fires on a watched path. The
module-level :data:`~automation_file.trigger.trigger_manager` keeps a named
registry of active watchers so the JSON facade and the GUI share one
lifecycle.

.. code-block:: python

   from automation_file import watch_start, watch_stop

   watch_start(
       name="inbox-sweeper",
       path="/data/inbox",
       action_list=[["FA_copy_all_file_to_dir", {"source_dir": "/data/inbox",
                                                 "target_dir": "/data/processed"}]],
       events=["created", "modified"],
       recursive=False,
   )
   # later:
   watch_stop("inbox-sweeper")

Or drive it from a JSON action list with ``FA_watch_start`` /
``FA_watch_stop`` / ``FA_watch_stop_all`` / ``FA_watch_list``.

Cron scheduler
--------------

Run an action list on a recurring schedule. The 5-field cron parser supports
``*``, exact values, ``a-b`` ranges, comma-separated lists, and ``*/n`` step
syntax with ``jan``..``dec`` / ``sun``..``sat`` aliases.

.. code-block:: python

   from automation_file import schedule_add

   schedule_add(
       name="nightly-snapshot",
       cron_expression="0 2 * * *",           # every day at 02:00 local time
       action_list=[["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                                    "zip_name": "/backup/data_nightly"}]],
   )

A background thread wakes on minute boundaries, so expressions with
sub-minute precision are not supported. Use ``FA_schedule_add`` /
``FA_schedule_remove`` / ``FA_schedule_remove_all`` / ``FA_schedule_list``
from JSON.

Transfer progress + cancellation
--------------------------------

Pass ``progress_name="<label>"`` to :func:`download_file`,
:func:`s3_upload_file`, or :func:`s3_download_file` to register the transfer
with the shared progress registry. The GUI's **Progress** tab polls the
registry every half second; ``FA_progress_list``, ``FA_progress_cancel``,
and ``FA_progress_clear`` give JSON action lists the same view.

.. code-block:: python

   from automation_file import download_file, progress_cancel

   # In one thread:
   download_file("https://example.com/big.bin", "big.bin",
                 progress_name="big-download")

   # In another thread / from the GUI:
   progress_cancel("big-download")

Cancellation raises :class:`~automation_file.CancelledException` inside the
transfer loop. The transfer function catches it, marks the reporter
``status="cancelled"``, and returns ``False`` — callers don't need to handle
the exception themselves.

Fast file search
----------------

:func:`fast_find` picks the cheapest backend available on the host — OS
index first, streaming scandir walk as a fallback — so large trees are
searched with minimal energy:

* macOS: ``mdfind`` (Spotlight)
* Linux: ``plocate`` / ``locate`` database
* Windows: Everything's ``es.exe`` CLI, if installed
* Fallback: ``os.scandir`` generator with ``fnmatch`` matching and early
  termination via ``limit=``

.. code-block:: python

   from automation_file import fast_find, scandir_find, has_os_index

   # Query an indexer when available, fall back to scandir otherwise.
   results = fast_find("/var/log", "*.log", limit=100)

   # Force the portable path (skip the OS indexer).
   results = fast_find("/data", "report_*.csv", use_index=False)

   # Streaming generator — stop early without scanning the whole tree.
   for path in scandir_find("/data", "*.csv"):
       if "2026" in path:
           break

   # Which indexer will fast_find try?  Returns "mdfind" / "locate" /
   # "plocate" / "es" / None.
   has_os_index()

The same action is available to JSON action lists as ``FA_fast_find``:

.. code-block:: json

   [["FA_fast_find", {"root": "/var/log", "pattern": "*.log", "limit": 50}]]

Checksums and integrity verification
------------------------------------

Hash any file with a streaming reader (any :mod:`hashlib` algorithm) and
verify it against an expected digest using constant-time comparison:

.. code-block:: python

   from automation_file import file_checksum, verify_checksum

   digest = file_checksum("bundle.tar.gz")                 # sha256 by default
   verify_checksum("bundle.tar.gz", digest)                # -> True
   verify_checksum("bundle.tar.gz", "deadbeef...", algorithm="blake2b")

The same functions are available to JSON action lists as
``FA_file_checksum`` and ``FA_verify_checksum``.

Resumable HTTP downloads
------------------------

:func:`~automation_file.download_file` accepts ``resume=True``. Bytes are
written to ``<target>.part``; if the tempfile already exists the next call
sends ``Range: bytes=<n>-`` so the transfer picks up where it left off.
Combined with ``expected_sha256=`` the download is verified immediately
after the last chunk is written:

.. code-block:: python

   from automation_file import download_file

   download_file(
       "https://example.com/big.bin",
       "big.bin",
       resume=True,
       expected_sha256="3b0c44298fc1...",
   )

File deduplication
------------------

:func:`~automation_file.find_duplicates` walks a tree once with
``os.scandir`` and runs a three-stage size → partial-hash → full-hash
pipeline. Files with unique sizes are eliminated without being hashed at
all, so a tree of millions of files is cheap to scan:

.. code-block:: python

   from automation_file import find_duplicates

   groups = find_duplicates("/data", min_size=1024)
   # groups: list[list[str]], each inner list is a set of identical files
   # sorted by size descending.

``FA_find_duplicates`` exposes the same call to JSON action lists.

DAG action executor
-------------------

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

Entry-point plugins
-------------------

Third-party packages can register their own ``FA_*`` commands by
declaring an ``automation_file.actions`` entry point in their
``pyproject.toml``::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

where ``register`` is a zero-argument callable returning a
``Mapping[str, Callable]``. Once the plugin is installed into the same
virtual environment,
:func:`~automation_file.core.action_registry.build_default_registry`
picks it up automatically — no caller changes required:

.. code-block:: python

   # my_plugin/__init__.py
   def greet(name: str) -> str:
       return f"hello {name}"

   def register() -> dict:
       return {"FA_greet": greet}

.. code-block:: python

   # consumer code, after `pip install my_plugin`
   from automation_file import execute_action
   execute_action([["FA_greet", {"name": "world"}]])

Plugin failures (import errors, factory exceptions, wrong return shape,
registry rejection) are logged and swallowed so one broken plugin cannot
break the library.

GUI (PySide6)
-------------

A tabbed control surface wraps every feature:

.. code-block:: bash

   python -m automation_file ui
   # or from the repo root during development:
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

Tabs: Home, Local, Transfer, Progress, JSON actions, Triggers, Scheduler,
Servers. A persistent log panel below the tabs streams every call's result or
error. Background work runs on ``QThreadPool`` via ``ActionWorker`` so the UI
stays responsive.

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
