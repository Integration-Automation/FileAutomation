CLI
===

执行 JSON 动作列表的旧式参数::

   python -m automation_file --execute_file actions.json
   python -m automation_file --execute_dir ./actions/
   python -m automation_file --execute_str '[["FA_create_dir",{"dir_path":"x"}]]'
   python -m automation_file --create_project ./my_project

一次性操作的子命令::

   python -m automation_file ui
   python -m automation_file zip ./src out.zip --dir
   python -m automation_file unzip out.zip ./restored
   python -m automation_file download https://example.com/file.bin file.bin
   python -m automation_file create-file hello.txt --content "hi"
   python -m automation_file server --host 127.0.0.1 --port 9943
   python -m automation_file http-server --host 127.0.0.1 --port 9944
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum
   python -m automation_file drive-upload my.txt --token token.json --credentials creds.json

``mcp`` 子命令通过 stdio 启动 Model Context Protocol 服务器，
让 Claude Desktop 这类宿主可以把 ``FA_*`` 动作当作 MCP 工具调用——完整集成
说明请见 :doc:`mcp`。

存储
----

``storage`` 子命令让你从 shell 使用存储层（:doc:`storage`）。每个命令都接受存储 URI
或普通的本地路径::

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

每个命令都会输出一份 JSON 文档（``cat`` 输出文件的文本内容），因此可以接到 ``jq``
或交给其他程序读取。成功时退出码为 0。``verify`` 在摘要不符时以 1 退出；``cp -r`` 与
``sync`` 在有文件失败时以 1 退出，失败项列在 ``errors`` 之下。其他失败会打印异常并
以 1 退出。

远端后端必须先初始化客户端。``--init`` 接受一份 JSON 动作列表，会在命令之前执行::

   python -m automation_file storage \
       --init '[["FA_s3_later_init", {"region_name": "us-east-1"}]]' \
       ls s3://reports
