File integrity monitoring
=========================

``automation_file.integrity`` answers one question about a directory tree: is it
still what was approved? An
:class:`~automation_file.integrity.monitor.IntegrityMonitor` records the approved
state as a *baseline*, compares the tree with it, and reports every difference
as a change of one of six kinds.

It reads through the :doc:`storage layer <storage>`, so the tree and the baseline
are storage URIs and may live in any backend. Drift is published as an event
(:doc:`event_bus`); the monitor never calls a notification sink itself. It only
reads, unless you pass a remediation policy.

``IntegrityMonitor`` is still importable from ``automation_file`` and from
``automation_file.core.fim``, and the call written for the first monitor keeps
working (`The first monitor`_).

Minimal example
---------------

.. code-block:: python

   from automation_file.integrity import IntegrityMonitor

   monitor = IntegrityMonitor("/srv/site", baseline="/var/lib/fa/site.baseline.json")
   monitor.create_baseline()                 # approve what is there now

   report = monitor.verify()                 # hash every file, compare with the baseline
   if not report.ok:
       print(report.counts)                  # {'created': 0, 'modified': 1, 'deleted': 0, ...}
       for change in report.changes:
           print(change.kind.value, change.path)
       monitor.accept(report)                # after review: approve what the report saw

Production example
------------------

The baseline is kept outside the bucket it describes, the monitor verifies on a
thread, the event is routed to a notification sink, and remediation is switched
on explicitly.

.. code-block:: python

   import json

   from automation_file import Severity, SlackSink, event_bus, notification_manager, s3_instance
   from automation_file.integrity import IntegrityMonitor, RemediationPolicy

   s3_instance.later_init(region_name="eu-west-1")
   notification_manager.register(SlackSink(slack_webhook_url))

   def route(event):
       level = "error" if event.severity.at_least(Severity.ERROR) else "warning"
       details = event.payload.get("error") or json.dumps(event.payload.get("counts", {}))
       notification_manager.notify(event.subject, details, level)

   # integrity.violation and integrity.remediated; a successful remediation is "info".
   event_bus.subscribe(route, types="integrity.*", min_severity=Severity.WARNING)

   monitor = IntegrityMonitor(
       "s3://reports/2026",
       baseline="local:///var/lib/fa/baselines/reports-2026.json",
       algorithm="sha256",
       interval=900,                                   # continuous mode: every 15 minutes
       remediation=RemediationPolicy(                  # opt-in; without it nothing is changed
           quarantine="s3://reports-quarantine/2026",
           restore_from="s3://reports-mirror/2026",
           on_created="quarantine",
           on_modified="restore",
           on_deleted="restore",
       ),
   )
   if not monitor.has_baseline():
       monitor.create_baseline()

   monitor.start()                                     # a daemon thread; returns at once
   ...
   monitor.status()                                    # running, last_run, last_error, last_report
   monitor.stop()

Keep the baseline where whoever can change the tree cannot change the baseline.
A baseline inside the target works, and the monitor leaves that file out of its
snapshots, but then one write access covers both.

The four modes
--------------

.. list-table::
   :header-rows: 1
   :widths: 16 30 54

   * - Mode
     - Call
     - What it does
   * - snapshot
     - ``monitor.snapshot()``
     - Reads the tree and returns a
       :class:`~automation_file.integrity.snapshot.Snapshot`. Nothing is stored
       and no baseline is needed.
   * - verify
     - ``monitor.verify(deep=True)``
     - Compares the tree with the baseline once and returns a
       :class:`~automation_file.integrity.report.DriftReport`.
   * - watch
     - ``monitor.watch()``
     - Reacts to changes as they happen and returns a handle with ``stop()``. A
       local target is observed through filesystem events: paths that change
       within ``debounce`` seconds (0.5 by default) are verified together, and
       only those paths are read. Any other backend is polled with a quick pass
       every ``poll_interval`` seconds. A drift is reported when it appears, not
       again while it stays the same.
   * - continuous
     - ``monitor.start()`` / ``monitor.stop()``
     - Verifies every ``interval`` seconds (60 by default) on a daemon thread;
       the first pass runs after one interval. Every pass that finds drift
       publishes an event.

``monitor.create_baseline()`` stores a snapshot as the baseline, and
``monitor.accept(report)`` approves a drift. With a report, ``accept`` stores
exactly the tree that verification saw, so a change made after the report is not
approved unseen; without one it reads the tree again.

``monitor.verify_paths(["a.txt", "config"])`` verifies only those paths (a
directory stands for everything below it) and marks the report ``partial``. Watch
mode runs it for the paths that changed; call it yourself when something else,
such as a bucket notification, tells you what changed.

Watching does not verify the tree when it starts, and an operating system drops
events without notice when its queue overflows. Watch mode shortens the time to
detection; a periodic deep verification is still what proves the tree.

Deep and quick verification
---------------------------

``verify(deep=True)`` hashes every file. On a remote backend that means reading
every file.

``verify(deep=False)`` first compares the size, the modification time and the
etag of each file with the baseline and hashes only the files where one of them
differs. The report says so: ``report.deep`` is ``False``, ``report.hashed``
counts the files that were read out of ``report.checked``, and ``report.notes``
holds ``"quick pass: 2 of 1840 files hashed; size, modification time and etag
decided the rest"``. A change that keeps all three goes unnoticed by a quick
pass, so schedule a deep one as well. A baseline entry that recorded neither a
time nor an etag (the legacy format) is always hashed.

A report holds ``changes``, ``counts`` (one number per kind, zeros included),
``ok``, ``deep``, ``partial``, ``checked``, ``hashed``, ``notes``,
``remediation``, ``verified_at`` and ``correlation_id``. ``report.to_dict()`` is
JSON-serialisable.

The manifest
------------

A baseline is one JSON document, the *manifest*, with a schema version:

.. code-block:: json

   {
     "schema_version": 2,
     "created_at": "2026-10-08T10:15:30.123456+00:00",
     "root": "s3://reports/2026",
     "backend": "s3",
     "algorithm": "sha256",
     "entries": [
       {
         "path": "q1.csv",
         "size": 1024,
         "modified_at": "2026-10-01T08:00:00+00:00",
         "checksum": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
         "algorithm": "sha256",
         "content_type": "text/csv",
         "backend": "s3",
         "version": null,
         "etag": "5d41402abc4b2a76b9719d911017c592",
         "mode": null
       }
     ]
   }

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Field
     - Meaning
   * - ``schema_version``
     - ``2``. Any other number is refused with an ``IntegrityException``, so a
       document from a newer release is never half-understood.
   * - ``created_at``
     - When the snapshot was taken, ISO 8601 in UTC.
   * - ``root``, ``backend``
     - The URI of the tree and the scheme of the backend that served it.
   * - ``algorithm``
     - The hash algorithm of every checksum. A verification hashes with it.
   * - ``entries``
     - One object per file, sorted by ``path`` (relative to ``root``, ``/``
       separators). Directories are not recorded, so an empty directory is
       invisible.
   * - ``size``, ``modified_at``, ``content_type``, ``version``, ``etag``
     - What the backend reports. A field it cannot provide is ``null``.
   * - ``mode``
     - The permission bits as an integer (``420`` is ``0o644``). Recorded only
       for a file on the local filesystem.

The manifest written by ``write_manifest`` / ``FA_write_manifest`` (no
``schema_version``, a ``files`` mapping with ``size`` and ``checksum``) is read
too and converted on the way. ``create_baseline()`` and ``accept()`` always write
version 2; after that ``verify_manifest`` refuses the file with a
``ManifestException`` that names ``FA_integrity_verify``.

The Baseline Manager writes the manifest to a temporary sibling file and moves
it over the baseline, so a reader never sees a half-written document. The move
is a rename on the local filesystem and one whole write of the finished file
elsewhere.

Change kinds
------------

.. list-table::
   :header-rows: 1
   :widths: 24 60 16

   * - Kind
     - Reported when
     - Severity
   * - ``created``
     - A path the baseline does not have.
     - warning
   * - ``modified``
     - The checksum, or the recorded size, differs.
     - error
   * - ``deleted``
     - A path of the baseline is gone.
     - error
   * - ``renamed``
     - One deleted and one created file have the same checksum and size.
       ``change.previous_path`` is the old path.
     - error
   * - ``metadata_changed``
     - Same checksum, but the modification time, content type, version or etag
       differs; ``change.fields`` names which. A field one side did not record is
       not compared.
     - warning
   * - ``permission_changed``
     - The permission bits differ. Reported next to ``modified`` when both
       happened.
     - error

When several deleted or several created files share one checksum, the pairing is
ambiguous. They are then reported as ``deleted`` and ``created``, each with
``change.note`` set to ``"ambiguous rename: 2 deleted and 1 created files share
the checksum 9f86d081884c...; reported separately"``.

Events
------

Each verification that finds drift publishes one
:class:`~automation_file.events.model.IntegrityViolation` on ``event_bus``, or on
the bus passed as ``bus=``. The verification runs in a correlation scope, so the
event, the remediation events and ``report.correlation_id`` share one ID, and an
enclosing scope's ID is kept.

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Field
     - Value
   * - ``type``, ``source``
     - ``integrity.violation``, ``integrity``
   * - ``severity``
     - The worst severity among the kinds found: ``error`` when something was
       modified, deleted, renamed or had its permissions changed, ``warning``
       when there are only additions or metadata changes.
   * - ``payload["resource"]``, ``["backend"]``
     - The URI of the target and its backend.
   * - ``payload["status"]``
     - ``drift``, or ``error`` when the pass could not run (then
       ``payload["error"]`` says why).
   * - ``payload["counts"]``
     - The number of changes of each kind.
   * - ``payload["changes"]``
     - The first 20 changes as ``{"kind": ..., "path": ...}``; ``total`` is the
       real number and ``truncated`` says whether some were left out.
   * - ``payload["baseline"]``, ``["algorithm"]``, ``["deep"]``, ``["partial"]``
     - What the pass was compared with and how thorough it was.

Pass ``alerts=AlertPolicy(severities={"created": "error"}, max_changes=50)`` to
change the severity of a kind or the number of changes listed.

``verify()`` raises when it cannot run. Continuous mode, watch mode and
``check_once()`` have nobody to raise to: they publish the same event with
``status: "error"``, keep the reason in ``monitor.last_error``, and go on.

Remediation
-----------

Off by default. Nothing is moved or copied unless a
:class:`~automation_file.integrity.remediation.RemediationPolicy` is passed to
the monitor, and a policy with every action left at ``"none"`` does nothing.

.. code-block:: python

   RemediationPolicy(
       quarantine="s3://reports-quarantine/2026",   # or None
       restore_from="s3://reports-mirror/2026",     # or None; a mirror of the baseline
       on_created="quarantine",                     # "none" | "quarantine"
       on_modified="restore",                       # "none" | "quarantine" | "restore"
       on_deleted="restore",                        # "none" | "restore"
   )

``quarantine``
    Moves the offending file to ``<quarantine>/<UTC timestamp>/<path>``. All
    files of one pass share a timestamp directory, and nothing in the quarantine
    is ever overwritten.

``restore``
    Copies the file back from ``restore_from``. The mirror's copy is hashed
    first and refused when it does not match the baseline, so a stale or
    tampered mirror is never copied into place; the restored file is hashed
    again before the step counts as done. A modified file is moved to the
    quarantine first when one is configured. Without a quarantine its content is
    overwritten.

A rename is handled as its two halves: the old path as deleted, the new one as
created. Metadata and permission changes are never remediated. The quarantine
and the mirror must lie outside the target.

Each step is recorded in ``report.remediation`` (``action``, ``path``, ``kind``,
``ok``, ``source``, ``destination``, ``error``) and published as an
``IntegrityRemediated`` event of type ``integrity.remediated``: ``info`` when it
worked, ``error`` when it failed. A step that fails is reported and never raised;
the file stays as it was. The report describes the tree before remediation, so
``accept(report)`` reads the tree again when steps were taken.

A restored file has a new modification time, which the next verification reports
as ``metadata_changed`` until the baseline is accepted.

Algorithms
----------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Algorithm
     - Use
   * - ``sha256``
     - The default.
   * - ``sha512``, ``blake2b``
     - Alternatives of at least the same strength.
   * - ``md5``, ``sha1``
     - Refused unless ``allow_weak=True`` is passed. Both have practical
       collisions: a file can be replaced by another with the same digest and
       the change goes unnoticed. They exist to keep reading a baseline that was
       written with one of them, never as a default.

``algorithm=`` is what ``snapshot()`` and ``create_baseline()`` hash with. A
verification always hashes with the algorithm of the baseline it reads, and
``accept()`` keeps it. To move a baseline to another algorithm, review the tree
and call ``create_baseline()`` on a monitor created with the new one.

Files are hashed in parallel on a thread pool (``max_workers=8`` by default)
through the storage layer's ``checksum``.

Actions
-------

.. list-table::
   :header-rows: 1
   :widths: 30 36 34

   * - Action
     - Parameters
     - Returns
   * - ``FA_integrity_snapshot``
     - ``target, algorithm="sha256"``
     - The snapshot: ``root``, ``backend``, ``algorithm``, ``created_at``,
       ``entries``
   * - ``FA_integrity_baseline``
     - ``target, baseline, algorithm="sha256"``
     - ``target``, ``baseline``, ``backend``, ``algorithm``, ``created_at`` and
       the number of ``entries``
   * - ``FA_integrity_verify``
     - ``target, baseline, deep=True``
     - The drift report
   * - ``FA_integrity_accept``
     - ``target, baseline``
     - As ``FA_integrity_baseline``
   * - ``FA_integrity_watch_start``
     - ``name, target, baseline, interval=60.0``
     - The status of the new monitor
   * - ``FA_integrity_watch_stop``
     - ``name``
     - Its last status
   * - ``FA_integrity_status``
     - ``name=None``
     - A list of statuses: one monitor, or all of them

``FA_integrity_watch_start`` keeps a named monitor in continuous mode until
``FA_integrity_watch_stop``; the baseline must exist first. A status holds
``name``, ``target``, ``baseline``, ``algorithm``, ``interval``, ``running``,
``last_run``, ``last_error`` and ``last_report``.

.. code-block:: json

   [
     ["FA_integrity_baseline", {"target": "s3://reports/2026",
                                "baseline": "local:///var/lib/fa/reports-2026.json"}],
     ["FA_integrity_verify", {"target": "s3://reports/2026",
                              "baseline": "local:///var/lib/fa/reports-2026.json",
                              "deep": false}],
     ["FA_integrity_watch_start", {"name": "reports", "target": "s3://reports/2026",
                                   "baseline": "local:///var/lib/fa/reports-2026.json",
                                   "interval": 900}],
     ["FA_integrity_status", {"name": "reports"}]
   ]

The actions publish drift on the process-wide ``event_bus``. They take no weak
algorithm and no remediation policy: both can only be chosen in Python. Like the
storage actions they reach whatever the process can reach, and
``FA_integrity_baseline`` and ``FA_integrity_accept`` write a file, so on a TCP
or HTTP action server pass an ``ActionACL``, and on the MCP server
``--allowed-actions``, to expose only what a client needs.
``register_integrity_ops(registry)`` adds them to a registry of your own.

The first monitor
-----------------

Code written for the first ``IntegrityMonitor`` keeps working:

.. code-block:: python

   from automation_file import IntegrityMonitor, notification_manager, write_manifest

   write_manifest("/srv/site", "/srv/MANIFEST.json")
   monitor = IntegrityMonitor(
       "/srv/site",                 # root= and manifest_path= are still accepted as keywords
       "/srv/MANIFEST.json",
       interval=60.0,
       manager=notification_manager,
       on_drift=lambda summary: print("drift:", summary),
   )
   summary = monitor.check_once()   # {"matched": [...], "missing": [...], "modified": [...],
                                    #  "extra": [...], "ok": False}
   monitor.start()

``check_once()`` returns the same summary dictionary, with ``error`` when the
pass could not run; ``on_drift`` receives it, and ``last_summary`` keeps it. As
before, additions do not count as drift for ``on_drift`` and the notification
unless ``alert_on_extra=True``, and a rename appears as ``missing`` plus
``extra``.

The notification goes where it went before: through the ``manager`` you pass,
or through the process-wide ``notification_manager`` when you pass none. One
thing was added: every drift, additions included, is also published as an
``IntegrityViolation`` event. While the notification router is active
(:doc:`notifications`), its routes deliver that event and the process-wide
manager is not notified directly, so one drift is not announced twice; a
``manager`` you pass is always notified. ``notify=False`` turns the direct
notification off altogether.

When something fails
--------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - What you see
     - What it means and what to do
   * - ``IntegrityException: no baseline at …``
     - Nothing is stored at the baseline URI. Check the URI, then call
       ``create_baseline()``. A baseline that disappears from a running monitor
       is itself a finding: it arrives as an event with ``status: "error"``.
   * - ``… is not readable JSON`` / ``… is not a valid manifest``
     - The baseline is damaged or was edited. Restore it from a copy, or review
       the tree and create it again. Do not accept a tree you cannot compare.
   * - ``… has manifest schema version 3``
     - The baseline was written by a newer release. Upgrade, or create the
       baseline again with this one.
   * - ``md5 is refused for integrity checks …``
     - The baseline uses a weak algorithm. Pass ``allow_weak=True`` to read it,
       then call ``create_baseline()`` with ``sha256``.
   * - ``target … does not exist``
     - The directory is missing on a filesystem. On an object store a prefix
       that holds nothing is an empty tree instead: every file is ``deleted``.
   * - ``StorageUnavailableException``
     - The backend is not initialised: call ``s3_instance.later_init(...)`` or
       the equivalent first.
   * - ``StoragePermissionException`` or ``StorageTransientException`` during a
       pass
     - The pass fails as a whole; a tree that could not be read completely is
       never reported as clean. Continuous mode tries again after ``interval``.
   * - A quick pass is clean, a deep pass reports ``modified``
     - The content changed while size and modification time stayed the same.
       Ordinary tools do not do that; treat it as tampering.
   * - Everything is ``metadata_changed``
     - The files were copied or restored, which gives them new times. Review,
       then ``accept()``.
   * - A remediation step has ``ok: False``
     - ``step.error`` says why (no copy in the mirror, a mirror that does not
       match the baseline, access denied). The file was left as it was; an
       ``integrity.remediated`` event of severity ``error`` was published.
   * - The same event on every interval
     - Continuous mode reports a drift on every pass for as long as it lasts.
       Fix the tree or ``accept()`` it, or deduplicate in the subscriber (the
       ``NotificationManager`` does).
   * - Watch mode missed a change
     - Filesystem events can be lost. Run a deep ``verify()`` on a schedule next
       to the watch.

One monitor runs one pass at a time: a ``verify()`` called while the continuous
thread is in a pass waits for it.
