# FileAutomation

[English](README.md) | [繁體中文](README.zh-TW.md) | **简体中文**

一套模块化的自动化框架，涵盖本地文件 / 目录 / ZIP 操作、经 SSRF 验证的 HTTP
下载、远程存储（Google Drive、S3、Azure Blob、Dropbox、SFTP），以及通过内嵌
TCP / HTTP 服务器执行的 JSON 驱动动作。内附 PySide6 GUI，每个功能都有对应
页签。所有公开 API 均由顶层 `automation_file` facade 统一导出。

- 本地文件 / 目录 / ZIP 操作，内置路径穿越防护（`safe_join`）
- 经 SSRF 验证的 HTTP 下载，支持重试与大小 / 时间上限
- Google Drive CRUD（上传、下载、搜索、删除、分享、文件夹）
- 一等公民的 S3、Azure Blob、Dropbox、SFTP 后端 — 默认安装
- JSON 动作清单由共享的 `ActionExecutor` 执行 — 支持验证、干跑、并行
- Loopback 优先的 TCP **与** HTTP 服务器，接受 JSON 指令批量并可选 shared-secret 验证
- 可靠性原语：`retry_on_transient` 装饰器、`Quota` 大小 / 时间预算
- **文件监听触发** — 当路径变动时执行动作清单（`FA_watch_*`）
- **Cron 调度器** — 仅用标准库的 5 字段解析器执行周期性动作清单（`FA_schedule_*`）
- **传输进度 + 取消** — HTTP 与 S3 传输可选的 `progress_name` 钩子（`FA_progress_*`）
- **快速文件搜索** — OS 索引快速路径（`mdfind` / `locate` / `es.exe`）搭配流式 `scandir` 回退（`FA_fast_find`）
- **校验和 + 完整性验证** — 流式 `file_checksum` / `verify_checksum`，支持任何 `hashlib` 算法；`download_file(expected_sha256=...)` 在下载完成后立即验证（`FA_file_checksum`、`FA_verify_checksum`）
- **可续传 HTTP 下载** — `download_file(resume=True)` 写入 `<target>.part` 并发送 `Range: bytes=<n>-`，让中断的传输继续而非从头开始
- **重复文件查找器** — 三阶段 size → 部分哈希 → 完整哈希管线；大小唯一的文件完全不会被哈希（`FA_find_duplicates`）
- **DAG 动作执行器** — 按依赖顺序拓扑调度，独立分支并行展开，失败时其后代默认标记为跳过（`FA_execute_action_dag`）
- **Entry-point 插件** — 第三方包通过 `[project.entry-points."automation_file.actions"]` 注册自定义 `FA_*` 动作；`build_default_registry()` 会自动加载
- **增量目录同步** — rsync 风格镜像，支持 size+mtime 或 checksum 变更检测，可选删除多余文件，支持干跑（`FA_sync_dir`）
- **目录 manifest** — 以 JSON 快照记录树下每个文件的校验和，验证时分开报告 missing / modified / extra（`FA_write_manifest`、`FA_verify_manifest`）
- **通知 sink** — webhook / Slack / SMTP / Telegram / Discord / Teams / PagerDuty，fanout 管理器做单 sink 错误隔离与滑动窗口去重；trigger + scheduler 失败时自动通知（`FA_notify_send`、`FA_notify_list`）
- **配置文件 + 密钥提供者** — 在 `automation_file.toml` 声明通知 sink / 默认值；`${env:…}` 与 `${file:…}` 引用通过 Env / File / Chained 提供者抽象解析，让密钥不留在配置文件中
- **配置热加载** — `ConfigWatcher` 轮询 `automation_file.toml`，变更时即时应用 sink / 默认值,无需重启
- **Shell / grep / JSON 编辑 / tar / 备份轮转** — `FA_run_shell`(参数列表式 subprocess,含超时)、`FA_grep`(流式文本搜索)、`FA_json_get` / `FA_json_set` / `FA_json_delete`(原地 JSON 编辑)、`FA_create_tar` / `FA_extract_tar`、`FA_rotate_backups`
- **FTP / FTPS 后端** — 纯 FTP 或通过 `FTP_TLS.auth()` 的显式 FTPS;自动注册为 `FA_ftp_*`
- **跨后端复制** — `FA_copy_between` 通过 `local://`、`s3://`、`azure://`、`dropbox://`、`sftp://`、`ftp://` URI 在任意两个后端之间搬运数据
- **调度器重叠防护** — 正在执行的作业在下次触发时会被跳过,除非显式传入 `allow_overlap=True`
- **服务器动作 ACL** — `allowed_actions=(...)` 限制 TCP / HTTP 服务器可派发的命令
- **变量替换** — 动作参数中可选使用 `${env:VAR}` / `${date:%Y-%m-%d}` / `${uuid}` / `${cwd}`,通过 `execute_action(..., substitute=True)` 展开
- **条件执行** — `FA_if_exists` / `FA_if_newer` / `FA_if_size_gt` 仅在路径守卫通过时执行嵌套动作清单
- **SQLite 审计日志** — `AuditLog(db_path)` 为每个动作记录 actor / status / duration;通过 `recent` / `count` / `purge` 查询
- **文件完整性监控** — `IntegrityMonitor` 为任何存储后端中的目录树保存带版本的基准，检测新增、修改、删除、重命名以及元数据或权限的变更，把偏移发布为事件，并且只在策略要求时才隔离或还原
- **HTTPActionClient SDK** — HTTP 动作服务器的类型化 Python 客户端,具 shared-secret 认证、loopback 守护与 OPTIONS ping
- **AES-256-GCM 文件加密** — `encrypt_file` / `decrypt_file` 搭配 `generate_key()` / `key_from_password()`(PBKDF2-HMAC-SHA256);JSON 动作 `FA_encrypt_file` / `FA_decrypt_file`
- **Prometheus metrics 导出器** — `start_metrics_server()` 提供 `automation_file_actions_total{action,status}` 计数器与 `automation_file_action_duration_seconds{action}` 直方图
- **WebDAV 后端** — `WebDAVClient` 提供 `exists` / `upload` / `download` / `delete` / `mkcol` / `list_dir`，适用于任何 RFC 4918 服务器；除非显式传入 `allow_private_hosts=True`，否则拒绝私有 / loopback 目标
- **SMB / CIFS 后端** — `SMBClient` 基于 `smbprotocol` 的高阶 `smbclient` API；采用 UNC 路径，默认启用加密会话
- **fsspec 桥接** — 通过 `get_fs` / `fsspec_upload` / `fsspec_download` / `fsspec_list_dir` 等函数，驱动任何 `fsspec` 支持的文件系统（memory、local、s3、gcs、abfs、…）
- **HTTP 服务器观测端点** — `GET /healthz` / `GET /readyz` 探针、`GET /openapi.json` 规格，以及 `GET /progress`（通过 WebSocket 推送实时传输快照）
- **HTMX Web UI** — `start_web_ui()` 启动只读观测仪表板（health、progress、registry），通过 HTML 片段轮询；仅用标准库 HTTP，搭配一个带 SRI 的 CDN 脚本
- **MCP（Model Context Protocol）服务器** — `MCPServer` 通过 stdio 上的 JSON-RPC 2.0（换行分隔 JSON）将注册表桥接到任意 MCP 主机（Claude Desktop、MCP CLI）；每个 `FA_*` 动作都会自动生成输入 schema 并成为 MCP 工具
- **通用存储层** — `File` / `Storage` 以同一套 URI 语法（`local:///…`、`s3://…`、`azure://…`、`gdrive://…`、`sftp://…`、…）、同一份 `StorageBackend` 契约与同一组异常层级访问本地与远端存储；内置十二种后端（本地、内存、S3、Azure Blob、Google Drive、Dropbox、OneDrive、SFTP、FTP / FTPS、WebDAV、SMB、fsspec），并附带 81 个用例的契约测试套件可检查任何后端
- **事件总线** — 单一 `Event` 模型与十种核心事件（`pipeline.*`、`task.*`、`integrity.violation`、`storage.error`、`scheduler.error`、`system.error`），具备严重程度、关联 ID 与 actor；可以在 `event_bus` 上按类、type 或前缀订阅
- **通知路由器** — 以路由决定哪些事件（按类型、来源与最低严重程度）发送到哪些 sink，每条路由各自去重与限流；可在代码、`automation_file.toml` 或通过 `FA_notify_route_*` 声明
- **审计轨迹** — `configure_audit(path)` 为每个事件与每次存储操作记录一条（actor、来源、pipeline、task、动作、资源、后端、状态、耗时、关联 ID），可用 `audit_search` / `FA_audit_search` 查询
- **流水线（Pipeline）** — `Pipeline` 按依赖顺序执行任务（可调用对象或 `FA_*` 动作），互不依赖者并行执行，并支持重试、超时、取消、条件、幂等键、检查点与续跑、试运行以及执行历史；定义可以用 Python、YAML 或 JSON 编写
- PySide6 GUI（`python -m automation_file ui`）每个后端一个页签，含 JSON 动作执行器，另有 Triggers、Scheduler、实时 Progress 专属页签
- 功能丰富的 CLI，包含一次性子命令与旧式 JSON 批量标志
- 项目脚手架（`ProjectBuilder`）协助构建以 executor 为核心的自动化项目

## 架构

```mermaid
flowchart TD
    CLI["<b>CLI / JSON 批次</b><br/>python -m automation_file"]
    GUIUser["<b>PySide6 GUI</b><br/>launch_ui"]
    ClientSDK["<b>HTTPActionClient SDK</b>"]
    MCPHost["<b>MCP 主机</b><br/>Claude Desktop · MCP CLIs"]
    Plugins["<b>入口点插件</b><br/>automation_file.actions"]

    subgraph Facade["<b>automation_file &mdash; 门面 (__init__.py)</b>"]
        PublicAPI["<b>Public API</b><br/>execute_action · execute_action_parallel · execute_action_dag<br/>validate_action · driver_instance · s3_instance · azure_blob_instance<br/>dropbox_instance · sftp_instance · ftp_instance · onedrive_instance · box_instance<br/>start_autocontrol_socket_server · start_http_action_server<br/>start_metrics_server · start_web_ui · MCPServer<br/>notification_manager · scheduler · trigger_manager<br/>AutomationConfig · progress_registry · Quota · retry_on_transient"]
    end

    subgraph Core["<b>core 核心</b>"]
        Registry[("<b>ActionRegistry</b><br/>FA_* 命令")]
        Executor["<b>ActionExecutor</b><br/>串行 · 并行 · dry-run · validate-first"]
        DAG["<b>dag_executor</b><br/>拓扑调度 fan-out"]
        Callback["<b>CallbackExecutor</b>"]
        Loader["<b>PackageLoader</b><br/>+ 入口点插件"]
        Queue["<b>ActionQueue</b>"]
        Json["<b>json_store</b>"]
        Sub["<b>substitution</b><br/>${env:} ${date:} ${uuid}"]
    end

    subgraph Reliability["<b>可靠性</b>"]
        Retry["<b>retry</b><br/>@retry_on_transient"]
        QuotaMod["<b>Quota</b><br/>字节 + 时间配额"]
        Breaker["<b>CircuitBreaker</b>"]
        RL["<b>RateLimiter</b>"]
        Locks["<b>FileLock</b> · <b>SQLiteLock</b>"]
    end

    subgraph Observability["<b>可观测性</b>"]
        Progress["<b>progress</b><br/>CancellationToken · Reporter"]
        Metrics["<b>metrics</b><br/>Prometheus counters + histograms"]
        Audit["<b>AuditLog</b><br/>SQLite 审计日志"]
        Tracing["<b>tracing</b><br/>OpenTelemetry spans"]
        FIM["<b>IntegrityMonitor</b>"]
    end

    subgraph Security["<b>安全 &amp; 配置</b>"]
        Secrets["<b>Secret providers</b><br/>Env · File · Chained"]
        Config["<b>AutomationConfig</b><br/>TOML 加载器"]
        ConfW["<b>ConfigWatcher</b><br/>热重载"]
        Crypto["<b>crypto</b><br/>AES-256-GCM"]
        Check["<b>checksum</b> / <b>manifest</b>"]
        SafeP["<b>safe_paths</b><br/>safe_join · is_within"]
        ACL["<b>ActionACL</b>"]
    end

    subgraph Events["<b>事件驱动</b>"]
        Trigger["<b>TriggerManager</b><br/>watchdog 文件监听"]
        Sched["<b>Scheduler</b><br/>5-field cron + overlap guard"]
    end

    subgraph Servers["<b>服务器</b>"]
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

    subgraph Local["<b>本地 ops</b>"]
        FileOps["<b>file_ops</b> · <b>dir_ops</b>"]
        Archives["<b>zip_ops</b> · <b>tar_ops</b> · <b>archive_ops</b>"]
        DataOps["<b>data_ops</b><br/>csv · jsonl · parquet · yaml"]
        TextOps["<b>text_ops</b> · <b>diff_ops</b><br/><b>json_edit</b> · <b>templates</b>"]
        Misc["<b>shell_ops</b> · <b>sync_ops</b> · <b>trash</b><br/><b>versioning</b> · <b>conditional</b> · <b>mime</b>"]
    end

    subgraph Remote["<b>远程后端</b>"]
        UrlVal["<b>url_validator</b><br/>SSRF 保护"]
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
        Cross["<b>cross_backend</b><br/>local:// s3:// azure://<br/>dropbox:// sftp:// ftp://"]
    end

    subgraph StorageLayer["<b>通用存储层</b>"]
        FileAPI["<b>File</b> · <b>Storage</b><br/>local:// s3:// azure:// gdrive:// sftp:// …"]
        Resolver["<b>StorageResolver</b><br/>mounts · scheme factories"]
        Backends["<b>StorageBackend</b> contract<br/>Local · Memory · S3 · Azure · Drive · Dropbox<br/>OneDrive · SFTP · FTP · WebDAV · SMB · fsspec"]
    end

    subgraph Notify["<b>通知</b>"]
        NM["<b>NotificationManager</b><br/>fanout · dedup · SSRF guard"]
        Sinks["<b>Sinks</b><br/>Webhook · Slack · Email<br/>Telegram · Discord · Teams · PagerDuty"]
    end

    subgraph Utils["<b>工具 / 项目</b>"]
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
    PublicAPI ==> FileAPI
    FileAPI ==> Resolver
    Resolver ==> Backends
    Backends ==> SafeP
    Backends ==> Check
    Backends ==> S3M
    Backends ==> Azure
    Backends ==> Drive
    Backends ==> Dropbox
    Backends ==> OneD
    Backends ==> SFTP
    Backends ==> FTP
    Backends ==> WebDAV
    Backends ==> SMB
    Backends ==> Fsspec

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
    Trigger -. 失败时 .-> NM
    Sched -. 失败时 .-> NM
    FIM -. 检测到变动 .-> NM
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
    classDef storage fill:#D4E6F1,stroke:#1A5276,stroke-width:3px,color:#000,font-weight:bold;

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
    class FileAPI,Resolver,Backends storage;

    linkStyle default stroke:#1F2A44,stroke-width:2.5px;
```

`build_default_registry()` 构建的 `ActionRegistry` 是所有 `FA_*` 命令的唯一
权威来源。`ActionExecutor`、`CallbackExecutor`、`PackageLoader`、
`TCPActionServer`、`HTTPActionServer` 都通过同一份共享 registry（以
`executor.registry` 对外公开）解析命令。

## 安装

```bash
pip install automation_file                 # 基础安装：不含云端 SDK，也不含 GUI 工具包
pip install "automation_file[s3,sftp]"      # 加上你会用到的后端
pip install "automation_file[all]"          # 所有后端与 GUI
```

基础安装即可运行 JSON 动作、本地文件操作、HTTP 下载、存储层的本地与内存后端、pipeline、
事件、触发器、调度器与各种服务器。各后端的 SDK 与 GUI 工具包都放在 extra 中，只有在用到该
功能时才会导入。调用缺少 extra 的功能时，会抛出 `OptionalDependencyException`，信息中附有
要执行的安装命令。

| Extra | 安装的包 | 提供的功能 |
|---|---|---|
| `s3` | `boto3` | S3（`FA_s3_*`、`s3://`） |
| `azure` | `azure-storage-blob` | Azure Blob（`FA_azure_blob_*`、`azure://`） |
| `gdrive` | `google-api-python-client`、`google-auth-httplib2`、`google-auth-oauthlib` | Google Drive（`FA_drive_*`） |
| `dropbox` | `dropbox` | Dropbox（`FA_dropbox_*`） |
| `sftp` | `paramiko` | SFTP（`FA_sftp_*`） |
| `ftp` | — | FTP / FTPS（`FA_ftp_*`）；只需要标准库 |
| `webdav` | — | WebDAV（`WebDAVClient`）；基础依赖已足够 |
| `smb` | `smbprotocol` | SMB / CIFS（`SMBClient`） |
| `fsspec` | `fsspec` | fsspec 桥接 |
| `onedrive` | `msal` | OneDrive（`FA_onedrive_*`） |
| `box` | `boxsdk` | Box（`FA_box_*`） |
| `parquet` | `pyarrow` | Parquet 数据操作（`FA_parquet_*`、`FA_csv_to_parquet`） |
| `gui` | `PySide6` | 桌面 GUI（`python -m automation_file ui`） |
| `all` | 以上全部 | 所有后端与 GUI，与拆分之前相同 |

```bash
pip install "automation_file[all,dev]"   # 另含 ruff、mypy、pre-commit、pytest-cov、build、twine
```

从先前包含所有包的版本升级时：安装 `automation_file[all]` 即可保留原有的全部功能。

要求：
- Python 3.10+
- 基础依赖：`requests`、`tqdm`、`watchdog`、`cryptography`、`prometheus_client`、`defusedxml`、
  `PyYAML`、`opentelemetry-api`、`opentelemetry-sdk`、`je_action_core`（与 APITestka、
  LoadDensity、MailThunder 共用的 action 执行器）

## 使用方式

### 执行 JSON 动作清单
```python
from automation_file import execute_action

execute_action([
    ["FA_create_file", {"file_path": "test.txt"}],
    ["FA_copy_file", {"source": "test.txt", "target": "copy.txt"}],
])
```

### 验证、干跑、并行
```python
from automation_file import execute_action, execute_action_parallel, validate_action

# Fail-fast：只要有任何命令名称未知就在执行前中止。
execute_action(actions, validate_first=True)

# Dry-run：只记录会被调用的内容，不真的执行。
execute_action(actions, dry_run=True)

# Parallel：通过 thread pool 并行执行独立动作。
execute_action_parallel(actions, max_workers=4)

# 手动验证 — 返回解析后的名称列表。
names = validate_action(actions)
```

### 初始化 Google Drive 并上传
```python
from automation_file import driver_instance, drive_upload_to_drive

driver_instance.later_init("token.json", "credentials.json")
drive_upload_to_drive("example.txt")
```

### 经验证的 HTTP 下载（含重试）
```python
from automation_file import download_file

download_file("https://example.com/file.zip", "file.zip")
```

### 启动 loopback TCP 服务器（可选 shared-secret 验证）
```python
from automation_file import start_autocontrol_socket_server

server = start_autocontrol_socket_server(
    host="127.0.0.1", port=9943, shared_secret="optional-secret",
)
```

设定 `shared_secret` 时，客户端每个包都必须以 `AUTH <secret>\n` 为前缀。
若要绑定非 loopback 地址必须明确传入 `allow_non_loopback=True`。

### 启动 HTTP 动作服务器
```python
from automation_file import start_http_action_server

server = start_http_action_server(
    host="127.0.0.1", port=9944, shared_secret="optional-secret",
)

# curl -H 'Authorization: Bearer optional-secret' \
#      -d '[["FA_create_dir",{"dir_path":"x"}]]' \
#      http://127.0.0.1:9944/actions
```

### Retry 与 quota 原语
```python
from automation_file import retry_on_transient, Quota

@retry_on_transient(max_attempts=5, backoff_base=0.5)
def flaky_network_call(): ...

quota = Quota(max_bytes=50 * 1024 * 1024, max_seconds=30.0)
with quota.time_budget("bulk-upload"):
    bulk_upload_work()
```

### 路径穿越防护
```python
from automation_file import safe_join

target = safe_join("/data/jobs", user_supplied_path)
# 若解析后的路径逃出 /data/jobs 会抛出 PathTraversalException。
```

### Cloud / SFTP 后端
每个后端都会由 `build_default_registry()` 自动注册，因此 `FA_s3_*`、
`FA_azure_blob_*`、`FA_dropbox_*`、`FA_sftp_*` 动作开箱即用 — 不需要另外调用
`register_*_ops`。

```python
from automation_file import execute_action, s3_instance

s3_instance.later_init(region_name="us-east-1")

execute_action([
    ["FA_s3_upload_file", {"local_path": "report.csv", "bucket": "reports", "key": "report.csv"}],
])
```

所有后端（`s3`、`azure_blob`、`dropbox_api`、`sftp`）都提供相同的五组操作：
`upload_file`、`upload_dir`、`download_file`、`delete_*`、`list_*`。
SFTP 使用 `paramiko.RejectPolicy` — 未知主机会被拒绝，不会自动加入。

### 通用存储层（File / Storage）
每一种存储都使用同一套 URI 语法、同一组操作和同一组异常。`File` 代表单个文件，
`Storage` 代表目录，`StorageBackend` 则是后端需要实现的契约。`FA_*` 动作以及各后端原有的
函数完全不变，可以与本层同时使用。

```python
from automation_file import File, LocalStorage, Storage

report = File("local:///data/reports/q1.csv")      # 也可以直接写普通路径
report.write("region,total\nEMEA,42\n")
report.size, report.modified_at, report.content_type
report.checksum()                                   # Checksum("sha256", "…")
report.copy_to("memory://scratch/archive/q1.csv")   # 任何后端到任何后端
report.move_to("local:///data/done/q1.csv")

reports = Storage("local:///data/reports")
for info in reports.list_dir(recursive=True):
    print(info.path, info.size)

# 限制不受信任的路径：sandbox://jobs/ 之下的任何东西都离不开 /srv/jobs。
Storage.mount("sandbox://jobs", LocalStorage("/srv/jobs"))
File("sandbox://jobs/42/out.csv").write(b"done")
```

- **URI** — `<scheme>://<authority>/<path>`：`local:///data/a.csv`、`s3://bucket/a.csv`、
  `sftp://server/data/a.csv`。路径按字面理解（不做百分号解码），`..` 段会被拒绝，
  authority 中的凭据也会被拒绝。不含 `://` 的文本视为本地路径。
- **操作** — `exists`、`stat`、`list_dir`、`mkdir`、`upload`、`download`、`delete`、
  `checksum`、`read_bytes`、`write_bytes`、`copy_from`、`move_from`，在每个后端上都相同。
  下载与本地写入均为原子操作，删除内有条目的目录需要 `recursive=True`，存储的根目录
  永远不会被删除。
- **流与目录树** — `File.open_read()` / `open_write()` / `iter_chunks()` 用于大到放不进内存的
  内容；`Storage.copy_to(target)` 把整个目录树复制到任何后端，
  `Storage.sync_to(target, delete=False, checksum=False, dry_run=False)` 只复制有变动的部分。
- **异常** — `StorageException` 及其子类：`StorageNotFoundException`、
  `StorageAlreadyExistsException`、`StoragePathTypeException`、`StorageNotEmptyException`、
  `StoragePermissionException`、`StorageTransientException`、`StorageUnavailableException`、
  `StorageUnsupportedException`、`StorageURIException`。
- **后端** — 内置十二种。可以直接用 URI 访问、并使用你原本就会初始化的共用客户端的有：`local://`、
  `memory://`、`s3://bucket/key`、`azure://container/blob`、`gdrive://<root>/path`、`dropbox:///path`、
  `onedrive:///path`、`sftp://host/path`、`ftp://host/path` 与 `ftps://host/path`。需要自己的客户端或
  文件系统、因此以挂载方式使用的有：`WebDAVStorage`、`SMBStorage` 与 `FsspecStorage`
  （`Storage.mount("webdav://files.example.com", WebDAVStorage(client))`）。每个远端后端都需要对应的
  extra（`pip install "automation_file[sftp]"`）。`sftp://` 或 `ftp://` URI 必须写出会话实际连接
  的主机，打错字就不会写到另一台服务器。Box 没有适配器，仍使用它的 `FA_box_*` 动作。你可以继承
  `StorageBackend`（对象存储继承 `ObjectStorage`，登录会话继承 `SessionStorage`）编写自己的后端，
  并用 `tests/storage_contract.py` 中 81 个用例的契约测试套件检查。

- **动作** — `FA_storage_exists`, `FA_storage_stat`, `FA_storage_list`, `FA_storage_mkdir`,
  `FA_storage_upload`, `FA_storage_download`, `FA_storage_delete`, `FA_storage_checksum`,
  `FA_storage_verify`, `FA_storage_copy`, `FA_storage_move`, `FA_storage_read_text`,
  `FA_storage_write_text`, `FA_storage_copy_tree`, `FA_storage_sync`, `FA_storage_schemes`。它们以字符串
  形式接收 URI，并返回可以序列化为 JSON 的值，因此本层可用于动作文件、CLI、TCP 与 HTTP 服务器，
  也能作为 MCP 工具。在服务器上请像其他文件动作一样用 `ActionACL` 加以限制。

```json
[
  ["FA_storage_copy", {"source": "s3://reports/q1.csv", "target": "local:///backup/q1.csv"}],
  ["FA_storage_verify", {"uri": "local:///backup/q1.csv", "expected": "sha256:9f86d081884c7d65…"}],
  ["FA_storage_list", {"uri": "s3://reports", "recursive": true}]
]
```

此 API 为新功能，在 1.0 之前仍可能调整。完整说明请见文档的“通用存储层”章节。

### 事件
每个组件都通过同一套事件模型报告，而不是自行调用通知接收端或审计记录。

```python
from automation_file import Severity, actor_scope, correlation_scope, event_bus

event_bus.subscribe(print, types=["pipeline.*", "integrity.violation"])
event_bus.subscribe(alert, min_severity=Severity.ERROR)

with actor_scope("scheduler"), correlation_scope() as run_id:
    ...   # 这里面的每个事件与存储操作都带有 run_id 与 actor
event_bus.recent(limit=20, correlation_id=run_id)
```

- **核心事件** — `PipelineStarted`、`PipelineCompleted`、`PipelineFailed`、`TaskStarted`、
  `TaskCompleted`、`TaskFailed`、`IntegrityViolation`、`StorageError`、`SchedulerError`、
  `SystemErrorEvent`。每个事件都有 `type`（`pipeline.failed`）、`severity`、`source`、`subject`、
  结构化的 `payload`、`correlation_id` 与 `actor`，并可以用 `to_dict()` 转成 JSON。
- **总线** — `event_bus.subscribe(handler, types=..., min_severity=...)` 可以按类、type 名称或
  前缀订阅；处理函数抛出异常时只会被记录并跳过；`event_bus.recent()` 返回最近的事件。
- **存储操作** — 上传、下载、读取、删除、复制与移动都会报告给
  `automation_file.storage.observe` 的监听者，后端失败时会产生 `StorageError` 事件。

### 通知路由器
通知改由事件驱动：模块发布事件，再由路由决定哪些 sink 会收到。

```python
from automation_file import Route, Severity, notification_router

notification_router.add_route(Route(
    "pipeline-failures",
    sinks=("team-alerts",),                  # 留空 = 所有已注册的 sink
    types=("pipeline.*", "task.failed"),     # 事件类、type 名称或前缀
    min_severity=Severity.ERROR,
    dedup_seconds=600, rate_limit=10, rate_period=60,
))
notification_router.start()                  # 在事件总线上订阅
```

- **路由** — 按事件 type、来源与最低严重程度，送往指定名称的 sink。可以在代码中声明、
  在 `automation_file.toml` 以 `[[notify.routes]]` 表声明（与 sink 一起热重载），或使用
  `FA_notify_route_add` / `FA_notify_route_remove` / `FA_notify_route_list`。
- **去重与速率限制** — 以每条路由、每个 sink 为单位：type、来源与主题都相同的事件在
  `dedup_seconds` 内重复出现时会被丢弃，每个 `rate_period` 内最多送出 `rate_limit` 条消息。
- **结构化消息** — 主题与正文由事件组成：严重程度、来源、关联 ID、actor 以及
  `event.to_dict()` 的 JSON。`critical` 会以 sink 的 `error` 级别发送。
- **失败隔离** — 单个 sink 失败绝对不会影响其他 sink。失败会以来源为 `notify` 的
  `system.error` 事件发布，而路由器绝对不会路由这类事件，因此故障的 sink 不会形成循环。
- **`notify_on_failure`** — 总是会发布事件。路由器工作时由路由投递；否则照旧直接发送通知，
  因此不会有人收到两次，也不会有人收不到。

### 审计轨迹（schema v2）
审计轨迹记录谁在什么时候做了什么、对象是哪个资源、使用哪个后端以及结果如何：每个事件与
每次存储操作各一条记录。

```python
from automation_file import audit_search, configure_audit, correlation_scope

configure_audit("audit.sqlite")              # SQLite 存储库；开始记录

with correlation_scope() as run_id:
    ...                                      # 事件与存储操作都会被记录
audit_search(correlation_id=run_id)          # 整次运行，最新的在前
audit_search(status="error", resource_prefix="s3://reports/", limit=20)
```

- **记录** — `id`、`timestamp`（UTC）、`actor`、`source`、`pipeline`、`task`、`action`、
  `resource`、`backend`、`status`、`duration_ms`、`error`、`metadata`、`correlation_id`。
- **搜索** — 可以按 `since` / `until`、`actor`、`source`、`pipeline`、`task`、`action`、
  `resource_prefix`、`backend`、`status`、`correlation_id` 与自由文本 `text` 筛选；最新的
  在前，并支持 `limit` / `offset`。
- **存储库** — `SQLiteAuditStore`（参数化 SQL、模式版本表、WAL）与测试用的
  `MemoryAuditStore`；`AuditStore` 是 PostgreSQL 或远程存储库要实现的接口。
  `SQLiteAuditStore.import_v1()` 可以复制 v1 `AuditLog` 的行。
- **绝不碍事** — 无法写入的记录只会被记录到日志并丢弃，绝对不会抛进被审计的代码。失败的
  存储操作只记录一次，不会重复。
- **动作与指标** — `FA_audit_configure` / `FA_audit_search` / `FA_audit_count` /
  `FA_audit_purge`；`install_operational_metrics()` 会加入事件、通知与存储操作的
  Prometheus 计数器。

### 流水线（Pipeline）

`automation_file.pipeline` 按依赖顺序执行任务，互不依赖的任务并行执行，并记录每一个
步骤。任务可以是 Python 可调用对象或 `FA_*` 动作；流水线可以用 Python 构建，也可以从
YAML / JSON 定义载入。一次运行只通过事件总线上的 `pipeline.*` 与 `task.*` 事件报告。

```python
from automation_file import Pipeline, RetryPolicy, SQLiteRunStore

def check(ctx):
    if ctx.results["download"]["size"] == 0:
        raise ValueError("the report is empty")

pipeline = Pipeline("daily-report", max_workers=4)
pipeline.task(
    "download",
    ["FA_storage_copy", {"source": "s3://input/${params.date}.csv",
                         "target": "local:///tmp/report.csv"}],
    retry=RetryPolicy(max_attempts=3, backoff_base=1.0, backoff_cap=30.0),
    timeout=300.0,
)
pipeline.task("check", check, depends_on=["download"])
pipeline.task(
    "publish",
    ["FA_storage_copy", {"source": "local:///tmp/report.csv",
                         "target": "azure://reports/${params.date}.csv"}],
    depends_on=["check"],
    idempotency_key="publish-${params.date}",        # 同一个日期最多一次
)
pipeline.task(
    "withdraw",                                      # publish 失败时清理
    ["FA_storage_delete", {"uri": "azure://reports/${params.date}.csv",
                           "missing_ok": True}],
    depends_on=["publish"],
    when="on_failure",
)

store = SQLiteRunStore("pipelines.db")
run = pipeline.run(params={"date": "2026-10-08"}, store=store)
if run.status != "succeeded":
    run = pipeline.resume(run.run_id, store=store)   # 保留已成功的部分
```

- **重试、超时、取消。** `RetryPolicy` 以有上限的指数退避重试暂时性错误；超过
  `timeout` 的任务会被标记为 `timeout`，运行则继续进行；`pipeline.start()` 在后台
  运行，`run.cancel()` 可以停止它。
- **条件与幂等。** `when` 可以是 `on_success`、`on_failure`、`always` 或可调用对象；
  `idempotency_key` 会跳过已经以相同的键成功过的任务，并沿用它的结果。
- **检查点、续跑、历史。** 任务的每一次状态转换都会写入 `RunStore`
  （`MemoryRunStore`、`SQLiteRunStore`）；`resume(run_id)` 只执行尚未成功的部分，
  `store.list_runs()` 就是运行历史。
- **定义文件。** `Pipeline.from_file("daily-report.yaml")`、`from_dict` / `to_dict`、
  会报告每一项问题路径的 `validate_definition()`，以及 `PIPELINE_SCHEMA`
  （JSON Schema）。`run(dry_run=True)` 只规划而不执行。
- **动作。** `FA_pipeline_run`、`FA_pipeline_validate`、`FA_pipeline_status`、
  `FA_pipeline_history` 与 `FA_pipeline_resume`，可用于 JSON 动作列表、CLI、动作
  服务器与 MCP。

### 文件监听触发
每当被监听路径发生文件系统事件，就执行动作清单：

```python
from automation_file import watch_start, watch_stop

watch_start(
    name="inbox-sweeper",
    path="/data/inbox",
    action_list=[["FA_copy_all_file_to_dir", {"source_dir": "/data/inbox",
                                              "target_dir": "/data/processed"}]],
    events=["created", "modified"],
    recursive=False,
)
# 稍后：
watch_stop("inbox-sweeper")
```

`FA_watch_start` / `FA_watch_stop` / `FA_watch_stop_all` / `FA_watch_list`
让 JSON 动作清单能使用相同的生命周期。

### Cron 调度器
以纯标准库的 5 字段 cron 解析器执行周期性动作清单：

```python
from automation_file import schedule_add

schedule_add(
    name="nightly-snapshot",
    cron_expression="0 2 * * *",        # 每天本地时间 02:00
    action_list=[["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                                 "zip_name": "/backup/data_nightly"}]],
)
```

支持 `*`、确切值、`a-b` 范围、逗号列表、`*/n` 步进语法，以及 `jan..dec` /
`sun..sat` 别名。JSON 动作：`FA_schedule_add`、`FA_schedule_remove`、
`FA_schedule_remove_all`、`FA_schedule_list`。

### 传输进度 + 取消
HTTP 与 S3 传输支持可选的 `progress_name` 关键字参数：

```python
from automation_file import download_file, progress_cancel

download_file("https://example.com/big.bin", "big.bin",
              progress_name="big-download")

# 从另一个线程或 GUI：
progress_cancel("big-download")
```

共享的 `progress_registry` 通过 `progress_list()` 以及 `FA_progress_list` /
`FA_progress_cancel` / `FA_progress_clear` JSON 动作提供实时快照。GUI 的
**Progress** 页签每半秒轮询一次 registry。

### 快速文件搜索
若 OS 索引器可用就直接查询（macOS 的 `mdfind`、Linux 的 `locate` /
`plocate`、Windows 的 Everything `es.exe`），否则回退到以流式 `os.scandir`
遍历。不需要额外依赖。

```python
from automation_file import fast_find, scandir_find, has_os_index

# 可用时使用 OS 索引器，否则回退到 scandir。
results = fast_find("/var/log", "*.log", limit=100)

# 强制使用可移植路径（跳过 OS 索引器）。
results = fast_find("/data", "report_*.csv", use_index=False)

# 流式 — 不需要遍历整棵树就能提前停止。
for path in scandir_find("/data", "*.csv"):
    if "2026" in path:
        break
```

`FA_fast_find` 将同一个函数提供给 JSON 动作清单：

```json
[["FA_fast_find", {"root": "/var/log", "pattern": "*.log", "limit": 50}]]
```

### 校验和 + 完整性验证
流式处理任何 `hashlib` 算法；`verify_checksum` 使用 `hmac.compare_digest`
（常数时间）比较摘要：

```python
from automation_file import file_checksum, verify_checksum

digest = file_checksum("bundle.tar.gz")                # 默认为 sha256
verify_checksum("bundle.tar.gz", digest)               # -> True
verify_checksum("bundle.tar.gz", "deadbeef...", algorithm="blake2b")
```

同时以 `FA_file_checksum` / `FA_verify_checksum` 提供 JSON 动作。

### 可续传 HTTP 下载
`download_file(resume=True)` 会写入 `<target>.part` 并在下次尝试时发送
`Range: bytes=<n>-`。配合 `expected_sha256=` 可在下载完成后立即验证完整性：

```python
from automation_file import download_file

download_file(
    "https://example.com/big.bin",
    "big.bin",
    resume=True,
    expected_sha256="3b0c44298fc1...",
)
```

### 重复文件查找器
三阶段管线：按大小分桶 → 64 KiB 部分哈希 → 完整哈希。大小唯一的文件完全不会
被哈希：

```python
from automation_file import find_duplicates

groups = find_duplicates("/data", min_size=1024)
# list[list[str]] — 每个内层 list 是一组相同内容的文件，按大小降序排序。
```

`FA_find_duplicates` 以相同调用提供给 JSON。

### 增量目录同步
`sync_dir` 以只复制新增或变更文件的方式将 `src` 镜像到 `dst`。变更检测默认
为 `(size, mtime)`；当 mtime 不可靠时可传入 `compare="checksum"`。`dst`
下多余的文件默认保留 — 传入 `delete=True` 才会清理（`dry_run=True` 可先
预览）：

```python
from automation_file import sync_dir

summary = sync_dir("/data/src", "/data/dst", delete=True)
# summary: {"copied": [...], "skipped": [...], "deleted": [...],
#           "errors": [...], "dry_run": False}
```

Symlink 会以 symlink 形式重建而非被跟随，因此指向树外的链接不会拖垮镜像。
JSON 动作：`FA_sync_dir`。

### 目录 manifest
将树下每个文件的校验和写入 JSON manifest，之后再验证树是否变动：

```python
from automation_file import write_manifest, verify_manifest

write_manifest("/release/payload", "/release/MANIFEST.json")

# 稍后…
result = verify_manifest("/release/payload", "/release/MANIFEST.json")
if not result["ok"]:
    raise SystemExit(f"manifest mismatch: {result}")
```

`result` 以 `matched`、`missing`、`modified`、`extra` 分别报告列表。
多余文件（`extra`）不会让验证失败（对齐 `sync_dir` 默认不删除的行为），
`missing` 与 `modified` 则会。JSON 动作：`FA_write_manifest`、
`FA_verify_manifest`。

### 通知
通过 webhook、Slack 或 SMTP 推送一次性消息，或在 trigger / scheduler
失败时自动通知：

```python
from automation_file import (
    SlackSink, WebhookSink, EmailSink,
    notification_manager, notify_send,
)

notification_manager.register(SlackSink("https://hooks.slack.com/services/T/B/X"))
notify_send("deploy complete", body="rev abc123", level="info")
```

每个 sink 都遵循相同的 `send(subject, body, level)` 合约。Fanout 的
`NotificationManager` 会做单 sink 错误隔离（一个坏掉的 sink 不会影响
其他 sink）、滑动窗口去重（避免卡住的 trigger 刷屏），并对每个
webhook / Slack URL 进行 SSRF 验证。Scheduler 与 trigger 派发器在失败时
会以 `level="error"` 自动通知 — 只要注册 sink 就能拿到生产环境告警。
JSON 动作：`FA_notify_send`、`FA_notify_list`。

### 配置文件与密钥提供者
在 `automation_file.toml` 一次声明 sink 与默认值。密钥引用在加载时由
环境变量或文件根目录（Docker / K8s 风格）解析：

```toml
# automation_file.toml

[secrets]
file_root = "/run/secrets"

[defaults]
dedup_seconds = 120

[[notify.sinks]]
type = "slack"
name = "team-alerts"
webhook_url = "${env:SLACK_WEBHOOK}"

[[notify.sinks]]
type = "email"
name = "ops-email"
host = "smtp.example.com"
port = 587
sender = "alerts@example.com"
recipients = ["ops@example.com"]
username = "${env:SMTP_USER}"
password = "${file:smtp_password}"
```

```python
from automation_file import AutomationConfig, notification_manager, notification_router

config = AutomationConfig.load("automation_file.toml")
config.apply_to(notification_manager, notification_router)   # sinks, and [[notify.routes]]
```

未解析的 `${…}` 引用会抛出 `SecretNotFoundException`，而不是默默变成空
字符串。可组合 `ChainedSecretProvider` / `EnvSecretProvider` /
`FileSecretProvider` 构建自定义提供者链，并以
`AutomationConfig.load(path, provider=…)` 传入。

### 动作清单变量替换
以 `substitute=True` 启用后,`${…}` 引用会在派发时展开:

```python
from automation_file import execute_action

execute_action(
    [["FA_create_file", {"file_path": "reports/${date:%Y-%m-%d}/${uuid}.txt"}]],
    substitute=True,
)
```

支持 `${env:VAR}`、`${date:FMT}`(strftime)、`${uuid}`、`${cwd}`。未知名称
会抛出 `SubstitutionException`,不会默默变成空字符串。

### 条件执行
只在路径守卫通过时执行嵌套动作清单:

```json
[
  ["FA_if_exists", {"path": "/data/in/job.json",
                    "then": [["FA_copy_file", {"source": "/data/in/job.json",
                                               "target": "/data/processed/job.json"}]]}],
  ["FA_if_newer",  {"source": "/src", "target": "/dst",
                    "then": [["FA_sync_dir", {"src": "/src", "dst": "/dst"}]]}],
  ["FA_if_size_gt", {"path": "/logs/app.log", "size": 10485760,
                     "then": [["FA_run_shell", {"command": ["logrotate", "/logs/app.log"]}]]}]
]
```

### SQLite 审计日志
`AuditLog` 以短连接 + 模块级锁为每个动作写入一条记录:

```python
from automation_file import AuditLog

audit = AuditLog("audit.sqlite3")
audit.record(action="FA_copy_file", actor="ops",
             status="ok", duration_ms=12, detail={"src": "a", "dst": "b"})

for row in audit.recent(limit=50):
    print(row["timestamp"], row["action"], row["status"])
```

### 文件完整性监控
`IntegrityMonitor` 检查任何存储后端中的目录树是否仍然是当初批准的样子：它存储基线、拿目录树与
基线比较，并把每一次偏移以事件的形式发布。

```python
from automation_file import IntegrityMonitor

monitor = IntegrityMonitor("s3://reports/2026",
                           baseline="local:///var/lib/fa/reports-2026.json")
monitor.create_baseline()        # 批准当前的内容
report = monitor.verify()        # 对每个文件计算哈希；verify(deep=False) 是快速验证
if not report.ok:
    print(report.counts)         # {'created': 0, 'modified': 1, 'deleted': 0, ...}
    monitor.accept(report)       # 审查之后：批准这份报告所看到的状态
monitor.start()                  # 持续模式：每隔 `interval` 秒验证一次
handle = monitor.watch()         # 或在变更发生时即时响应；handle.stop() 结束监视
```

- **四种模式** — `snapshot()`、`verify()`、`watch()`（本地目标使用文件系统事件，其他后端使用
  轮询）以及持续模式的 `start()` / `stop()`。
- **六种变更** — `created`、`modified`、`deleted`、`renamed`、`metadata_changed` 与
  `permission_changed`，汇总在带有各种类数量与 `to_dict()` 的 `DriftReport` 中。
- **基线可放在任何地方** — 位于任意存储 URI、带有版本的 JSON manifest，以原子方式写入；仍可读取
  `write_manifest` 的格式。默认使用 SHA-256，可改用 `sha512` 与 `blake2b`，`md5` 与 `sha1` 只有在
  `allow_weak=True` 时才能使用。
- **事件与需显式开启的补救** — 每一次发现偏移的验证发布一个 `IntegrityViolation`（有东西被修改
  或删除时为 `error`，新增与元数据变更为 `warning`）。除非以 `RemediationPolicy` 要求隔离，
  或要求从镜像还原（会以校验码验证），否则监控器只会读取。
- **动作** — `FA_integrity_snapshot`、`FA_integrity_baseline`、`FA_integrity_verify`、
  `FA_integrity_accept`、`FA_integrity_watch_start`、`FA_integrity_watch_stop`、
  `FA_integrity_status`。

为第一代监控器写的代码照常工作：`IntegrityMonitor(root=..., manifest_path=..., interval=...,
manager=..., on_drift=...)` 会读取 `write_manifest` 写出的 manifest，`check_once()` 返回同样的摘要，
通知也仍然通过 `manager` 发送，没有传入时则使用整个进程共用的 `notification_manager`。通知路由器
启用期间改由路由送达 `IntegrityViolation` 事件，不再另外直接通知，同一次偏移不会被通知两次；
`notify=False` 会完全关闭这项直接通知。

### AES-256-GCM 文件加密
带认证的加密与自描述封包格式。可由密码派生密钥或直接生成密钥:

```python
from automation_file import encrypt_file, decrypt_file, key_from_password

key = key_from_password("correct horse battery staple", salt=b"app-salt-v1")
encrypt_file("secret.pdf", "secret.pdf.enc", key, associated_data=b"v1")
decrypt_file("secret.pdf.enc", "secret.pdf", key, associated_data=b"v1")
```

篡改由 GCM 认证 tag 检测,以 `CryptoException("authentication failed")`
报告。JSON 动作:`FA_encrypt_file`、`FA_decrypt_file`。

### HTTPActionClient Python SDK
HTTP 动作服务器的类型化客户端;默认强制 loopback,并自动携带 shared
secret:

```python
from automation_file import HTTPActionClient

with HTTPActionClient("http://127.0.0.1:9944", shared_secret="s3cr3t") as client:
    client.ping()                                       # OPTIONS /actions
    result = client.execute([["FA_create_dir", {"dir_path": "x"}]])
```

认证失败会转换为 `HTTPActionClientException(kind="unauthorized")`;
404 则表示服务器存在但未对外提供 `/actions`。

### Prometheus metrics 导出器
`ActionExecutor` 为每个动作记录一条计数器与一条直方图样本。在 loopback
`/metrics` 端点提供:

```python
from automation_file import start_metrics_server

server = start_metrics_server(host="127.0.0.1", port=9945)
# curl http://127.0.0.1:9945/metrics
```

导出 `automation_file_actions_total{action,status}` 以及
`automation_file_action_duration_seconds{action}`。若要绑定非 loopback
地址必须显式传入 `allow_non_loopback=True`。

### WebDAV、SMB/CIFS、fsspec
在一等公民的 S3 / Azure / Dropbox / SFTP 之外，额外的远程后端：

```python
from automation_file import WebDAVClient, SMBClient, fsspec_upload

# RFC 4918 WebDAV —— loopback / 私有目标需要显式开关。
dav = WebDAVClient("https://files.example.com/remote.php/dav",
                   username="alice", password="s3cr3t")
dav.upload("/local/report.csv", "team/reports/report.csv")

# 通过 smbprotocol 的高阶 smbclient API 操作 SMB / CIFS。
with SMBClient("fileserver", "share", "alice", "s3cr3t") as smb:
    smb.upload("/local/report.csv", "reports/report.csv")

# 任何 fsspec 能寻址的目标 —— memory、gcs、abfs、local、…
fsspec_upload("/local/report.csv", "memory://reports/report.csv")
```

### HTTP 服务器观测端点
`start_http_action_server()` 额外提供 liveness / readiness 探针、OpenAPI 3.0
规格，以及实时进度快照的 WebSocket 流：

```bash
curl http://127.0.0.1:9944/healthz          # {"status": "ok"}
curl http://127.0.0.1:9944/readyz           # 注册表非空时 200，否则 503
curl http://127.0.0.1:9944/openapi.json     # OpenAPI 3.0 规格
# 使用 WebSocket 连接 ws://127.0.0.1:9944/progress 获取实时进度帧。
```

### HTMX Web UI
基于标准库 HTTP + HTMX（以带 SRI 的固定 CDN URL 加载）构建的只读观测仪表板。
默认仅允许 loopback，可选 shared-secret：

```python
from automation_file import start_web_ui

server = start_web_ui(host="127.0.0.1", port=9955, shared_secret="s3cr3t")
# 浏览 http://127.0.0.1:9955/ —— health、progress、registry 片段每几秒
# 自动轮询一次；写入操作仍然保留在动作服务器。
```

### MCP（Model Context Protocol）服务器
通过 stdio 上的 JSON-RPC 2.0 把每个已注册的 `FA_*` 动作暴露给 MCP 主机
（Claude Desktop、MCP CLI）：

```python
from automation_file import MCPServer

MCPServer().serve_stdio()          # 从 stdin 读取 JSON-RPC，写入 stdout
```

`pip install` 后，`[project.scripts]` 会提供 `automation_file_mcp` console
script，MCP 主机无需编写 Python glue 即可启动桥接器。三种等价的启动方式：

```bash
automation_file_mcp                                      # 已安装的 console script
python -m automation_file mcp                            # CLI 子命令
python examples/mcp/run_mcp.py                           # 独立启动脚本
```

三者都支持 `--name`、`--version`、`--allowed-actions`（逗号分隔白名单——
强烈建议使用，因为默认注册表包含 `FA_run_shell` 等高权限动作）。可直接复制的
Claude Desktop 示例配置请见 [`examples/mcp/`](examples/mcp)。

工具描述符在运行时由动作签名自动生成——参数名称与类型会转换为 JSON schema，
主机无需任何手动配置即可渲染字段。

### DAG 动作执行器
按依赖顺序执行动作；独立分支通过线程池并行展开。每个节点的形式为
`{"id": ..., "action": [...], "depends_on": [...]}`：

```python
from automation_file import execute_action_dag

execute_action_dag([
    {"id": "fetch",  "action": ["FA_download_file",
                                ["https://example.com/src.tar.gz", "src.tar.gz"]]},
    {"id": "verify", "action": ["FA_verify_checksum",
                                ["src.tar.gz", "3b0c44298fc1..."]],
                     "depends_on": ["fetch"]},
    {"id": "unpack", "action": ["FA_unzip_file", ["src.tar.gz", "src"]],
                     "depends_on": ["verify"]},
])
```

若 `verify` 抛出异常，默认情况下 `unpack` 会被标记为 `skipped`。传入
`fail_fast=False` 可让后代节点仍然执行。JSON 动作：`FA_execute_action_dag`。

### Entry-point 插件
第三方包通过 `pyproject.toml` 声明动作：

```toml
[project.entry-points."automation_file.actions"]
my_plugin = "my_plugin:register"
```

其中 `register` 是一个零参数的可调用对象，返回 `dict[str, Callable]`。只要
包被安装在同一个虚拟环境，这些命令就会出现在每次新建的 registry 中：

```python
# my_plugin/__init__.py
def greet(name: str) -> str:
    return f"hello {name}"

def register() -> dict:
    return {"FA_greet": greet}
```

```python
# 执行 `pip install my_plugin` 之后
from automation_file import execute_action
execute_action([["FA_greet", {"name": "world"}]])
```

插件失败（导入错误、factory 异常、返回类型不正确、registry 拒绝）都会被记录
并吞掉 — 一个坏掉的插件不会影响整个库。

### GUI
```bash
python -m automation_file ui        # 或：python main_ui.py
```

```python
from automation_file import launch_ui
launch_ui()
```

页签：Home、Local、Transfer、Progress、JSON actions、Triggers、Scheduler、
Servers。底部常驻的 log 面板实时流式输出每一笔结果与错误。

### 以 executor 为核心构建项目脚手架
```python
from automation_file import create_project_dir

create_project_dir("my_workflow")
```

## CLI

```bash
# 子命令（一次性操作）
python -m automation_file ui
python -m automation_file zip ./src out.zip --dir
python -m automation_file unzip out.zip ./restored
python -m automation_file download https://example.com/file.bin file.bin
python -m automation_file create-file hello.txt --content "hi"
python -m automation_file server --host 127.0.0.1 --port 9943
python -m automation_file http-server --host 127.0.0.1 --port 9944
python -m automation_file drive-upload my.txt --token token.json --credentials creds.json
python -m automation_file mcp --allowed-actions FA_file_checksum,FA_fast_find
automation_file_mcp --allowed-actions FA_file_checksum,FA_fast_find  # 已安装的 console script

# 存储层：ls、stat、cat、cp、mv、rm、mkdir、sync、checksum、verify、schemes（输出 JSON）
python -m automation_file storage ls s3://reports/2026 --recursive
python -m automation_file storage cp report.csv s3://reports/2026/report.csv
python -m automation_file storage sync ./site s3://www --delete --dry-run
python -m automation_file storage checksum s3://reports/2026/q1.csv

# 旧式标志（JSON 动作清单）
python -m automation_file --execute_file actions.json
python -m automation_file --execute_dir ./actions/
python -m automation_file --execute_str '[["FA_create_dir",{"dir_path":"x"}]]'
python -m automation_file --create_project ./my_project
```

## JSON 动作格式

每一项动作可以是单纯的命令名称、`[name, kwargs]` 组合，或 `[name, args]`
列表：

```json
[
  ["FA_create_file", {"file_path": "test.txt"}],
  ["FA_drive_upload_to_drive", {"file_path": "test.txt"}],
  ["FA_drive_search_all_file"]
]
```

## 文档

完整 API 文档位于 `docs/`，可用 Sphinx 生成：

```bash
pip install -r docs/requirements.txt
sphinx-build -b html docs/source docs/_build/html
```

架构笔记、代码规范与安全考量请参见 [`CLAUDE.md`](CLAUDE.md)。
