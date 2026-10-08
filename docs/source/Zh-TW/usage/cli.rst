CLI
===

執行 JSON 動作清單的舊式參數::

   python -m automation_file --execute_file actions.json
   python -m automation_file --execute_dir ./actions/
   python -m automation_file --execute_str '[["FA_create_dir",{"dir_path":"x"}]]'
   python -m automation_file --create_project ./my_project

一次性操作的子指令::

   python -m automation_file ui
   python -m automation_file zip ./src out.zip --dir
   python -m automation_file unzip out.zip ./restored
   python -m automation_file download https://example.com/file.bin file.bin
   python -m automation_file create-file hello.txt --content "hi"
   python -m automation_file server --host 127.0.0.1 --port 9943
   python -m automation_file http-server --host 127.0.0.1 --port 9944
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum
   python -m automation_file drive-upload my.txt --token token.json --credentials creds.json

``mcp`` 子指令以 stdio 啟動 Model Context Protocol 伺服器，
讓 Claude Desktop 之類的宿主可把 ``FA_*`` 動作當成 MCP 工具呼叫——
完整整合說明請見 :doc:`mcp`。

儲存
----

``storage`` 子指令讓你從 shell 使用儲存層（:doc:`storage`）。每個指令都接受儲存 URI
或一般的本機路徑::

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

每個指令都會輸出一份 JSON 文件（``cat`` 輸出檔案的文字內容），因此可以接到 ``jq``
或交給其他程式讀取。成功時結束碼為 0。``verify`` 在摘要不符時以 1 結束；``cp -r`` 與
``sync`` 在有檔案失敗時以 1 結束，失敗項目列在 ``errors`` 之下。其他失敗會印出例外並
以 1 結束。

遠端後端必須先初始化用戶端。``--init`` 接受一份 JSON 動作清單，會在指令之前執行::

   python -m automation_file storage \
       --init '[["FA_s3_later_init", {"region_name": "us-east-1"}]]' \
       ls s3://reports
