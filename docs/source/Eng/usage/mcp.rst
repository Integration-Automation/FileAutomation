MCP server
==========

``automation_file`` ships a Model Context Protocol (MCP) server, so an AI client
such as **Claude Desktop** or **Claude Code** can work with files through it. The
transport is stdio: one JSON-RPC 2.0 message per line.

The server offers two sets of tools:

* the **semantic tools**: fourteen stable, task-shaped tools (``file_read``,
  ``file_copy``, ``pipeline_run``, ...) that work on :doc:`storage URIs <storage>`
  and are bound by a permission policy. This is the interface meant for AI
  clients;
* the **bridge**: every registered ``FA_*`` action as a tool of its own, as in
  earlier versions. It is on by default for compatibility and is **not** bound by
  the policy.

The defaults are safe for the semantic tools: no location is allowed, nothing can
be changed, and every answer is bounded in size.

Minimal setup
-------------

Give the server one directory to read. In ``claude_desktop_config.json`` (Claude
Desktop) or ``.mcp.json`` (Claude Code):

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp", "--root", "/srv/reports", "--no-bridge"]
       }
     }
   }

The client now sees the fourteen semantic tools. It can list, read, search and
checksum what is below ``/srv/reports``, and nothing else: writing is refused,
and so is every path outside that directory. On Windows write the path as
``"C:\\data\\reports"``. Use the interpreter of the environment the package is
installed in (``"command": "C:\\envs\\fa\\Scripts\\python.exe"``) when ``python``
on the ``PATH`` is another one.

With Claude Code the same server is added from a shell::

   claude mcp add automation_file -- python -m automation_file mcp --root /srv/reports --no-bridge

Production setup
----------------

Name every location, switch on only the permissions the work needs, keep the
definitions of pipelines on disk, and leave the bridge off:

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "/opt/fa/bin/python",
         "args": [
           "-m", "automation_file", "mcp",
           "--root", "/srv/reports/inbox",
           "--root", "/srv/reports/outbox",
           "--allow-write",
           "--max-read-bytes", "65536",
           "--max-results", "100",
           "--pipeline-dir", "/var/lib/automation_file/pipelines",
           "--tools", "file_read,file_write,file_copy,file_search,file_checksum,file_verify,storage_list,storage_copy",
           "--no-bridge"
         ]
       }
     }
   }

A remote backend needs its client initialised, and an audit trail and
notification routes have to be set up, before the server starts. That takes a few
lines of Python, so start the server from a launcher script and point the host's
``command`` at it:

.. code-block:: python

   # /opt/fa/mcp_server.py
   import os

   from automation_file import (
       MCPServer, Route, Severity, SlackSink, configure_audit,
       notification_manager, notification_router, s3_instance, sftp_instance,
   )
   from automation_file.server.mcp_policy import MCPPolicy

   s3_instance.later_init(region_name="eu-west-1")              # credentials: the AWS chain
   sftp_instance.later_init(host="sftp.example.com", username="reports",
                            key_filename="/etc/fa/id_ed25519",
                            known_hosts="/etc/fa/known_hosts")
   configure_audit("/var/lib/automation_file/audit.sqlite")     # audit_search reads this
   notification_manager.register(SlackSink(os.environ["SLACK_WEBHOOK"], name="ops"))
   notification_router.add_route(Route(
       "mcp-failures", sinks=("ops",),
       types=("mcp.tool.failed", "pipeline.failed", "storage.error"),
       min_severity=Severity.WARNING,
   ))
   notification_router.start()

   policy = MCPPolicy(
       roots=["s3://reports-export/daily", "sftp://sftp.example.com/inbound/reports"],
       allow_write=True,
       allow_delete=True,                # file_move deletes its source
       max_read_bytes=64 * 1024,
       pipeline_dir="/var/lib/automation_file/pipelines",
   )
   MCPServer(policy=policy, bridge=False).serve_stdio()

.. code-block:: json

   {"mcpServers": {"automation_file": {"command": "/opt/fa/bin/python",
                                       "args": ["/opt/fa/mcp_server.py"]}}}

Nothing may be written to ``stdout`` but the protocol: the library logs to
``stderr`` and to its log file, and a launcher must not ``print``.

The semantic tools
------------------

Every location is a storage URI, ``<scheme>://<authority>/<path>``
(``local:///srv/reports/a.csv``, ``s3://bucket/2026/a.csv``,
``sftp://host/inbox/a.csv``), or an absolute local path. "Needs" lists what the
policy must allow besides a root that contains every location of the call.

.. list-table::
   :header-rows: 1
   :widths: 14 30 36 20

   * - Tool
     - Arguments
     - Result
     - Needs
   * - ``file_read``
     - ``uri``, ``offset=0``, ``max_bytes``, ``encoding="utf-8"`` (a text
       encoding, or ``base64``)
     - ``content``, ``encoding``, ``size``, ``offset``, ``bytes``,
       ``truncated``, ``next_offset``
     - —
   * - ``file_write``
     - ``uri``, ``content``, ``encoding="utf-8"``, ``overwrite=false``,
       ``dry_run=false``
     - ``size``, ``sha256``, ``overwrites``, ``replaced_size``, ``written``
     - write; overwrite to replace a file
   * - ``file_copy``
     - ``source``, ``target``, ``overwrite=false``, ``verify=false``,
       ``dry_run=false``
     - ``source``, ``target``, ``size``, ``overwrites``, ``replaced_size``,
       ``deletes_source``, ``done``; with ``verify``: ``sha256``, ``verified``
     - write; overwrite to replace a file
   * - ``file_move``
     - As ``file_copy``
     - As ``file_copy``; ``deletes_source`` is true
     - write and delete; overwrite to replace a file
   * - ``file_search``
     - ``uri``, ``pattern="*"``, ``content``, ``recursive=true``,
       ``case_sensitive=false``, ``max_results``
     - ``matches`` (``uri``, ``path``, ``name``, ``size``, ``modified_at``; for a
       content search also ``line``, ``snippet``, ``matching_lines``), ``count``,
       ``candidates``, ``truncated``; for a content search also
       ``searched_files``, ``searched_bytes``, ``skipped``, ``complete``
     - —
   * - ``file_checksum``
     - ``uri``, ``algorithm="sha256"``
     - ``algorithm``, ``value``, ``size``
     - —
   * - ``file_verify``
     - ``uri``, ``expected`` (hex, or ``sha256:<hex>``), ``algorithm="sha256"``
     - ``match``, ``expected``, ``actual``, ``algorithm``
     - —
   * - ``storage_list``
     - ``uri``, ``recursive=false``, ``max_results``
     - ``entries`` (``uri``, ``path``, ``name``, ``is_dir``, ``size``,
       ``modified_at``), ``count``, ``total``, ``truncated``
     - —
   * - ``storage_copy``
     - ``source``, ``target``, ``overwrite=false``, ``verify=false``,
       ``dry_run=false``
     - A file: ``kind="file"`` and the result of ``file_copy``. A directory:
       ``kind="tree"``, ``planned`` (``copy``, ``overwrite``, ``skip``,
       ``bytes``), ``paths``, ``existing``, ``truncated``, ``done``, and after
       the copy ``copied``, ``skipped``, ``failed``, ``errors``, ``ok``
     - write; overwrite to replace files
   * - ``pipeline_create``
     - ``name``, ``definition``, ``overwrite=false``, ``dry_run=false``
     - ``name``, ``location``, ``persistent``, ``tasks``, ``actions``,
       ``overwrites``, ``stored``
     - write; overwrite to replace a definition
   * - ``pipeline_run``
     - ``name``, ``params``, ``dry_run=false``, ``background=false``
     - ``run_id``, ``status``, ``ok``, ``run`` (the run with every task)
     - write; each task needs what its action needs
   * - ``pipeline_status``
     - ``run_id``, or ``name`` and ``limit=5``
     - ``runs``, ``count``
     - no root
   * - ``integrity_status``
     - ``name``
     - ``monitors`` (``name``, ``target``, ``running``, ``last_run``,
       ``last_error``, ``last_report``), ``count``
     - no root
   * - ``audit_search``
     - ``actor``, ``source``, ``pipeline``, ``task``, ``action``, ``backend``,
       ``status``, ``correlation_id``, ``resource_prefix``, ``text``, ``since``,
       ``until``, ``limit=50``, ``offset=0``
     - ``records``, ``count``, ``total``, ``limit``, ``offset``, ``truncated``
     - no root; a configured audit trail

Notes on single tools:

``file_read``
    Returns at most ``--max-read-bytes`` per call. When ``truncated`` is true,
    call again with ``offset`` set to ``next_offset``; a character is never cut
    in half. Content that is not text in the chosen encoding is an error that
    asks for ``encoding="base64"``.

``file_copy``, ``file_move`` and ``verify``
    With ``verify=true`` the SHA-256 of the source is compared with that of the
    copy. A move then copies, compares, and deletes the source only when the
    digests match; on a mismatch the source stays and the call fails as
    ``checksum_mismatch``.

``file_verify``
    A mismatch is a result (``match`` is false), not an error.

``file_search``
    ``pattern`` is a shell-style pattern for the file name (``*.csv``); with a
    ``/`` in it, it is matched against the path below ``uri``
    (``2026/*/*.csv``). ``content`` is a plain substring, not a regular
    expression. A content search reads at most ``--max-search-bytes`` in one
    call. A file that does not fit in what is left of that budget is not opened
    and is listed under ``skipped``, as are binary files and files that could
    not be read; ``complete`` is true only when every candidate was searched.

``storage_copy``
    Copies a file like ``file_copy``, or every file below a directory. For a
    directory, files that exist at the target are skipped unless ``overwrite``
    is true. A file that fails is recorded under ``errors`` and the others are
    still copied; the call is then an error whose result holds the counts.

``pipeline_run``
    Runs in the calling request and returns the finished run. With
    ``background=true`` it returns at once with ``status="running"``; poll
    ``pipeline_status`` with the ``run_id``. A run that fails is an error whose
    result still holds the run.

Results and errors
~~~~~~~~~~~~~~~~~~

A semantic tool answers with one JSON document as the text of the result. It
always holds ``tool`` and ``correlation_id``. When the call was refused or
failed, ``isError`` is true and the document holds an ``error``:

.. code-block:: json

   {
     "tool": "file_write",
     "correlation_id": "27acff55529c4317b74de6ea98759f42",
     "error": {
       "type": "permission_denied",
       "code": "read_only",
       "message": "file_write changes something and this server is read-only: start it with --allow-write, or pass MCPPolicy(allow_write=True)"
     }
   }

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - ``error.type``
     - Meaning
   * - ``permission_denied``
     - The policy refused the call. ``code`` names the rule: ``no_root``,
       ``outside_root``, ``read_only``, ``overwrite_not_allowed``,
       ``delete_not_allowed``, ``tool_disabled``, ``action_not_allowed`` or
       ``limit_exceeded``.
   * - ``invalid_arguments``
     - An argument is missing, unknown, of the wrong type or out of range. Every
       problem is listed.
   * - ``invalid_uri``
     - The location is not a storage URI, or its path holds a ``..`` segment.
   * - ``not_found``, ``already_exists``
     - There is no such file, pipeline, run or monitor; or the target exists and
       ``overwrite`` was not given.
   * - ``checksum_mismatch``
     - A ``verify`` found different digests on the two sides.
   * - ``invalid_definition``
     - The pipeline definition is wrong; ``problems`` lists every finding with
       its path.
   * - ``not_configured``
     - The server keeps no audit trail.
   * - ``failed``
     - Anything else the library reported; ``exception`` names the class.
   * - ``internal_error``
     - An unexpected exception. Report it.

The permission model
--------------------

An :class:`~automation_file.server.mcp_policy.MCPPolicy` is built when the server
starts and cannot be changed afterwards. Its text form is sent to the client in
the ``instructions`` of the handshake, so the model knows the boundaries before
its first call.

.. list-table::
   :header-rows: 1
   :widths: 24 24 14 38

   * - Field
     - Flag
     - Default
     - Meaning
   * - ``roots``
     - ``--root`` (repeatable)
     - none
     - The locations the tools may work in: storage URIs or local directories.
       Without one, every tool that touches storage refuses and says how to add
       a root.
   * - ``allow_write``
     - ``--allow-write``
     - off
     - ``file_write``, ``file_copy``, ``file_move``, ``storage_copy``,
       ``pipeline_create`` and ``pipeline_run`` are refused without it, a dry
       run included.
   * - ``allow_overwrite``
     - ``--allow-overwrite``
     - off
     - Replacing an existing file or definition. The call has to ask for it too
       (``overwrite=true``). Needs ``allow_write``.
   * - ``allow_delete``
     - ``--allow-delete``
     - off
     - Deleting. ``file_move`` deletes its source, so it needs this. Needs
       ``allow_write``.
   * - ``max_read_bytes``
     - ``--max-read-bytes``
     - 262144
     - The most bytes ``file_read`` returns in one call, and the largest task
       result a pipeline tool returns.
   * - ``max_write_bytes``
     - ``--max-write-bytes``
     - 1048576
     - The largest content ``file_write`` accepts and the largest definition
       ``pipeline_create`` stores.
   * - ``max_results``
     - ``--max-results``
     - 200
     - The most entries a listing, a search, a tree plan or ``audit_search``
       returns. A larger ``max_results`` or ``limit`` in a call is lowered to it.
   * - ``max_search_bytes``
     - ``--max-search-bytes``
     - 8388608
     - The most bytes one content search reads.
   * - ``pipeline_dir``
     - ``--pipeline-dir``
     - memory
     - Where ``pipeline_create`` keeps definitions: a storage URI or a local
       directory, one ``<name>.json`` per pipeline. Without it they are kept in
       memory and are gone when the server stops.
   * - ``pipeline_actions``
     - ``--pipeline-actions``
     - by permission
     - The actions a pipeline created or run through MCP may call. See
       `Pipelines`_.
   * - ``tools``
     - ``--tools``
     - all fourteen
     - The semantic tools to offer. A tool left out is not listed and a call to
       it is refused. ``--tools none`` offers none.
   * - ``actor``
     - (Python only)
     - ``mcp``
     - The actor of every call in events and audit records. The client's name
       from the handshake is appended: ``mcp:claude-desktop``.

Locations
~~~~~~~~~

A call is allowed when every location it names is at or below a root.

* **A local root** is enforced by the storage layer itself. The location is
  served by a ``LocalStorage`` confined to the root, so every operation passes
  ``safe_join``: a symbolic link (or a Windows junction) that leads out of the
  root, and an absolute path smuggled below it, are refused as
  ``outside_root``. A link that stays inside a root is followed. On Windows the
  comparison ignores case and accepts backslashes, and a name that is a device
  (``CON``, ``NUL``, ``COM1``) or an alternate data stream (``a.txt:stream``) is
  refused too.
* **Any other backend** is compared by scheme, authority and whole path
  segments. ``s3://bucket/team`` allows ``s3://bucket/team/2026/a.csv`` and
  refuses ``s3://bucket/team-b/a.csv`` and ``s3://other/team/a.csv``. The
  authority is compared exactly, letter case included. The root is a path prefix
  and nothing more: a link that exists on the server, an SFTP symbolic link for
  instance, is followed by the server. Give the backend an account that cannot
  leave the tree.
* A path with a ``..`` segment is not a storage URI at all (``invalid_uri``).
* A backend mounted with ``Storage.mount`` is addressed through its mount URI,
  and a root below a mounted ``LocalStorage`` is confined to that root.

Write a location the way the root is written. A root given as
``/srv/reports`` does not match ``local:///mnt/disk2/reports`` even when both are
the same directory.

Pipelines
~~~~~~~~~

``pipeline_create`` stores a definition (:doc:`pipeline`, ``schema_version: 1``)
and ``pipeline_run`` runs it. Both need ``allow_write``.

What a definition may call is checked when it is created and again when it is
run, because the file may have been written by something else in between. By
default a pipeline may call the ``FA_storage_*`` actions the permissions cover:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Permission
     - Actions
   * - always
     - ``FA_storage_exists``, ``FA_storage_stat``, ``FA_storage_list``,
       ``FA_storage_checksum``, ``FA_storage_verify``, ``FA_storage_read_text``,
       ``FA_storage_schemes``
   * - ``allow_write``
     - ``FA_storage_mkdir``, ``FA_storage_write_text``, ``FA_storage_copy``,
       ``FA_storage_copy_tree``
   * - ``allow_overwrite``
     - ``FA_storage_sync`` (it replaces changed files)
   * - ``allow_delete``
     - ``FA_storage_move``, ``FA_storage_delete``

Inside such a pipeline these names do not run the plain actions. They run
guarded versions that check the roots and the permissions at the moment the task
runs, after ``${params.<name>}`` and ``${tasks.<id>.result}`` are filled in, so a
parameter cannot lead a task out of the roots. They behave like the plain
actions with these differences:

* ``overwrite`` defaults to what the policy permits instead of ``true``; an
  explicit ``overwrite: true`` is refused where overwriting is not allowed;
* ``FA_storage_verify`` also takes the result of ``FA_storage_checksum`` as its
  ``expected``, so ``"${tasks.<id>.result}"`` compares two files;
* ``FA_storage_read_text`` and ``FA_storage_write_text`` keep the read and write
  limits;
* ``FA_storage_sync`` needs ``allow_overwrite``, and ``delete: true`` needs
  ``allow_delete``;
* ``FA_storage_delete`` never removes a root itself;
* ``FA_storage_upload`` and ``FA_storage_download`` are not available: they take
  a filesystem path, not a storage URI. Copy to or from a ``local://`` URI.

``--pipeline-actions a,b,c`` replaces the default list. The ``FA_storage_*``
actions above stay guarded when they are listed. **Any other action runs as it
is, outside the roots and the permissions**: list only what you would let the
client call directly, and never an action that runs other actions
(``FA_execute_action``, ``FA_pipeline_run``, ``FA_run_shell``). Every name has to
be an action the server exposes, or the server does not start. An action named
inside the arguments or the parameters of another one is refused unless the list
names it, and a storage action is always refused there: nested, it would run
unguarded.

A definition created through MCP cannot carry a ``schedule``: when a pipeline
runs by itself is the operator's decision. The definition's ``name`` is the name
it is stored under; it is filled in when left out.

Runs are recorded in the default run store, where ``pipeline_status`` and
``FA_pipeline_status`` find them. That store is in memory unless a launcher calls
``set_default_run_store(SQLiteRunStore(path))``.

Dry run
-------

Every tool that changes something takes ``dry_run``. It then does every check
the real call would do, changes nothing, and returns the plan:

.. code-block:: json

   {
     "tool": "file_move",
     "correlation_id": "bb62a807d4f64bf3b666d00d3b4f410f",
     "source": "s3://reports-export/daily/2026-10-07.csv",
     "target": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
     "size": 48211,
     "overwrites": false,
     "replaced_size": null,
     "deletes_source": true,
     "dry_run": true,
     "done": false
   }

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Tool
     - What the dry run reports
   * - ``file_write``
     - The size and SHA-256 of the content, whether a file would be replaced and
       how large it is.
   * - ``file_copy``, ``file_move``
     - Source, target, size, whether the target would be replaced, whether the
       source would be deleted.
   * - ``storage_copy``
     - For a directory: how many files and bytes would be copied, replaced and
       skipped, with the paths (capped by ``max_results``).
   * - ``pipeline_create``
     - Whether the definition is valid and allowed, its tasks and actions, and
       whether it would replace a stored one.
   * - ``pipeline_run``
     - The tasks in dependency order as ``planned``, with an ``error`` on a task
       that names an unknown action or a parameter the run was not given.
       Nothing is executed or recorded.

A dry run needs the same permissions as the real call: a read-only server
refuses it as well, so a plan is never offered for something the server would
not do.

Traceability
------------

Each semantic call runs inside ``correlation_scope()`` and ``actor_scope(...)``.
The result carries the ``correlation_id``, and so does everything the call does:
the storage operations and one event per call, ``mcp.tool.completed`` or
``mcp.tool.failed`` (source ``mcp``).

.. list-table::
   :header-rows: 1
   :widths: 26 14 60

   * - Outcome
     - Severity
     - Event
   * - Done
     - info
     - ``mcp.tool.completed``, ``status="ok"``
   * - Refused by the policy
     - warning
     - ``mcp.tool.failed``, ``status="refused"``, ``code`` names the rule
   * - A mistake in the request: a missing file, an existing target, a wrong
       argument, an invalid definition
     - info
     - ``mcp.tool.failed``, ``status="error"``, ``code`` is the ``error.type``
   * - Failed: a backend error, a tree copy with failed files, a failed
       pipeline run
     - warning
     - ``mcp.tool.failed``, ``status="error"``. A failing backend is also
       reported as ``storage.error``, a failed run as ``pipeline.failed``.
   * - A ``verify`` whose digests differ
     - error
     - ``mcp.tool.failed``, ``status="error"``, ``code="checksum_mismatch"``
   * - Unexpected exception
     - error
     - ``mcp.tool.failed``, ``status="error"``, ``code="internal_error"``

A notification route on ``mcp.tool.failed`` with ``min_severity=Severity.WARNING``
therefore hears about refusals and real failures, and not about a model that
asked for a file that is not there.

The payload names the tool (``action``), the storage URIs the call was about
(``resource``, ``source_uri``), ``duration_ms`` and, for the pipeline tools,
``pipeline`` and ``run_id``. It never holds content, parameters or digests. A
refused call is also logged as a warning with the tool, the rule and the
correlation ID, and no argument value.

With an :doc:`audit trail <audit>` configured, one search returns what a call
did:

.. code-block:: python

   audit_search(correlation_id="7dc51e94bd3b494eae8e6b6f3f3b150b")
   # [{"source": "mcp", "action": "mcp.tool.completed", "actor": "mcp:claude-desktop", ...},
   #  {"source": "storage", "action": "copy", "resource": "sftp://...", "status": "ok", ...}]

A pipeline run has a correlation ID of its own, its ``run_id``. The event of the
``pipeline_run`` call holds that ``run_id``, which ties the two together.

Example: S3 to SFTP, verified, audited, with an alert on failure
----------------------------------------------------------------

The task: *move yesterday's CSV from S3 to the company SFTP server, verify its
SHA-256, audit the transfer, and notify Slack on failure*. The launcher of
`Production setup`_ provides what this needs: both backends initialised, two
roots, writing and deleting allowed, an audit trail, and a route that sends
failures to Slack. The client then makes these calls:

.. code-block:: text

   1. storage_list   {"uri": "s3://reports-export/daily"}
        -> the entries; the client picks 2026-10-07.csv

   2. file_move      {"source": "s3://reports-export/daily/2026-10-07.csv",
                      "target": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
                      "verify": true, "dry_run": true}
        -> the plan: size, overwrites=false, deletes_source=true

   3. file_move      the same arguments without dry_run
        -> done=true, verified=true, sha256="9f86d0...", correlation_id="7dc5..."
           The source was deleted only after the two SHA-256 digests matched.

   4. file_verify    {"uri": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
                      "expected": "sha256:9f86d0..."}
        -> match=true (an independent check, for the record)

   5. audit_search   {"correlation_id": "7dc5..."}
        -> the mcp.tool.completed record of step 3 and the storage records
           (copy, delete) with their resources, durations and status

**On failure.** When step 3 fails, the client gets an ``error`` and the source
is still in S3. The server publishes ``mcp.tool.failed`` (an error for digests
that differ, a warning for a transfer that failed), plus ``storage.error`` when
a backend failed, and the route of the launcher delivers them to Slack. No tool
sends the notification, so the client cannot skip it.

The same work as a pipeline that is created once and run daily:

.. code-block:: text

   pipeline_create {
     "name": "export-daily",
     "definition": {
       "schema_version": 1,
       "description": "Move the daily export from S3 to SFTP and verify it",
       "tasks": {
         "digest": {"action": ["FA_storage_checksum",
                               {"uri": "s3://reports-export/daily/${params.date}.csv"}]},
         "copy":   {"action": ["FA_storage_copy",
                               {"source": "s3://reports-export/daily/${params.date}.csv",
                                "target": "sftp://sftp.example.com/inbound/reports/${params.date}.csv"}],
                    "depends_on": ["digest"],
                    "retry": {"max_attempts": 3, "backoff": 5}, "timeout": 600},
         "verify": {"action": ["FA_storage_verify",
                               {"uri": "sftp://sftp.example.com/inbound/reports/${params.date}.csv",
                                "expected": "${tasks.digest.result}", "strict": true}],
                    "depends_on": ["copy"]},
         "remove": {"action": ["FA_storage_delete",
                               {"uri": "s3://reports-export/daily/${params.date}.csv"}],
                    "depends_on": ["verify"]}
       }
     }
   }
   pipeline_run    {"name": "export-daily", "params": {"date": "2026-10-07"}, "dry_run": true}
   pipeline_run    {"name": "export-daily", "params": {"date": "2026-10-07"}}
   audit_search    {"correlation_id": "<the run_id>"}

``"${tasks.digest.result}"`` hands the checksum of the source to
``FA_storage_verify``. With ``strict: true`` a mismatch fails the task, so
``remove`` is skipped and the source stays. A failed run publishes
``pipeline.failed``, which the same route sends to Slack.

The ``FA_*`` bridge
-------------------

With the bridge on, ``tools/list`` returns the semantic tools first and then one
tool per registered action, sorted by name, with a JSON Schema derived from the
Python signature. ``tools/call`` on such a tool dispatches through the registry
and answers with the JSON-encoded return value; a failure is a JSON-RPC error.
This is what earlier versions did, and existing configurations keep working.

.. code-block:: text

   python -m automation_file mcp                                    # semantic tools + every FA_* action
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum
   python -m automation_file mcp --root /srv/reports --no-bridge    # semantic tools only

``--allowed-actions`` narrows the bridge to the named actions. A call whose
arguments name an action outside that list is refused (``FA_execute_action``
cannot be used to reach it). ``--no-bridge``, or ``MCPServer(bridge=False)``,
switches the bridge off; an ``FA_*`` name is then an unknown tool.

**The policy does not bind the bridge.** ``FA_storage_copy`` called through the
bridge reaches any location the process can, whatever ``--root`` says. For an AI
client use ``--no-bridge``; keep the bridge for tools you would also let the
client call without a policy.

From Python:

.. code-block:: python

   from automation_file import MCPServer, executor, tools_from_registry
   from automation_file.server.mcp_policy import MCPPolicy
   from automation_file.server.mcp_tools import SemanticToolkit

   MCPServer().serve_stdio()                                  # as before: bridge on
   MCPServer(policy=MCPPolicy(roots=["/srv/reports"]), bridge=False).serve_stdio()

   for tool in tools_from_registry(executor.registry):        # the bridge's catalogue
       print(tool["name"], "->", tool["description"])

   toolkit = SemanticToolkit(MCPPolicy(roots=["/srv/reports"]))   # the tools without JSON-RPC
   outcome = toolkit.call("file_checksum", {"uri": "/srv/reports/a.csv"})
   outcome.is_error, outcome.payload["value"], outcome.correlation_id

Flags
-----

``python -m automation_file mcp`` and the ``automation_file_mcp`` console script
take the same flags.

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Flag
     - Meaning
   * - ``--name``, ``--version``
     - ``serverInfo`` of the handshake. Defaults: ``automation_file``, ``1.0.0``.
   * - ``--allowed-actions a,b``
     - The registered actions the bridge offers. Default: all.
   * - ``--no-bridge``
     - Offer only the semantic tools.
   * - ``--root URI``
     - An allowed location; repeatable.
   * - ``--allow-write``, ``--allow-overwrite``, ``--allow-delete``
     - The three permissions. The last two need the first.
   * - ``--max-read-bytes N``, ``--max-write-bytes N``, ``--max-results N``,
       ``--max-search-bytes N``
     - The limits.
   * - ``--pipeline-dir URI``
     - Where pipeline definitions are kept.
   * - ``--pipeline-actions a,b``
     - The actions a pipeline run through MCP may call.
   * - ``--tools a,b``
     - The semantic tools to offer, or ``none``.

A wrong flag (an unknown tool name, ``--allow-overwrite`` without
``--allow-write``, a root with credentials in it) ends the command with a usage
error before anything is served.

Security guidance
-----------------

* **The process's privileges are the outer limit.** The server runs as the user
  who started it, with the credentials its backends were given. The policy
  narrows that for the semantic tools; it does not replace least privilege on
  the account, the bucket policy or the SFTP user.
* **Switch the bridge off for AI clients** (``--no-bridge``). The bridge offers
  every registered action, ``FA_run_shell`` and ``FA_storage_delete`` included,
  and the policy does not apply to it.
* **Keep roots narrow.** A root is a grant for everything below it. Do not use
  ``local:///`` or a home directory. Put what a client may write in a directory
  of its own.
* **Start read-only.** Add ``--allow-write`` when the work needs it, and
  ``--allow-overwrite`` and ``--allow-delete`` only when it needs those. A
  client that can write but not overwrite or delete cannot destroy what is
  already there.
* **What a file contains is not an instruction.** A model reads file content
  through ``file_read`` and ``file_search`` and may act on what it reads. The
  policy bounds what such a hijacked session can do; so do the confirmation
  prompts of the host. Ask for a ``dry_run`` first on anything that matters.
* **Pipelines.** The default actions stay inside the roots. Every action you add
  with ``--pipeline-actions`` runs unconfined. The pipeline directory holds
  definitions an AI client wrote: only ``pipeline_run`` applies the policy to
  them, so do not run them with ``FA_pipeline_run`` or ``Pipeline.from_file``,
  and do not point a scheduler at that directory.
* **The reporting tools are not bound by the roots.** ``audit_search``,
  ``integrity_status`` and ``pipeline_status`` show resource names, errors and
  run parameters from the whole process. Leave them out of ``--tools`` for a
  client that must not see them.
* **The client's name proves nothing.** It labels the actor in the audit trail
  and comes from the client itself. Stdio has no authentication: whoever can
  start the process has its powers.
* **Secrets.** Credentials never belong in a storage URI (one that carries them
  is refused) or in pipeline parameters, which are recorded with the run. The
  log holds no argument values and no file content.
* **Network.** The semantic tools make no HTTP request of their own. The storage
  backends keep their checks: TLS verification, SFTP host keys, and the SSRF
  guard of the actions that fetch a URL.
* Do not call ``PackageLoader.add_package_to_executor`` in a process that serves
  the bridge: it registers every member of a package as an action.

When something goes wrong
-------------------------

``no storage location is allowed on this server``
    No root is configured. Add ``--root <storage URI or directory>``, or pass
    ``MCPPolicy(roots=[...])``.

``... is outside the allowed locations (...)``
    The location is not at or below a root; the message lists the roots. Check
    the spelling against the root: another bucket or host, a sibling directory
    (``reports-old`` next to ``reports``), another letter case in the authority,
    or another path to the same directory.

``... leaves the allowed location through a link or an absolute path``
    A symbolic link or a junction below a local root points outside it. Add the
    link's target as a root if the client should reach it.

``this server is read-only``, ``does not allow it``
    The permission is off: ``--allow-write``, ``--allow-overwrite`` or
    ``--allow-delete``. ``file_move`` needs writing and deleting.

``already exists``
    Pass ``overwrite=true``; the server must allow overwriting as well.

``file_read`` returns only part of a file
    ``truncated`` is true: call again with ``offset=next_offset``, or raise
    ``--max-read-bytes``. For a backend without ranged reads the whole file is
    staged locally for each call, so page through a very large remote file
    sparingly.

``file_search`` misses a file
    Look at ``complete`` and ``skipped``. A file larger than what is left of
    ``--max-search-bytes`` is not searched; narrow ``pattern`` or raise the
    budget. Content is matched as UTF-8 text.

``... is not allowed in a pipeline``
    The definition names an action outside the allowed set; the message lists
    that set. Use the storage actions, or add the action with
    ``--pipeline-actions``.

A pipeline task fails with ``MCPLocationException`` or ``MCPPermissionException``
    The task reached a location outside the roots, or needed a permission that
    is off, when it ran. The definition was accepted because the location came
    from a parameter.

``no pipeline named ... is stored``
    The message lists the stored names. Without ``--pipeline-dir`` definitions
    are gone when the server restarts.

``pipeline_status`` does not know a run
    Runs are kept in memory by default. Call
    ``set_default_run_store(SQLiteRunStore(path))`` in a launcher.

``this server keeps no audit trail``
    Call ``configure_audit(path)`` in a launcher before ``serve_stdio()``.

An ``sftp://`` or ``s3://`` location fails although it is inside a root
    The backend is not initialised in this process. Call its ``later_init`` in a
    launcher; see `Production setup`_ and :doc:`storage`.

The host lists hundreds of tools, or none of the semantic ones
    The first is the bridge: add ``--no-bridge`` or ``--allowed-actions``. The
    second is ``--tools none``, or a version of the package from before the
    semantic tools.

The host reports a broken connection at start
    Something wrote to ``stdout``, or the command ended with a usage error.
    Run the same command in a terminal: errors go to ``stderr``. To check a
    server by hand::

       printf '%s\n%s\n' \
         '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
         '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
         | python -m automation_file mcp --root /srv/reports --no-bridge

Every exception of the semantic tools derives from ``MCPServerException``, and so
from ``FileAutomationException``: ``MCPPermissionException`` (with ``code``),
its subclass ``MCPLocationException``, and ``MCPToolException`` (with ``kind``).
