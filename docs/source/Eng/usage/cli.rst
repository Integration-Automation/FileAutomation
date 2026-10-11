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

Exit status of the legacy flags
-------------------------------

``-e``, ``-d`` and ``--execute_str`` exit with status 1 when an action of the list failed. A failed
action does not stop the list: the rest runs first, and ``error: N action(s) failed`` is printed on
stderr at the end. A script that cannot be read exits with 1 as before.
