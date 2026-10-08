CLI
===

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
   python -m automation_file mcp --root /srv/reports --no-bridge
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum
   python -m automation_file drive-upload my.txt --token token.json --credentials creds.json

The ``mcp`` subcommand starts a Model Context Protocol server over stdio so
hosts such as Claude Desktop can work with files: through the semantic tools
(``file_read``, ``storage_copy``, ``pipeline_run``, ...), which stay inside the
``--root`` locations and are read-only until ``--allow-write``, and through the
bridge that offers ``FA_*`` actions as MCP tools. See :doc:`mcp` for the flags,
the permission model and the full integration guide.

Storage
-------

The ``storage`` subcommand reaches the storage layer (:doc:`storage`) from a
shell. Every command takes storage URIs or plain local paths::

   python -m automation_file storage ls s3://reports/2026 --recursive
   python -m automation_file storage stat s3://reports/2026/q1.csv
   python -m automation_file storage cat local:///etc/hostname
   python -m automation_file storage cp report.csv s3://reports/2026/report.csv
   python -m automation_file storage cp -r ./site s3://www/site --no-overwrite
   python -m automation_file storage mv s3://inbox/a.csv s3://archive/a.csv
   python -m automation_file storage rm s3://tmp/old --recursive --missing-ok
   python -m automation_file storage mkdir local:///data/new
   python -m automation_file storage sync ./site s3://www --delete --dry-run
   python -m automation_file storage checksum s3://reports/2026/q1.csv --algorithm sha512
   python -m automation_file storage verify s3://reports/2026/q1.csv sha256:9f86d081...
   python -m automation_file storage schemes

Each command prints one JSON document (``cat`` prints the file's text), so the
output can be piped into ``jq`` or read by another program. The exit code is 0 on
success. ``verify`` exits 1 when the digest does not match; ``cp -r`` and ``sync``
exit 1 when a file failed, with the failures under ``errors``. Any other failure
prints the exception and exits 1.

A remote backend needs its client initialised first. ``--init`` takes a JSON
action list that runs before the command::

   python -m automation_file storage \
       --init '[["FA_s3_later_init", {"region_name": "us-east-1"}]]' \
       ls s3://reports

Integrity
---------

The ``integrity`` subcommand baselines and verifies a directory tree in any
storage backend (:doc:`integrity`). The target and the baseline are storage URIs
or plain local paths::

   python -m automation_file integrity baseline s3://reports/2026 reports.baseline.json
   python -m automation_file integrity verify s3://reports/2026 reports.baseline.json
   python -m automation_file integrity verify ./site site.baseline.json --quick
   python -m automation_file integrity accept ./site site.baseline.json
   python -m automation_file integrity snapshot ./site --algorithm sha512

``baseline`` approves the tree as it is now, ``verify`` compares it with that
baseline and prints the drift report, ``accept`` approves the current tree after a
review, and ``snapshot`` prints the manifest without storing anything. ``verify``
exits 1 when the tree drifted, so a shell script or a CI job can gate on it;
``--quick`` hashes only the files whose size, modification time or etag changed.
``--init`` works as it does for ``storage``. Continuous monitoring and watching
need a process that stays alive: use the Python API or the ``FA_integrity_watch_*``
actions for those.

Pipelines
---------

The ``pipeline`` subcommand validates, runs and inspects pipelines written as
YAML or JSON definitions (:doc:`pipeline`)::

   python -m automation_file pipeline validate daily.yaml
   python -m automation_file pipeline run daily.yaml --param date=2026-10-08 --store runs.db
   python -m automation_file pipeline run daily.yaml --dry-run
   python -m automation_file pipeline status <run-id> --store runs.db
   python -m automation_file pipeline history --pipeline daily-report --limit 10 --store runs.db
   python -m automation_file pipeline resume <run-id> daily.yaml --store runs.db

``--param name=value`` may be repeated; a value that is valid JSON keeps its type
(``--param retries=3``, ``--param tags='["a","b"]'``), anything else is a string.
``validate`` exits 1 when the definition is invalid and prints every problem with
its path. ``run`` and ``resume`` print the run and exit 1 unless it succeeded.

A run is recorded in the memory of the process that made it. Pass ``--store`` with
the path of a SQLite file to keep it: ``status``, ``history`` and ``resume`` read
the same file to find a run of an earlier command, and without it they only know
the runs of their own process, which is none.

Audit
-----

``--audit <file>`` on ``storage``, ``integrity`` and ``pipeline`` records the
command's events and storage operations in an audit trail (:doc:`audit`), with
the actor ``cli:<user>``. The ``audit`` subcommand reads that trail::

   python -m automation_file pipeline --audit audit.sqlite run daily.yaml --store runs.db
   python -m automation_file storage --audit audit.sqlite cp report.csv s3://reports/report.csv
   python -m automation_file audit search --db audit.sqlite --status error --limit 20
   python -m automation_file audit search --db audit.sqlite --correlation-id <run-id>
   python -m automation_file audit count --db audit.sqlite --since 2026-10-01 --backend s3
   python -m automation_file audit purge --db audit.sqlite --older-than-days 90

``search`` prints the matching records newest first and takes ``--since``,
``--until``, ``--actor``, ``--source``, ``--pipeline``, ``--task``, ``--action``,
``--resource-prefix``, ``--backend``, ``--status``, ``--correlation-id``,
``--text``, ``--limit`` and ``--offset``. ``count`` takes the same filters.
``--since`` and ``--until`` take an ISO 8601 date or time; one without a UTC
offset is read as local time.
``purge`` deletes the records older than a number of days and prints how many it
removed. A pipeline run's ID is its correlation ID, so one search shows everything
a run did.
