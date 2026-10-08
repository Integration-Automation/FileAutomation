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
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum
   python -m automation_file drive-upload my.txt --token token.json --credentials creds.json

The ``mcp`` subcommand starts a Model Context Protocol server over stdio so
hosts such as Claude Desktop can call ``FA_*`` actions as MCP tools — see
:doc:`mcp` for the full integration guide.

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
