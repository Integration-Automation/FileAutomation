# FileAutomation 1.0 Roadmap

## Purpose

This draft defines the product and engineering roadmap for the next major evolution of FileAutomation.

Target positioning:

> Universal File Layer + File Integrity + Data Pipeline Runtime

FileAutomation should become the common file/data infrastructure layer for Integration-Automation projects. The roadmap covers architecture, packaging, storage abstraction, integration testing, integrity monitoring, pipeline/DAG execution, scheduling, notifications, auditability, UI redesign, AI/MCP integration, release engineering, and the path to 1.0.

---

## 1. Product vision

Target architecture:

Clients (CLI / Python / REST / MCP / GUI / Integration-Automation projects)
  -> Pipeline Runtime (DAG / Scheduler / Retry / Events / Notifications / Audit)
  -> Universal File Layer (File / Directory / Stream / Artifact / URI / Metadata / Checksum / Version)
  -> Storage Layer (Local / S3 / Azure / GDrive / Dropbox / SFTP / FTP / WebDAV / SMB / fsspec / additional adapter)

Long-term public API should converge around:

    from automation_file import File, Storage, Pipeline, IntegrityMonitor

Existing FA_* action APIs should remain available as a compatibility/automation interface while the new object-oriented API becomes the recommended application API.

## 2. Architecture 2.0

Core layers:

1. Core: domain objects, action registry, executor, plugin loading, configuration, error model.
2. Storage: common backend protocol, URI resolver, File abstraction, backend adapters.
3. Pipeline Runtime: DAG, task execution, retry, timeout, cancellation, checkpoint/resume, idempotency, conditions.
4. Event/Operations: events, scheduler, notification router, audit log, metrics/tracing.
5. Integrity: snapshots, manifests, watchers, checksum engines, drift detection, alerts, remediation.
6. Interfaces: CLI, Python API, REST/HTTP, MCP, GUI/Web UI.

Core must not depend on GUI or optional remote-storage SDKs.

## 3. Package and extras redesign

Goal: the base installation remains lightweight and usable without GUI or cloud SDKs.

Preferred package layout:

    packages/
      automation-file/
      automation-file-gui/
      automation-file-s3/
      automation-file-gdrive/
      automation-file-azure/
      automation-file-dropbox/
      automation-file-sftp/
      automation-file-ftp/
      automation-file-webdav/
      automation-file-smb/
      automation-file-fsspec/

Initial implementation may use one distribution with strict optional extras; separate distributions can follow once adapter APIs stabilize.

Required extras:

    automation-file
    automation-file[gui]
    automation-file[s3]
    automation-file[gdrive]
    automation-file[azure]
    automation-file[dropbox]
    automation-file[sftp]
    automation-file[ftp]
    automation-file[webdav]
    automation-file[smb]
    automation-file[fsspec]
    automation-file[all]
    automation-file[dev]
    automation-file[test]

Acceptance criteria:
- Base package does not import optional SDKs at import time.
- GUI dependencies are not required for CLI/library use.
- Each backend can be installed independently.
- [all] installs all supported adapters.
- Documentation maps features to extras.
- CI verifies minimal install and every optional extra.

## 4. Universal Storage Layer

All storage backends must implement one contract. The contract should cover exists, stat, upload, download, delete, list, mkdir, and checksum, with FileInfo/Checksum types and consistent errors.

Target eleven backend slots:

1. Local filesystem
2. S3-compatible object storage
3. Azure Blob
4. Google Drive
5. Dropbox
6. SFTP
7. FTP/FTPS
8. WebDAV
9. SMB/CIFS
10. fsspec
11. One additional first-class backend selected during implementation based on existing project support and maintenance value

Existing OneDrive/Box integrations should either be promoted into the formal storage contract or explicitly documented as legacy/action-only adapters during the transition.

Common URI model:

    local:///data/report.csv
    s3://bucket/report.csv
    azure://container/report.csv
    gdrive://folder/report.csv
    dropbox:///reports/report.csv
    sftp://server/data/report.csv
    ftp://server/data/report.csv
    webdav://server/files/report.csv
    smb://server/share/report.csv

URI resolver requirements: validate schemes, normalize paths, preserve backend authority, reject ambiguous URIs, expose backend capabilities, and produce actionable errors.

Target File API:

    file = File('s3://bucket/report.csv')
    file.exists()
    file.stat()
    file.read()
    file.write(data)
    file.copy_to('sftp://server/archive/report.csv')
    file.move_to(...)
    file.delete()
    file.checksum()

File should expose metadata, size, modified_at, etag, version, and content_type where available without leaking backend implementation details.

## 5. Backend integration test program

Every backend must pass the same contract suite.

Minimum coverage:
- exists
- stat
- upload/download/delete/list/mkdir/checksum
- nested directories
- empty files
- large files
- Unicode paths
- binary data
- overwrite behavior
- missing-resource behavior
- permission/access errors
- retryable failures
- metadata preservation where supported

CI integration environments should include Local, MinIO/S3-compatible, Azurite, SFTP, FTP/FTPS, WebDAV, and Samba/SMB. Cloud-specific adapters should additionally have credential-gated integration jobs when secrets are available.

Test matrix should cover supported Python versions, Linux, Windows, macOS where practical, minimal installation, each optional backend, contract tests, and end-to-end pipeline scenarios.

## 6. IntegrityMonitor 2.0

IntegrityMonitor becomes a complete file integrity monitoring subsystem.

Components:

    IntegrityMonitor
      - Snapshot
      - Manifest
      - Watcher
      - Hash Engine
      - Change Detector
      - Baseline Manager
      - Alert Engine
      - Remediation
      - Audit integration

Detect created, modified, deleted, renamed/moved where detectable, metadata changes, permission changes, and checksum changes.

Algorithms: SHA-256, SHA-512, BLAKE2, and MD5 for compatibility/non-security use. Security-sensitive verification defaults to SHA-256 or stronger.

Modes: snapshot, verify, watch, continuous.

Manifest records should include path, size, modification time, checksum, algorithm, content type where available, backend, and version/etag where available.

Drift response should support detect -> audit, notify, quarantine, restore. Remediation is opt-in and explicit; monitoring remains read-only by default.

## 7. Pipeline Runtime

Introduce a first-class Pipeline abstraction.

Conceptual API:

    pipeline = Pipeline('daily-report')
    pipeline.task('download', download(...))
    pipeline.task('validate', validate(...), depends_on=['download'])
    pipeline.task('transform', transform(...), depends_on=['validate'])
    pipeline.task('upload', upload(...), depends_on=['transform'])
    pipeline.run()

DAG capabilities:
- dependency ordering
- parallel fan-out
- retries and retry policy
- timeout
- cancellation
- skip/failure propagation
- conditional execution
- idempotency
- checkpointing
- resume
- dry-run
- execution history

Support versioned YAML/JSON pipeline definitions with schema validation.

Example pipeline:

    name: daily-report
    schedule:
      cron: '0 2 * * *'
      timezone: Asia/Taipei
    tasks:
      download: source s3://input/report.csv -> /tmp/report.csv
      verify: depends_on download
      transform: depends_on verify
      upload: depends_on transform -> s3://output/report.csv
      notify: depends_on upload

## 8. Scheduler

Cron becomes one scheduling source in a unified scheduler.

Supported triggers: cron, manual/API, file event, webhook/event, pipeline dependency.

Scheduler records scheduled, started, completed, failed, skipped, timeout, and cancelled states. Existing overlap protection becomes part of the scheduler contract.

Timezone-aware cron configuration is required.

## 9. Event and notification architecture

Notifications should be driven by events rather than individual modules directly calling sinks.

Core events:
- PipelineStarted
- PipelineCompleted
- PipelineFailed
- TaskStarted
- TaskCompleted
- TaskFailed
- IntegrityViolation
- StorageError
- SchedulerError
- SystemError

NotificationRouter fans out to Slack, Email, Discord, Teams, Telegram, Webhook, PagerDuty, and future sinks.

Requirements: per-sink error isolation, deduplication, rate limiting, configurable routing, structured payloads, severity, and correlation IDs.

## 10. Audit system

Audit must answer: who did what, when, against which resource, using which backend, and with what result?

Target fields:

    id, timestamp, actor, source, pipeline, task, action, resource, backend,
    status, duration_ms, error, metadata

Audit covers file operations, pipeline/task execution, scheduler events, integrity violations, notification failures, and applicable administrative/configuration changes.

Start with SQLite-friendly storage while defining an interface for future PostgreSQL/remote audit backends.

## 11. UI 2.0

Redesign around operational workflows rather than backend implementation tabs.

Target navigation:

    Dashboard
    Files
    Storage
    Pipelines
    Scheduler
    Integrity
    Audit
    Notifications
    Settings

Dashboard emphasizes health, running jobs, success/failure, integrity drift, recent events, and storage status.

Pipeline editor must support drag/drop tasks, dependency edges, parameter editing, validation, dry-run, test, run, retry, logs, and execution status.

PySide6 and Web UI should consume the same application/domain layer.

## 12. AI and MCP integration

MCP should become a semantic interface to FileAutomation.

Target semantic tools:

    file_read
    file_write
    file_copy
    file_move
    file_search
    file_checksum
    file_verify
    storage_list
    storage_copy
    pipeline_create
    pipeline_run
    pipeline_status
    integrity_status
    audit_search

Keep the existing automatic FA_* MCP bridge for compatibility.

AI-facing operations require explicit permission boundaries, dry-run support, safe defaults, and existing SSRF/auth/path-safety protections.

Example target workflow: move yesterday's CSV from S3 to company SFTP, verify SHA-256, audit the transfer, and notify Slack on failure.

## 13. Release engineering

The existing automatic PyPI publishing should evolve into:

    PR
      -> lint
      -> typecheck
      -> unit tests
      -> integration tests
      -> contract tests
      -> security checks
      -> package build
      -> merge
      -> release
      -> PyPI Trusted Publishing

Use SemVer MAJOR.MINOR.PATCH.

1.0 must freeze stable contracts for StorageBackend, URI handling, File, Pipeline, IntegrityMonitor, and Event/Audit models.

## 14. Documentation and discoverability

Organize docs around user goals:
1. Quick start
2. File API
3. Storage backends
4. Pipelines
5. Scheduler
6. Integrity monitoring
7. Notifications
8. Audit
9. CLI
10. REST/HTTP
11. MCP/AI
12. GUI
13. Plugin development
14. Security
15. Deployment
16. Integration testing

Every feature needs a minimal example, production example, API reference, configuration reference, and diagnostics/failure guidance.

README, PyPI metadata, docs, examples, MCP docs, and repository topics should consistently communicate the universal file layer/data pipeline positioning.

## 15. Milestones

### M1 — Architecture and packaging
- [ ] Define domain boundaries
- [ ] Define public API policy
- [ ] Define StorageBackend contract
- [ ] Define URI specification
- [ ] Separate optional dependencies
- [ ] Define extras
- [ ] Add compatibility layer for FA_* APIs

### M2 — Universal storage layer
- [ ] URI resolver
- [ ] File abstraction
- [ ] Local migration
- [ ] S3 migration
- [ ] Azure migration
- [ ] Google Drive migration
- [ ] Dropbox migration
- [ ] SFTP migration
- [ ] FTP/FTPS migration
- [ ] WebDAV migration
- [ ] SMB/CIFS migration
- [ ] fsspec adapter
- [ ] Formalize eleventh backend
- [ ] Cross-backend operations through common layer

### M3 — Backend integration tests
- [ ] Storage contract suite
- [ ] Local tests
- [ ] MinIO tests
- [ ] Azurite tests
- [ ] SFTP tests
- [ ] FTP/FTPS tests
- [ ] WebDAV tests
- [ ] SMB tests
- [ ] Cloud credential-gated tests
- [ ] Unicode/binary/large-file cases
- [ ] Failure/retry cases
- [ ] CI matrix

### M4 — IntegrityMonitor 2.0
- [ ] Snapshot model
- [ ] Manifest schema/versioning
- [ ] Hash engine
- [ ] Baseline management
- [ ] Change detection
- [ ] Watch/continuous mode
- [ ] Alert integration
- [ ] Audit integration
- [ ] Optional remediation/quarantine
- [ ] CLI/API/GUI integration

### M5 — Pipeline Runtime
- [ ] Pipeline domain model
- [ ] DAG runtime v2
- [ ] Task lifecycle
- [ ] Retry/timeout/cancellation
- [ ] Conditions
- [ ] Idempotency
- [ ] Checkpoint/resume
- [ ] Dry-run
- [ ] YAML/JSON schema
- [ ] Execution history

### M6 — Scheduler / Events / Notifications / Audit
- [ ] Unified scheduler
- [ ] Cron timezone support
- [ ] Event model
- [ ] Notification router
- [ ] Sink routing
- [ ] Dedup/rate limiting
- [ ] Audit schema v2
- [ ] Correlation IDs
- [ ] Operational metrics

### M7 — UI 2.0
- [ ] Information architecture
- [ ] Dashboard
- [ ] Storage explorer
- [ ] Pipeline editor
- [ ] Scheduler view
- [ ] Integrity view
- [ ] Audit viewer
- [ ] Notification configuration
- [ ] Settings
- [ ] Shared application/service layer

### M8 — MCP / AI
- [ ] Semantic MCP tools
- [ ] File operations
- [ ] Storage operations
- [ ] Pipeline operations
- [ ] Integrity operations
- [ ] Audit search
- [ ] Permission model
- [ ] Dry-run
- [ ] Safety validation
- [ ] MCP documentation/examples

### M9 — 1.0 release
- [ ] Freeze public APIs
- [ ] Migration guide
- [ ] Deprecation policy
- [ ] Complete test matrix
- [ ] Security review
- [ ] Documentation audit
- [ ] Packaging audit
- [ ] PyPI release
- [ ] Release notes

## 16. Epic / issue breakdown

Create/track these epics:

1. Core Architecture 2.0
2. Storage Abstraction
3. Optional Extras
4. Backend Contract Tests
5. IntegrityMonitor 2.0
6. Pipeline Runtime
7. Scheduler
8. Notification/Event System
9. Audit
10. GUI 2.0
11. MCP / AI Integration
12. Documentation
13. Release Engineering

Representative implementation issues:

- Define StorageBackend protocol
- Define URI specification
- Implement URI resolver
- Implement File object
- Refactor LocalStorage
- Refactor S3Storage
- Refactor AzureStorage
- Refactor GoogleDriveStorage
- Refactor DropboxStorage
- Refactor SFTPStorage
- Refactor FTPStorage
- Refactor WebDAVStorage
- Refactor SMBStorage
- Refactor fsspec adapter
- Add backend contract tests
- Add MinIO integration environment
- Add Azurite integration environment
- Add SFTP integration environment
- Add FTP integration environment
- Add WebDAV integration environment
- Add SMB integration environment
- Redesign IntegrityMonitor
- Add Integrity baseline management
- Add Integrity remediation
- Implement Pipeline domain model
- Implement DAG runtime v2
- Implement retry/timeout/cancellation
- Implement pipeline persistence
- Implement scheduler event model
- Implement notification router
- Implement Audit schema v2
- Redesign GUI
- Implement visual pipeline editor
- Implement semantic MCP tools
- Add 1.0 migration guide

## 17. Architectural rules

1. Core must not require GUI dependencies.
2. Backend SDKs are optional.
3. All storage backends satisfy one contract.
4. Cross-backend operations use the common File/Storage layer.
5. New public APIs avoid backend-specific implementation details unless unavoidable.
6. Existing FA_* APIs remain compatible during transition.
7. Pipeline execution is observable and auditable.
8. Integrity monitoring is read-only by default.
9. Remediation requires explicit configuration.
10. MCP tools use semantic, stable names.
11. Externally reachable operations retain SSRF/auth/path-safety protections.
12. Every new backend ships with contract tests.
13. Every major feature needs CLI/API documentation and an end-to-end example.
14. GUI is built against stable public application/domain APIs.
15. Public API stability is a 1.0 criterion.

## 18. Definition of Done for 1.0

FileAutomation 1.0 is ready when:

- base package installs without unnecessary optional dependencies;
- storage adapters implement a common contract;
- supported backend matrix has integration coverage;
- File/Storage/URI APIs are stable;
- IntegrityMonitor can baseline, verify, watch, alert, audit, and optionally remediate;
- Pipeline executes DAGs with retry, timeout, cancellation, conditions, checkpoint/resume, and audit;
- cron scheduling is integrated with pipeline execution;
- notifications are event-driven;
- audit provides end-to-end traceability;
- GUI 2.0 is built on the public application layer;
- MCP exposes semantic file/storage/pipeline/integrity tools;
- CI covers unit, contract, integration, and end-to-end paths;
- releases are automatically built and published to PyPI;
- documentation includes migration and production deployment guidance;
- stable public API is explicitly documented.

## 19. Product positioning

> FileAutomation is the universal file layer and data-pipeline runtime for Integration-Automation: one API for local and remote storage, file integrity monitoring, DAG workflows, scheduling, notifications, audit, and AI/MCP automation.

This positioning should be reflected consistently across README, PyPI metadata, documentation, examples, MCP documentation, and repository topics.

## 20. Recommended implementation order

Do not start with the GUI.

    Architecture
      -> Storage API
      -> Extras / packaging
      -> Integration tests
      -> IntegrityMonitor
      -> Pipeline / DAG
      -> Scheduler + Notifications + Audit
      -> GUI 2.0
      -> MCP / AI
      -> 1.0

The GUI should consume stable application/domain APIs; rebuilding it before those APIs stabilize would cause repeated UI rewrites.

## Status

This is intentionally a draft planning PR. It establishes the target architecture and implementation backlog first. Subsequent PRs should implement the milestones incrementally rather than attempting to merge the entire roadmap as one code change.