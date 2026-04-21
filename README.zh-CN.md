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
- **跨后端复制** — `FA_copy_between` 通过 `local://`、`s3://`、`drive://`、`azure://`、`dropbox://`、`sftp://`、`ftp://` URI 在任意两个后端之间搬运数据
- **调度器重叠防护** — 正在执行的作业在下次触发时会被跳过,除非显式传入 `allow_overlap=True`
- **服务器动作 ACL** — `allowed_actions=(...)` 限制 TCP / HTTP 服务器可派发的命令
- **变量替换** — 动作参数中可选使用 `${env:VAR}` / `${date:%Y-%m-%d}` / `${uuid}` / `${cwd}`,通过 `execute_action(..., substitute=True)` 展开
- **条件执行** — `FA_if_exists` / `FA_if_newer` / `FA_if_size_gt` 仅在路径守卫通过时执行嵌套动作清单
- **SQLite 审计日志** — `AuditLog(db_path)` 为每个动作记录 actor / status / duration;通过 `recent` / `count` / `purge` 查询
- **文件完整性监控** — `IntegrityMonitor` 按 manifest 轮询整棵树,检测到 drift 时触发 callback + 通知
- **HTTPActionClient SDK** — HTTP 动作服务器的类型化 Python 客户端,具 shared-secret 认证、loopback 守护与 OPTIONS ping
- **AES-256-GCM 文件加密** — `encrypt_file` / `decrypt_file` 搭配 `generate_key()` / `key_from_password()`(PBKDF2-HMAC-SHA256);JSON 动作 `FA_encrypt_file` / `FA_decrypt_file`
- **Prometheus metrics 导出器** — `start_metrics_server()` 提供 `automation_file_actions_total{action,status}` 计数器与 `automation_file_action_duration_seconds{action}` 直方图
- PySide6 GUI（`python -m automation_file ui`）每个后端一个页签，含 JSON 动作执行器，另有 Triggers、Scheduler、实时 Progress 专属页签
- 功能丰富的 CLI，包含一次性子命令与旧式 JSON 批量标志
- 项目脚手架（`ProjectBuilder`）协助构建以 executor 为核心的自动化项目

## 架构

```mermaid
flowchart LR
    User[User / CLI / JSON batch]

    subgraph Facade["automation_file (facade)"]
        Public["Public API<br/>execute_action, execute_action_parallel,<br/>validate_action, driver_instance,<br/>start_autocontrol_socket_server,<br/>start_http_action_server, Quota,<br/>retry_on_transient, safe_join, ..."]
    end

    subgraph Core["core"]
        Registry[(ActionRegistry<br/>FA_* commands)]
        Executor[ActionExecutor]
        Callback[CallbackExecutor]
        Loader[PackageLoader]
        Json[json_store]
        Retry[retry]
        QuotaMod[quota]
        Progress[progress<br/>Token + Reporter]
    end

    subgraph Events["event-driven"]
        TriggerMod["trigger<br/>watchdog file watcher"]
        SchedulerMod["scheduler<br/>cron background thread"]
    end

    subgraph Local["local"]
        FileOps[file_ops]
        DirOps[dir_ops]
        ZipOps[zip_ops]
        Safe[safe_paths]
    end

    subgraph Remote["remote"]
        UrlVal[url_validator]
        Http[http_download]
        Drive["google_drive<br/>client + *_ops"]
        S3["s3"]
        Azure["azure_blob"]
        Dropbox["dropbox_api"]
        SFTP["sftp"]
    end

    subgraph Server["server"]
        TCP[TCPActionServer]
        HTTP[HTTPActionServer]
    end

    subgraph UI["ui (PySide6)"]
        Launcher[launch_ui]
        MainWindow["MainWindow<br/>9-tab control surface"]
    end

    subgraph Project["project / utils"]
        Builder[ProjectBuilder]
        Templates[templates]
        Discovery[file_discovery]
    end

    User --> Public
    User --> Launcher
    Launcher --> MainWindow
    MainWindow --> Public
    Public --> Executor
    Public --> Callback
    Public --> Loader
    Public --> TCP
    Public --> HTTP

    Executor --> Registry
    Executor --> Retry
    Executor --> QuotaMod
    Callback --> Registry
    Loader --> Registry
    TCP --> Executor
    HTTP --> Executor
    Executor --> Json

    Registry --> FileOps
    Registry --> DirOps
    Registry --> ZipOps
    Registry --> Safe
    Registry --> Http
    Registry --> Drive
    Registry --> S3
    Registry --> Azure
    Registry --> Dropbox
    Registry --> SFTP
    Registry --> Builder
    Registry --> TriggerMod
    Registry --> SchedulerMod
    Registry --> Progress

    TriggerMod --> Executor
    SchedulerMod --> Executor
    Http --> Progress
    S3 --> Progress

    Http --> UrlVal
    Http --> Retry
    Builder --> Templates
    Builder --> Discovery
```

`build_default_registry()` 构建的 `ActionRegistry` 是所有 `FA_*` 命令的唯一
权威来源。`ActionExecutor`、`CallbackExecutor`、`PackageLoader`、
`TCPActionServer`、`HTTPActionServer` 都通过同一份共享 registry（以
`executor.registry` 对外公开）解析命令。

## 安装

```bash
pip install automation_file
```

单次安装即涵盖所有后端（Google Drive、S3、Azure Blob、Dropbox、SFTP）以及
PySide6 GUI — 日常使用不需要任何 extras。

```bash
pip install "automation_file[dev]"       # ruff, mypy, pre-commit, pytest-cov, build, twine
```

要求：
- Python 3.10+
- 内置依赖：`google-api-python-client`、`google-auth-oauthlib`、
  `requests`、`tqdm`、`boto3`、`azure-storage-blob`、`dropbox`、`paramiko`、
  `PySide6`、`watchdog`

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
from automation_file import AutomationConfig, notification_manager

config = AutomationConfig.load("automation_file.toml")
config.apply_to(notification_manager)
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
按 manifest 轮询整棵树,检测到 drift 时触发 callback + 通知:

```python
from automation_file import IntegrityMonitor, notification_manager, write_manifest

write_manifest("/srv/site", "/srv/MANIFEST.json")

mon = IntegrityMonitor(
    root="/srv/site",
    manifest_path="/srv/MANIFEST.json",
    interval=60.0,
    manager=notification_manager,
    on_drift=lambda summary: print("drift:", summary),
)
mon.start()
```

加载 manifest 时的错误也会被视为 drift,让篡改与配置问题走同一条处理
路径。

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
