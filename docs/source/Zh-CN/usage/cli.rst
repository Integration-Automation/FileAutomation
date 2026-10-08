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
   python -m automation_file mcp --root /srv/reports --no-bridge
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum
   python -m automation_file drive-upload my.txt --token token.json --credentials creds.json

``mcp`` 子命令通过 stdio 启动 Model Context Protocol 服务器，让 Claude Desktop 这类
宿主可以处理文件：一是通过语义工具（``file_read``、``storage_copy``、
``pipeline_run`` ……），它们只在 ``--root`` 指定的位置之内工作，而且在
``--allow-write`` 之前都是只读的；二是通过把 ``FA_*`` 动作当作 MCP 工具提供的桥接。
命令行参数、权限模型与完整集成说明请见 :doc:`mcp`。

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

完整性
------

``integrity`` 子命令可以为任何存储后端中的目录树建立基准并加以验证（:doc:`integrity`）。
目标与基准都是存储 URI 或普通的本地路径::

   python -m automation_file integrity baseline s3://reports/2026 reports.baseline.json
   python -m automation_file integrity verify s3://reports/2026 reports.baseline.json
   python -m automation_file integrity verify ./site site.baseline.json --quick
   python -m automation_file integrity accept ./site site.baseline.json
   python -m automation_file integrity snapshot ./site --algorithm sha512

``baseline`` 把目录树当前的状态核准为基准，``verify`` 把它与基准比对并输出偏移报告，
``accept`` 在检查之后把当前的状态核准为新基准，``snapshot`` 只输出 manifest 而不存储
任何东西。``verify`` 在目录树出现偏移时以 1 退出，因此 shell 脚本或 CI 作业可以据此
把关；``--quick`` 只对大小、修改时间或 etag 有变动的文件计算哈希。``--init`` 的用法与
``storage`` 相同。持续监控与监听需要一个持续存活的进程：请使用 Python API 或
``FA_integrity_watch_*`` 动作。

流水线
------

``pipeline`` 子命令可以验证、运行并查看以 YAML 或 JSON 定义编写的流水线
（:doc:`pipeline`）::

   python -m automation_file pipeline validate daily.yaml
   python -m automation_file pipeline run daily.yaml --param date=2026-10-08 --store runs.db
   python -m automation_file pipeline run daily.yaml --dry-run
   python -m automation_file pipeline status <run-id> --store runs.db
   python -m automation_file pipeline history --pipeline daily-report --limit 10 --store runs.db
   python -m automation_file pipeline resume <run-id> daily.yaml --store runs.db

``--param name=value`` 可以重复指定；值如果是合法的 JSON 会保留其类型
（``--param retries=3``、``--param tags='["a","b"]'``），其余一律视为字符串。
``validate`` 在定义无效时以 1 退出，并输出每个问题及其路径。``run`` 与 ``resume``
会输出该次运行，除非运行成功，否则以 1 退出。

运行记录默认只存在于运行它的进程的内存中。传入 ``--store`` 与一个 SQLite 文件的
路径即可保存：``status``、``history`` 与 ``resume`` 会读取同一个文件来找到先前命令
的运行；没有它，这些命令只知道自己进程中的运行，也就是没有。

审计
----

在 ``storage``、``integrity`` 与 ``pipeline`` 加上 ``--audit <文件>``，就会把该命令的
事件与存储操作记录到审计轨迹（:doc:`audit`），actor 为 ``cli:<用户>``。``audit``
子命令用来读取这份轨迹::

   python -m automation_file pipeline --audit audit.sqlite run daily.yaml --store runs.db
   python -m automation_file storage --audit audit.sqlite cp report.csv s3://reports/report.csv
   python -m automation_file audit search --db audit.sqlite --status error --limit 20
   python -m automation_file audit search --db audit.sqlite --correlation-id <run-id>
   python -m automation_file audit count --db audit.sqlite --since 2026-10-01 --backend s3
   python -m automation_file audit purge --db audit.sqlite --older-than-days 90

``search`` 由新到旧输出符合条件的记录，可以使用 ``--since``、``--until``、``--actor``、
``--source``、``--pipeline``、``--task``、``--action``、``--resource-prefix``、
``--backend``、``--status``、``--correlation-id``、``--text``、``--limit`` 与
``--offset``。``count`` 接受相同的筛选条件。``--since`` 与 ``--until`` 接受 ISO 8601 的
日期或时间，没有 UTC 偏移时视为本地时间。``purge`` 会删除早于指定天数的记录，并输出
删除的条数。流水线运行的 ID 就是它的关联 ID，因此一次搜索就能看到一次运行所做的一切。
