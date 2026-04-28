本地文件操作
============

路径安全
--------

.. code-block:: python

   from automation_file import safe_join

   target = safe_join("/data/jobs", user_supplied_path)
   # -> 若解析后的路径越过 /data/jobs，将抛出 PathTraversalException。

任何用户提供的路径都应通过
:func:`~automation_file.local.safe_paths.safe_join`（或 ``is_within``
判断）解析。直接拼接 + ``Path.resolve()`` 会被符号链接和 ``..`` 段绕过。

快速文件查找
------------

:func:`~automation_file.fast_find` 会挑选当前主机上代价最低的后端——
优先使用操作系统索引，否则回退为流式 scandir 走查，
让大目录树以最低开销被搜索：

* macOS：``mdfind``（Spotlight）
* Linux：``plocate`` / ``locate`` 数据库
* Windows：若已安装则使用 Everything 的 ``es.exe`` CLI
* 回退：``os.scandir`` 生成器配合 ``fnmatch`` 匹配，可由 ``limit=`` 提前终止

.. code-block:: python

   from automation_file import fast_find, scandir_find, has_os_index

   # 若有索引则查询，否则回退 scandir。
   results = fast_find("/var/log", "*.log", limit=100)

   # 强制走可移植路径（不使用操作系统索引）。
   results = fast_find("/data", "report_*.csv", use_index=False)

   # 流式生成器——可不扫描整棵树就提前停止。
   for path in scandir_find("/data", "*.csv"):
       if "2026" in path:
           break

   # fast_find 将尝试哪种索引？返回 "mdfind" / "locate" /
   # "plocate" / "es" / None。
   has_os_index()

JSON 形式：``[["FA_fast_find", {"root": "/var/log", "pattern": "*.log",
"limit": 50}]]``。

校验和与完整性
--------------

以流式方式哈希任意文件（任何 :mod:`hashlib` 算法），
使用常数时间比较来对照预期摘要：

.. code-block:: python

   from automation_file import file_checksum, verify_checksum

   digest = file_checksum("bundle.tar.gz")                 # 默认 sha256
   verify_checksum("bundle.tar.gz", digest)                # -> True
   verify_checksum("bundle.tar.gz", "deadbeef...", algorithm="blake2b")

JSON 形式：``FA_file_checksum`` / ``FA_verify_checksum``。

文件去重
--------

:func:`~automation_file.find_duplicates` 通过 ``os.scandir`` 一次性
走查目录树，并以「大小 → 部分哈希 → 全量哈希」三段式进行筛选。
大小唯一的文件根本不会被哈希，因此即使百万级别也能廉价扫描：

.. code-block:: python

   from automation_file import find_duplicates

   groups = find_duplicates("/data", min_size=1024)
   # groups: list[list[str]]，每个内层列表都是互相重复的文件，按大小降序。

JSON 形式：``FA_find_duplicates``。

增量目录同步
------------

:func:`~automation_file.sync_dir` 把 ``src`` 增量镜像到 ``dst``，仅复制
新增或变更的文件。默认按 ``(size, mtime)`` 检测变化；
当 mtime 不可靠时改用 ``compare="checksum"``。``dst`` 中的多余文件默认保留——
传入 ``delete=True`` 才会清理（``dry_run=True`` 可预览）：

.. code-block:: python

   from automation_file import sync_dir

   summary = sync_dir("/data/src", "/data/dst", delete=True)
   # summary: {"copied": [...], "skipped": [...], "deleted": [...],
   #           "errors": [...], "dry_run": False}

符号链接会按链接重新创建而不是被跟随。JSON 形式：``FA_sync_dir``。

目录清单
--------

把整棵目录树的每个文件写入 JSON 清单，稍后再校验目录是否变化。
适合用于发布产物校验、备份完整性检查与移动前的预检：

.. code-block:: python

   from automation_file import write_manifest, verify_manifest

   write_manifest("/release/payload", "/release/MANIFEST.json")

   # 之后……
   result = verify_manifest("/release/payload", "/release/MANIFEST.json")
   if not result["ok"]:
       raise SystemExit(f"manifest mismatch: {result}")

``result`` 会分别报告 ``matched`` / ``missing`` / ``modified`` / ``extra``。
多余文件不会让校验失败（与 ``sync_dir`` 默认不删除一致）；
``missing`` 与 ``modified`` 才会失败。JSON 形式：
``FA_write_manifest`` / ``FA_verify_manifest``。
