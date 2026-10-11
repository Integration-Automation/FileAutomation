Deploying to production
=======================

This page is about running FileAutomation unattended: what to install, where its
state lives, how to start it as one long-lived process, what to expose on the
network and what to watch. Every part of it is ordinary Python; there is no
separate server product to operate.

Install
-------

Pin the release and name the extras you use. The base package carries no cloud
SDK and no GUI toolkit:

.. code-block:: bash

   python -m venv /opt/fileautomation/venv
   /opt/fileautomation/venv/bin/pip install "automation_file[s3,sftp]==1.0.0"

Check what the installation can reach before anything depends on it::

   /opt/fileautomation/venv/bin/python -m automation_file storage schemes

A backend whose extra is missing fails at the first call with the command that
installs it (``pip install "automation_file[azure]"``), never at import.

Run it under an account of its own. That account's rights on the filesystem and
the credentials you give it are the boundary of what an action can do.

Configuration and secrets
-------------------------

Keep settings in ``automation_file.toml`` and keep secrets out of it:

.. code-block:: toml

   [secrets]
   file_root = "/run/secrets"

   [[notify.sinks]]
   type = "slack"
   name = "team-alerts"
   webhook_url = "${env:SLACK_WEBHOOK}"

   [[notify.routes]]
   name = "failures"
   sinks = ["team-alerts"]
   types = ["pipeline.failed", "task.failed", "integrity.violation", "scheduler.error"]
   min_severity = "error"
   dedup_seconds = 600

``${env:NAME}`` and ``${file:name}`` are resolved when the file is loaded, and a
reference that cannot be resolved raises instead of becoming an empty string
(:doc:`config`). Credentials for the backends come from the environment or from
files the account can read, passed to each client's ``later_init``. Do not put a
secret in an action list, a pipeline definition or a command line: all three are
logged, stored or visible to other users of the machine.

One process
-----------

The scheduler, the integrity monitors, the notification router, the audit trail
and the servers are threads of the process that started them. A production
deployment is therefore one script that starts what it needs and then waits:

.. code-block:: python

   # /opt/fileautomation/service.py
   import os
   import signal
   import threading

   from automation_file import (
       ActionACL, AutomationConfig, IntegrityMonitor, SQLiteRunStore, configure_audit,
       install_operational_metrics, notification_manager, notification_router,
       s3_instance, start_http_action_server, start_metrics_server,
   )
   from automation_file.pipeline import set_default_run_store

   STATE = "/var/lib/fileautomation"

   # 1. Settings, sinks and notification routes.
   AutomationConfig.load("/etc/fileautomation/automation_file.toml").apply_to(
       notification_manager, notification_router
   )

   # 2. State that must survive a restart.
   configure_audit(f"{STATE}/audit.sqlite")
   set_default_run_store(SQLiteRunStore(f"{STATE}/runs.sqlite"))

   # 3. Backends.
   s3_instance.later_init(region_name=os.environ["AWS_REGION"])

   # 4. What runs by itself.
   monitor = IntegrityMonitor("s3://reports/2026", baseline=f"{STATE}/reports.baseline.json")
   monitor.start()

   # 5. What listens: loopback only, a secret, and only the actions a client needs.
   install_operational_metrics()
   start_metrics_server(port=9945)
   start_http_action_server(
       port=9944,
       shared_secret=os.environ["FA_SHARED_SECRET"],
       action_acl=ActionACL.build(allowed=["FA_pipeline_run", "FA_storage_copy", "FA_storage_list"]),
   )

   # 6. Stay alive until asked to stop.
   stop = threading.Event()
   signal.signal(signal.SIGTERM, lambda *_: stop.set())
   signal.signal(signal.SIGINT, lambda *_: stop.set())
   stop.wait()
   monitor.stop()

Run it under your service manager. With systemd:

.. code-block:: ini

   [Unit]
   Description=FileAutomation
   After=network-online.target

   [Service]
   User=fileautomation
   EnvironmentFile=/etc/fileautomation/environment
   Environment=FILE_AUTOMATION_LOG_FILE=/var/log/fileautomation/FileAutomation.log
   ExecStart=/opt/fileautomation/venv/bin/python /opt/fileautomation/service.py
   Restart=on-failure
   StateDirectory=fileautomation
   LogsDirectory=fileautomation

   [Install]
   WantedBy=multi-user.target

On Windows the same script runs as a service through a wrapper such as NSSM, or
from Task Scheduler with "run whether the user is logged on or not".

A job that only has to run once (a nightly pipeline from the system's own cron,
a verification in a CI step) does not need the service: the command line does it
and exits with a code you can act on (:doc:`cli`)::

   python -m automation_file pipeline --audit /var/lib/fileautomation/audit.sqlite \
       run /etc/fileautomation/daily.yaml --store /var/lib/fileautomation/runs.sqlite

State on disk
-------------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - What
     - Where and how to treat it
   * - Audit trail
     - The SQLite file you gave ``configure_audit``. It is in WAL mode, so copy it
       with ``sqlite3 audit.sqlite ".backup …"`` and not with ``cp`` while the
       process runs. Keep it as long as your policy says, then
       ``python -m automation_file audit purge --db … --older-than-days 365``.
   * - Pipeline runs
     - The SQLite file of the ``SQLiteRunStore``. It is what ``resume`` reads after
       a crash; without it a run is forgotten when the process ends.
   * - Integrity baselines
     - One JSON file per monitored tree. Keep it outside the tree it describes
       and, better, where the account that changes the tree cannot write: whoever
       can rewrite the baseline can hide a change.
   * - OAuth tokens
     - The ``token_path`` you gave the Google Drive client. Readable by the
       service account only.
   * - Log
     - ``~/.automation_file/logs/FileAutomation.log`` unless
       ``FILE_AUTOMATION_LOG_FILE`` names another path. A file past 10 MB is moved
       to ``.1`` when a process opens it; rotate it yourself if you need more.
   * - Version snapshots, trash, the content store
     - The directories you gave those features. They grow until you prune them.

Network exposure
----------------

Every server binds the loopback interface unless you pass
``allow_non_loopback=True``, and that default is the recommendation: the action
servers run whatever is registered, so reaching one is equivalent to reaching a
Python prompt of the service account.

* Clients on the same machine use the loopback address and the shared secret.
* A client elsewhere goes through something that terminates TLS and
  authenticates it (a reverse proxy, an SSH tunnel, a service mesh). The servers
  speak plain HTTP and plain TCP.
* Give each server an ``ActionACL`` with an allow list. The ACL also checks the
  actions nested in the arguments of another action. It cannot see inside a file
  an action is told to run, so do not allow ``FA_execute_files`` or a pipeline
  given as a path to a client that must stay inside the list.
* The MCP server speaks over the standard streams of the process that starts it.
  It needs no port; its allow list is :doc:`mcp`.

Outbound requests to URLs supplied by a caller go through the SSRF guard: only
``http`` and ``https``, and no private, loopback or link-local address. That
guard is what makes it safe to accept a URL from a client; do not route around it.

What to watch
-------------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Signal
     - Where
   * - Health
     - ``GET /healthz`` and ``GET /readyz`` on the HTTP action server.
   * - Metrics
     - ``start_metrics_server()`` serves Prometheus text. ``automation_file_actions_total``
       and its duration histogram are always there; ``install_operational_metrics()``
       adds counters for events, notifications and storage operations.
   * - Failures
     - Events: ``pipeline.failed``, ``task.failed``, ``integrity.violation``,
       ``storage.error``, ``scheduler.error``, ``system.error``. Route the ones
       you want to be told about to a sink (:doc:`notifications`).
   * - History
     - The audit trail: ``python -m automation_file audit search --db … --status
       error``, or ``--correlation-id <run id>`` for everything one run did.
   * - Log
     - INFO and above also go to standard error, which a service manager
       captures.

Surviving failure
-----------------

* Give a pipeline task a ``RetryPolicy`` for the errors that pass (a dropped
  connection, throttling) and a ``timeout`` for the ones that never return.
* Give a task that must not happen twice an ``idempotency_key``, and keep runs in
  a ``SQLiteRunStore``: after a restart ``pipeline resume <run id>`` repeats only
  what did not succeed.
* A scheduled job does not start while its previous run is still going, unless
  you allowed the overlap.
* Remediation by the integrity monitor is off unless you configured it. Start
  with alerts, and add quarantine or restore when you trust the baseline.

Upgrading
---------

1. Read the release notes. A patch release only fixes; a minor release may
   deprecate; only a major release removes (:doc:`api_policy`).
2. Run your own tests with ``-W error::DeprecationWarning`` against the new
   version before it reaches production.
3. Back up the two SQLite files. A release that changes a stored format reads
   the previous one and says how to convert.
4. Install into a fresh virtual environment next to the old one and switch the
   service to it, so rolling back is switching again.

Checklist
---------

* The service runs under an account of its own, and only that account reads the
  secrets and the token files.
* The version and the extras are pinned.
* The audit trail and the run store are files on a disk that is backed up.
* Every server is on the loopback interface, has a shared secret and has an
  allow list; anything remote goes through TLS.
* Failures reach a person: at least one notification route for errors.
* Baselines live where the monitored tree's writers cannot change them.
* Logs and the growing directories have a retention you chose.
