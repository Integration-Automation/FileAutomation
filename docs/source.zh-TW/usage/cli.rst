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
