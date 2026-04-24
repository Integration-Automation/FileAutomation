Architecture
============

``automation_file`` follows a layered architecture built around five design
patterns:

System overview
---------------

The diagram below shows the full dispatch surface: every caller — CLI, GUI,
HTTP/MCP clients, entry-point plugins — eventually lands in the shared
``ActionRegistry`` that ``build_default_registry()`` populates, and the
registry fans out to local ops, remote backends, reliability / security /
observability helpers, notifications, and the event-driven trigger + cron
dispatchers.

.. mermaid::

   flowchart TD
       CLI["<b>CLI / JSON batch</b><br/>python -m automation_file"]
       GUIUser["<b>PySide6 GUI</b><br/>launch_ui"]
       ClientSDK["<b>HTTPActionClient SDK</b>"]
       MCPHost["<b>MCP hosts</b><br/>Claude Desktop · MCP CLIs"]
       Plugins["<b>Entry-point plugins</b><br/>automation_file.actions"]

       subgraph Facade["<b>automation_file &mdash; facade (__init__.py)</b>"]
           PublicAPI["<b>Public API</b><br/>execute_action · execute_action_parallel · execute_action_dag<br/>validate_action · driver_instance · s3_instance · azure_blob_instance<br/>dropbox_instance · sftp_instance · ftp_instance · onedrive_instance · box_instance<br/>start_autocontrol_socket_server · start_http_action_server<br/>start_metrics_server · start_web_ui · MCPServer<br/>notification_manager · scheduler · trigger_manager<br/>AutomationConfig · progress_registry · Quota · retry_on_transient"]
       end

       subgraph Core["<b>core</b>"]
           Registry[("<b>ActionRegistry</b><br/>FA_* commands")]
           Executor["<b>ActionExecutor</b><br/>serial · parallel · dry-run · validate-first"]
           DAG["<b>dag_executor</b><br/>topological fan-out"]
           Callback["<b>CallbackExecutor</b>"]
           Loader["<b>PackageLoader</b><br/>+ entry-point plugins"]
           Queue["<b>ActionQueue</b>"]
           Json["<b>json_store</b>"]
           Sub["<b>substitution</b><br/>${env:} ${date:} ${uuid}"]
       end

       subgraph Reliability["<b>reliability</b>"]
           Retry["<b>retry</b><br/>@retry_on_transient"]
           QuotaMod["<b>Quota</b><br/>bytes + time budget"]
           Breaker["<b>CircuitBreaker</b>"]
           RL["<b>RateLimiter</b>"]
           Locks["<b>FileLock</b> · <b>SQLiteLock</b>"]
       end

       subgraph Observability["<b>observability</b>"]
           Progress["<b>progress</b><br/>CancellationToken · Reporter"]
           Metrics["<b>metrics</b><br/>Prometheus counters + histograms"]
           Audit["<b>AuditLog</b><br/>SQLite"]
           Tracing["<b>tracing</b><br/>OpenTelemetry spans"]
           FIM["<b>IntegrityMonitor</b>"]
       end

       subgraph Security["<b>security &amp; config</b>"]
           Secrets["<b>Secret providers</b><br/>Env · File · Chained"]
           Config["<b>AutomationConfig</b><br/>TOML loader"]
           ConfW["<b>ConfigWatcher</b><br/>hot reload"]
           Crypto["<b>crypto</b><br/>AES-256-GCM"]
           Check["<b>checksum</b> / <b>manifest</b>"]
           SafeP["<b>safe_paths</b><br/>safe_join · is_within"]
           ACL["<b>ActionACL</b>"]
       end

       subgraph Events["<b>event-driven</b>"]
           Trigger["<b>TriggerManager</b><br/>watchdog file watcher"]
           Sched["<b>Scheduler</b><br/>5-field cron + overlap guard"]
       end

       subgraph Servers["<b>servers</b>"]
           TCP["<b>TCPActionServer</b><br/>loopback · AUTH secret"]
           HTTPS["<b>HTTPActionServer</b><br/>POST /actions · Bearer<br/>/healthz /readyz /progress /openapi.json"]
           MCP["<b>MCPServer</b><br/>JSON-RPC 2.0 (stdio)"]
           MetSrv["<b>MetricsServer</b><br/>/metrics"]
           WebUI["<b>WebUIServer</b><br/>HTMX dashboard"]
       end

       subgraph UI["<b>ui (PySide6)</b>"]
           MainWin["<b>MainWindow</b><br/>Home · Local · HTTP · Drive · S3 · Azure · Dropbox<br/>SFTP · OneDrive · Box · JSON · Triggers · Scheduler<br/>Progress · Transfer · Servers"]
           Worker["<b>ActionWorker</b><br/>QRunnable on QThreadPool"]
       end

       subgraph Local["<b>local ops</b>"]
           FileOps["<b>file_ops</b> · <b>dir_ops</b>"]
           Archives["<b>zip_ops</b> · <b>tar_ops</b> · <b>archive_ops</b>"]
           DataOps["<b>data_ops</b><br/>csv · jsonl · parquet · yaml"]
           TextOps["<b>text_ops</b> · <b>diff_ops</b><br/><b>json_edit</b> · <b>templates</b>"]
           Misc["<b>shell_ops</b> · <b>sync_ops</b> · <b>trash</b><br/><b>versioning</b> · <b>conditional</b> · <b>mime</b>"]
       end

       subgraph Remote["<b>remote backends</b>"]
           UrlVal["<b>url_validator</b><br/>SSRF guard"]
           Http["<b>http_download</b><br/>retry · resume · SHA-256"]
           Drive["<b>google_drive</b>"]
           S3M["<b>s3</b>"]
           Azure["<b>azure_blob</b>"]
           Dropbox["<b>dropbox_api</b>"]
           SFTP["<b>sftp</b> (RejectPolicy)"]
           FTP["<b>ftp / FTPS</b>"]
           OneD["<b>onedrive</b>"]
           Box["<b>box</b>"]
           WebDAV["<b>webdav</b>"]
           SMB["<b>smb / cifs</b>"]
           Fsspec["<b>fsspec_bridge</b>"]
           Cross["<b>cross_backend</b><br/>local:// s3:// drive:// azure://<br/>dropbox:// sftp:// ftp://"]
       end

       subgraph Notify["<b>notifications</b>"]
           NM["<b>NotificationManager</b><br/>fanout · dedup · SSRF guard"]
           Sinks["<b>Sinks</b><br/>Webhook · Slack · Email<br/>Telegram · Discord · Teams · PagerDuty"]
       end

       subgraph Utils["<b>utils / project</b>"]
           Fast["<b>fast_find</b><br/>mdfind / locate / es.exe"]
           Dedup["<b>find_duplicates</b>"]
           Grep["<b>grep_files</b>"]
           Rotate["<b>rotate_backups</b>"]
           Discovery["<b>file_discovery</b>"]
           Builder["<b>ProjectBuilder</b> + templates"]
       end

       CLI ==> PublicAPI
       GUIUser ==> MainWin
       ClientSDK ==> HTTPS
       MCPHost ==> MCP
       Plugins ==> Loader

       MainWin ==> Worker
       Worker ==> PublicAPI

       PublicAPI ==> Executor
       PublicAPI ==> DAG
       PublicAPI ==> Callback
       PublicAPI ==> Queue
       PublicAPI ==> Config
       PublicAPI ==> NM
       PublicAPI ==> Trigger
       PublicAPI ==> Sched

       TCP ==> Executor
       HTTPS ==> Executor
       MCP ==> Registry
       MetSrv ==> Metrics
       WebUI ==> Registry
       ACL ==> TCP
       ACL ==> HTTPS

       Executor ==> Registry
       Executor ==> Sub
       Executor ==> Retry
       Executor ==> QuotaMod
       Executor ==> Metrics
       Executor ==> Audit
       Executor ==> Tracing
       Executor ==> Json
       DAG ==> Executor
       Callback ==> Registry
       Loader ==> Registry

       Trigger ==> Executor
       Sched ==> Executor
       Trigger -. on failure .-> NM
       Sched -. on failure .-> NM
       FIM -. on drift .-> NM
       ConfW ==> Config
       Config ==> Secrets
       Config ==> NM

       Registry ==> FileOps
       Registry ==> Archives
       Registry ==> DataOps
       Registry ==> TextOps
       Registry ==> Misc
       Registry ==> Http
       Registry ==> Drive
       Registry ==> S3M
       Registry ==> Azure
       Registry ==> Dropbox
       Registry ==> SFTP
       Registry ==> FTP
       Registry ==> OneD
       Registry ==> Box
       Registry ==> WebDAV
       Registry ==> SMB
       Registry ==> Fsspec
       Registry ==> Cross
       Registry ==> Crypto
       Registry ==> Check
       Registry ==> Fast
       Registry ==> Dedup
       Registry ==> Grep
       Registry ==> Rotate
       Registry ==> Discovery
       Registry ==> Builder
       Registry ==> Progress

       FileOps ==> SafeP
       Archives ==> SafeP
       Misc ==> SafeP

       Http ==> UrlVal
       Http ==> Retry
       Http ==> Progress
       Http ==> Check
       S3M ==> Progress
       WebDAV ==> UrlVal
       NM ==> UrlVal
       NM ==> Sinks

       Cross ==> Drive
       Cross ==> S3M
       Cross ==> Azure
       Cross ==> Dropbox
       Cross ==> SFTP
       Cross ==> FTP

       classDef entry fill:#FDEDEC,stroke:#641E16,stroke-width:3px,color:#000,font-weight:bold;
       classDef facade fill:#D6EAF8,stroke:#154360,stroke-width:4px,color:#000,font-weight:bold;
       classDef core fill:#FEF9E7,stroke:#1F3A93,stroke-width:3px,color:#000,font-weight:bold;
       classDef rel fill:#D1F2EB,stroke:#0B5345,stroke-width:3px,color:#000,font-weight:bold;
       classDef obs fill:#FDEBD0,stroke:#9C640C,stroke-width:3px,color:#000,font-weight:bold;
       classDef sec fill:#F5B7B1,stroke:#78281F,stroke-width:3px,color:#000,font-weight:bold;
       classDef event fill:#FCF3CF,stroke:#7D6608,stroke-width:3px,color:#000,font-weight:bold;
       classDef server fill:#FADBD8,stroke:#922B21,stroke-width:3px,color:#000,font-weight:bold;
       classDef ui fill:#AED6F1,stroke:#1B4F72,stroke-width:3px,color:#000,font-weight:bold;
       classDef localOps fill:#E8DAEF,stroke:#512E5F,stroke-width:3px,color:#000,font-weight:bold;
       classDef remote fill:#D5F5E3,stroke:#196F3D,stroke-width:3px,color:#000,font-weight:bold;
       classDef notify fill:#F9E79F,stroke:#7D6608,stroke-width:3px,color:#000,font-weight:bold;
       classDef utils fill:#EAEDED,stroke:#212F3C,stroke-width:3px,color:#000,font-weight:bold;

       class CLI,GUIUser,ClientSDK,MCPHost,Plugins entry;
       class PublicAPI facade;
       class Registry,Executor,DAG,Callback,Loader,Queue,Json,Sub core;
       class Retry,QuotaMod,Breaker,RL,Locks rel;
       class Progress,Metrics,Audit,Tracing,FIM obs;
       class Secrets,Config,ConfW,Crypto,Check,SafeP,ACL sec;
       class Trigger,Sched event;
       class TCP,HTTPS,MCP,MetSrv,WebUI server;
       class MainWin,Worker ui;
       class FileOps,Archives,DataOps,TextOps,Misc localOps;
       class UrlVal,Http,Drive,S3M,Azure,Dropbox,SFTP,FTP,OneD,Box,WebDAV,SMB,Fsspec,Cross remote;
       class NM,Sinks notify;
       class Fast,Dedup,Grep,Rotate,Discovery,Builder utils;

       linkStyle default stroke:#1F2A44,stroke-width:2.5px;

Design patterns
---------------

**Facade**
   :mod:`automation_file` (the top-level ``__init__``) is the only name users
   should need to import. Every public function and singleton is re-exported
   from there.

**Registry + Command**
   :class:`~automation_file.core.action_registry.ActionRegistry` maps an action
   name (a string that appears in a JSON action list) to a Python callable.
   An action is a Command object of shape ``[name]``, ``[name, {kwargs}]``, or
   ``[name, [args]]``.

**Template Method**
   :class:`~automation_file.core.action_executor.ActionExecutor` defines the
   single-action lifecycle: resolve the name, dispatch the call, capture the
   return value or exception. The outer iteration template guarantees that one
   bad action never aborts the batch unless ``validate_first=True`` is set.

**Strategy**
   Each ``local/*_ops.py``, ``remote/*_ops.py``, and cloud subpackage is a
   collection of independent strategy functions. Every backend — local, HTTP,
   Google Drive, S3, Azure Blob, Dropbox, SFTP — is auto-registered by
   :func:`automation_file.core.action_registry.build_default_registry`. The
   ``register_<backend>_ops(registry)`` helpers stay exported for callers that
   assemble custom registries.

**Singleton (module-level)**
   ``executor``, ``callback_executor``, ``package_manager``, ``driver_instance``,
   ``s3_instance``, ``azure_blob_instance``, ``dropbox_instance``, and
   ``sftp_instance`` are shared instances wired in ``__init__`` so plugins
   pick up the same state as the CLI.

Module layout
-------------

.. code-block:: text

   automation_file/
   ├── __init__.py           # Facade — every public name
   ├── __main__.py           # CLI with subcommands
   ├── exceptions.py         # FileAutomationException hierarchy
   ├── logging_config.py     # file_automation_logger
   ├── core/
   │   ├── action_registry.py
   │   ├── action_executor.py   # serial, parallel, dry-run, validate-first
   │   ├── dag_executor.py      # topological scheduler with parallel fan-out
   │   ├── callback_executor.py
   │   ├── package_loader.py
   │   ├── plugins.py           # entry-point plugin discovery
   │   ├── json_store.py
   │   ├── retry.py             # @retry_on_transient
   │   ├── quota.py             # Quota(max_bytes, max_seconds)
   │   ├── checksum.py          # file_checksum, verify_checksum
   │   ├── manifest.py          # write_manifest, verify_manifest
   │   ├── config.py            # AutomationConfig (TOML loader + secret resolver)
   │   ├── secrets.py           # Env/File/Chained secret providers
   │   └── progress.py          # CancellationToken, ProgressReporter, progress_registry
   ├── local/
   │   ├── file_ops.py
   │   ├── dir_ops.py
   │   ├── zip_ops.py
   │   ├── sync_ops.py          # rsync-style incremental sync
   │   └── safe_paths.py        # safe_join + is_within
   ├── remote/
   │   ├── url_validator.py     # SSRF guard
   │   ├── http_download.py     # retried HTTP download
   │   ├── google_drive/
   │   ├── s3/                  # auto-registered in build_default_registry()
   │   ├── azure_blob/          # auto-registered in build_default_registry()
   │   ├── dropbox_api/         # auto-registered in build_default_registry()
   │   └── sftp/                # auto-registered in build_default_registry()
   ├── server/
   │   ├── tcp_server.py        # loopback-only, optional shared-secret
   │   └── http_server.py       # POST /actions, Bearer auth
   ├── trigger/
   │   └── manager.py           # FileWatcher + TriggerManager (watchdog-backed)
   ├── scheduler/
   │   ├── cron.py              # 5-field cron expression parser
   │   └── manager.py           # Scheduler background thread + ScheduledJob
   ├── notify/
   │   ├── sinks.py             # Webhook / Slack / Email sinks
   │   └── manager.py           # NotificationManager (fanout + dedup + auto-notify hook)
   ├── project/
   │   ├── project_builder.py
   │   └── templates.py
   ├── ui/                      # PySide6 GUI
   │   ├── launcher.py          # launch_ui(argv)
   │   ├── main_window.py       # tabbed MainWindow (Home, Local, Transfer,
   │   │                        #   Progress, JSON actions, Triggers,
   │   │                        #   Scheduler, Servers)
   │   ├── worker.py            # ActionWorker (QRunnable)
   │   ├── log_widget.py        # LogPanel
   │   └── tabs/                # one tab per backend + JSON runner + servers
   └── utils/
       ├── file_discovery.py
       ├── fast_find.py         # OS-index (mdfind/locate/es) + scandir fallback
       └── deduplicate.py       # size → partial-hash → full-hash dedup pipeline

Execution modes
---------------

The shared executor supports five orthogonal modes:

* ``execute_action(actions)`` — default serial execution; each failure is
  captured and reported without aborting the batch.
* ``execute_action(actions, validate_first=True)`` — resolve every name
  against the registry before running anything. A typo aborts the batch
  up-front instead of after half the actions have already run.
* ``execute_action(actions, dry_run=True)`` — parse each action and log what
  would be called without invoking the underlying function.
* ``execute_action_parallel(actions, max_workers=4)`` — dispatch actions
  concurrently through a thread pool. The caller is responsible for ensuring
  the chosen actions are independent.
* ``execute_action_dag(nodes, max_workers=4, fail_fast=True)`` — Kahn-style
  topological scheduling. Each node is ``{"id": str, "action": [...],
  "depends_on": [id, ...]}``. Independent branches run in parallel, failed
  branches mark their transitive dependents ``skipped`` (or still run them
  under ``fail_fast=False``). Cycles / unknown deps / duplicate ids are
  rejected before any node runs.

Reliability utilities
---------------------

* :func:`automation_file.core.retry.retry_on_transient` — decorator that
  retries ``ConnectionError`` / ``TimeoutError`` / ``OSError`` with capped
  exponential back-off. Used by :func:`automation_file.download_file`.
* :class:`automation_file.core.quota.Quota` — dataclass bundling an optional
  ``max_bytes`` size cap and an optional ``max_seconds`` time budget.
* :func:`automation_file.core.checksum.file_checksum` and
  :func:`automation_file.core.checksum.verify_checksum` — streaming file
  hashing (any :mod:`hashlib` algorithm) with constant-time digest comparison.
  :func:`automation_file.download_file` accepts ``expected_sha256=`` to
  verify the target immediately after the HTTP transfer completes.
* Resumable downloads: :func:`automation_file.download_file` accepts
  ``resume=True``, which writes to ``<target>.part`` and sends
  ``Range: bytes=<n>-`` so interrupted transfers continue from the existing
  byte count instead of restarting from zero.
* :func:`automation_file.utils.deduplicate.find_duplicates` — three-stage
  size → partial-hash → full-hash pipeline; most files never get hashed
  because unique-size buckets are discarded before any digest is read.
* :func:`automation_file.sync_dir` — incremental directory mirror with
  ``(size, mtime)`` or checksum-based change detection, optional delete
  of extras, and a dry-run mode.
* :func:`automation_file.write_manifest` /
  :func:`automation_file.verify_manifest` — JSON snapshot of every file
  digest under a root, for release-artifact verification and tamper
  detection.
* :class:`automation_file.core.progress.CancellationToken` and
  :class:`automation_file.core.progress.ProgressReporter` — opt-in per-transfer
  instrumentation. HTTP download and S3 upload/download accept a
  ``progress_name=`` kwarg that wires both primitives into the transfer loop;
  JSON actions ``FA_progress_list`` / ``FA_progress_cancel`` /
  ``FA_progress_clear`` address the central registry.

Event-driven dispatch
---------------------

Two long-running subsystems reuse the shared executor instead of forking
their own dispatch paths:

* :mod:`automation_file.trigger` wraps ``watchdog`` observers. Each
  :class:`~automation_file.trigger.FileWatcher` forwards matching filesystem
  events to an action list dispatched through the shared registry.
  :data:`~automation_file.trigger.trigger_manager` owns the name → watcher
  map so the GUI and JSON actions share one lifecycle.
* :mod:`automation_file.scheduler` runs one background thread that wakes on
  minute boundaries, iterates registered
  :class:`~automation_file.scheduler.ScheduledJob` instances, and dispatches
  every matching job on a short-lived worker thread so a slow action can't
  starve subsequent jobs.

Both dispatchers call
:func:`automation_file.notify.manager.notify_on_failure` when an action
list raises :class:`~automation_file.exceptions.FileAutomationException`.
The helper is a no-op when no sinks are registered, so auto-notification
is an opt-in side effect of registering any
:class:`~automation_file.NotificationSink`.

Notifications
-------------

:mod:`automation_file.notify` ships three concrete sinks
(:class:`~automation_file.WebhookSink`, :class:`~automation_file.SlackSink`,
:class:`~automation_file.EmailSink`) behind one
:class:`~automation_file.NotificationManager` fanout. The manager owns:

* Per-sink error isolation — one broken sink never aborts the others.
* Sliding-window dedup keyed on ``(subject, body, level)`` so a stuck
  trigger can't flood a channel.
* A shared module-level singleton
  (:data:`~automation_file.notification_manager`) so CLI, GUI, and
  long-running dispatchers all publish through one state.

Every webhook/Slack URL passes through
:func:`~automation_file.remote.url_validator.validate_http_url`, blocking
SSRF targets. Email sinks never expose the password in ``repr()``.

Configuration and secrets
-------------------------

:class:`automation_file.AutomationConfig` loads an
``automation_file.toml`` document and exposes helpers to materialise
sinks / defaults. Secret placeholders (``${env:NAME}`` /
``${file:NAME}``) resolve at load time through a
:class:`~automation_file.ChainedSecretProvider` built from
:class:`~automation_file.EnvSecretProvider` and/or
:class:`~automation_file.FileSecretProvider`. Unresolved references
raise :class:`~automation_file.SecretNotFoundException` so a typo never
silently becomes an empty string.

Security boundaries
-------------------

* **SSRF guard**: every outbound HTTP URL passes through
  :func:`automation_file.remote.url_validator.validate_http_url`.
* **Path traversal**:
  :func:`automation_file.local.safe_paths.safe_join` resolves user paths under
  a caller-specified root and rejects ``..`` escapes, absolute paths outside
  the root, and symlinks pointing out of it.
* **TCP / HTTP auth**: both servers accept an optional ``shared_secret``.
  When set, the TCP server requires ``AUTH <secret>\\n`` before the payload
  and the HTTP server requires ``Authorization: Bearer <secret>``. Both bind
  to loopback by default and refuse non-loopback binds unless
  ``allow_non_loopback=True`` is passed.
* **SFTP host verification**: the SFTP client uses
  :class:`paramiko.RejectPolicy` and never auto-adds unknown host keys.
* **Plugin loading**: :class:`automation_file.core.package_loader.PackageLoader`
  registers arbitrary module members; never expose it to untrusted input.
  The entry-point discovery path
  (:func:`automation_file.core.plugins.load_entry_point_plugins`) is safer —
  only packages the user has explicitly installed can contribute commands —
  but every plugin still runs with full library privileges, so review
  third-party plugins before installing them.

Entry-point plugins
-------------------

Third-party packages can ship extra actions without ``automation_file``
having to import them. A plugin advertises itself in its
``pyproject.toml``::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

where ``register`` is a zero-argument callable returning a
``Mapping[str, Callable]`` — the same shape you would hand to
:func:`automation_file.add_command_to_executor`.
:func:`automation_file.core.action_registry.build_default_registry`
invokes :func:`automation_file.core.plugins.load_entry_point_plugins` after
the built-ins are wired in, so installed plugins populate every
freshly-built registry automatically. Plugin failures (import errors,
factory exceptions, bad return shape, registry rejection) are logged and
swallowed so one broken plugin does not break the library.

Shared singletons
-----------------

``automation_file/__init__.py`` creates the following process-wide singletons:

* ``executor`` — :class:`ActionExecutor` used by :func:`execute_action`.
* ``callback_executor`` — :class:`CallbackExecutor` bound to ``executor.registry``.
* ``package_manager`` — :class:`PackageLoader` bound to the same registry.
* ``driver_instance``, ``s3_instance``, ``azure_blob_instance``,
  ``dropbox_instance``, ``sftp_instance`` — lazy clients for each cloud
  backend.

All executors share one :class:`ActionRegistry` instance, so calling
:func:`add_command_to_executor` (or any ``register_*_ops`` helper) makes the
new command visible to every dispatcher at once.
