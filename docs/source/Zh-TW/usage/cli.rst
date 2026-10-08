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

完整性
------

``integrity`` 子指令可為任何儲存後端中的目錄樹建立基準並加以驗證（:doc:`integrity`）。
目標與基準都是儲存 URI 或一般的本機路徑::

   python -m automation_file integrity baseline s3://reports/2026 reports.baseline.json
   python -m automation_file integrity verify s3://reports/2026 reports.baseline.json
   python -m automation_file integrity verify ./site site.baseline.json --quick
   python -m automation_file integrity accept ./site site.baseline.json
   python -m automation_file integrity snapshot ./site --algorithm sha512

``baseline`` 把目錄樹目前的狀態核可為基準，``verify`` 把它與基準比對並輸出偏移報告，
``accept`` 在檢視之後把目前的狀態核可為新基準，``snapshot`` 只輸出 manifest 而不儲存
任何東西。``verify`` 在目錄樹出現偏移時以 1 結束，因此 shell 腳本或 CI 工作可以據此
把關；``--quick`` 只對大小、修改時間或 etag 有變動的檔案計算雜湊。``--init`` 的用法與
``storage`` 相同。持續監控與監看需要一個持續存活的行程：請使用 Python API 或
``FA_integrity_watch_*`` 動作。

管線
----

``pipeline`` 子指令可驗證、執行並檢視以 YAML 或 JSON 定義撰寫的管線
（:doc:`pipeline`）::

   python -m automation_file pipeline validate daily.yaml
   python -m automation_file pipeline run daily.yaml --param date=2026-10-08 --store runs.db
   python -m automation_file pipeline run daily.yaml --dry-run
   python -m automation_file pipeline status <run-id> --store runs.db
   python -m automation_file pipeline history --pipeline daily-report --limit 10 --store runs.db
   python -m automation_file pipeline resume <run-id> daily.yaml --store runs.db

``--param name=value`` 可以重複指定；值若是合法的 JSON 會保留其型別
（``--param retries=3``、``--param tags='["a","b"]'``），其餘一律視為字串。
``validate`` 在定義無效時以 1 結束，並輸出每個問題及其路徑。``run`` 與 ``resume``
會輸出該次執行，除非執行成功，否則以 1 結束。

執行紀錄預設只存在於執行它的行程的記憶體中。傳入 ``--store`` 與一個 SQLite 檔案的
路徑即可保存：``status``、``history`` 與 ``resume`` 會讀取同一個檔案來找到先前指令
的執行；沒有它，這些指令只知道自己行程中的執行，也就是沒有。

稽核
----

在 ``storage``、``integrity`` 與 ``pipeline`` 加上 ``--audit <檔案>``，就會把該指令的
事件與儲存操作記錄到稽核軌跡（:doc:`audit`），actor 為 ``cli:<使用者>``。``audit``
子指令用來讀取這份軌跡::

   python -m automation_file pipeline --audit audit.sqlite run daily.yaml --store runs.db
   python -m automation_file storage --audit audit.sqlite cp report.csv s3://reports/report.csv
   python -m automation_file audit search --db audit.sqlite --status error --limit 20
   python -m automation_file audit search --db audit.sqlite --correlation-id <run-id>
   python -m automation_file audit count --db audit.sqlite --since 2026-10-01 --backend s3
   python -m automation_file audit purge --db audit.sqlite --older-than-days 90

``search`` 由新到舊輸出符合條件的紀錄，可使用 ``--since``、``--until``、``--actor``、
``--source``、``--pipeline``、``--task``、``--action``、``--resource-prefix``、
``--backend``、``--status``、``--correlation-id``、``--text``、``--limit`` 與
``--offset``。``count`` 接受相同的篩選條件。``--since`` 與 ``--until`` 接受 ISO 8601 的
日期或時間，沒有 UTC 偏移時視為本地時間。``purge`` 會刪除早於指定天數的紀錄，並輸出
刪除的筆數。管線執行的 ID 就是它的關聯 ID，因此一次搜尋就能看到一次執行所做的一切。
