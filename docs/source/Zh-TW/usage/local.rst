本地檔案操作
============

路徑安全
--------

.. code-block:: python

   from automation_file import safe_join

   target = safe_join("/data/jobs", user_supplied_path)
   # -> 若解析後的路徑越過 /data/jobs，將擲出 PathTraversalException。

任何使用者提供的路徑都應透過
:func:`~automation_file.local.safe_paths.safe_join`（或 ``is_within``
檢查）解析。直接串接 + ``Path.resolve()`` 會被符號連結與 ``..`` 段繞過。

快速檔案搜尋
------------

:func:`~automation_file.fast_find` 會挑選目前主機上代價最低的後端——
優先使用作業系統索引，否則回退為串流式 scandir 走訪，
讓大目錄樹以最低代價被搜尋：

* macOS：``mdfind``（Spotlight）
* Linux：``plocate`` / ``locate`` 資料庫
* Windows：若已安裝則使用 Everything 的 ``es.exe`` CLI
* 回退：``os.scandir`` 產生器搭配 ``fnmatch`` 比對，可由 ``limit=`` 提早結束

.. code-block:: python

   from automation_file import fast_find, scandir_find, has_os_index

   # 若有索引則查詢，否則回退 scandir。
   results = fast_find("/var/log", "*.log", limit=100)

   # 強制走可攜路徑（不使用作業系統索引）。
   results = fast_find("/data", "report_*.csv", use_index=False)

   # 串流產生器——可不掃整棵樹就提早停止。
   for path in scandir_find("/data", "*.csv"):
       if "2026" in path:
           break

   # fast_find 將嘗試哪個索引？回傳 "mdfind" / "locate" /
   # "plocate" / "es" / None。
   has_os_index()

JSON 形式：``[["FA_fast_find", {"root": "/var/log", "pattern": "*.log",
"limit": 50}]]``。

校驗和與完整性
--------------

以串流方式雜湊任意檔案（任何 :mod:`hashlib` 演算法），
使用常數時間比較對照預期摘要：

.. code-block:: python

   from automation_file import file_checksum, verify_checksum

   digest = file_checksum("bundle.tar.gz")                 # 預設 sha256
   verify_checksum("bundle.tar.gz", digest)                # -> True
   verify_checksum("bundle.tar.gz", "deadbeef...", algorithm="blake2b")

JSON 形式：``FA_file_checksum`` / ``FA_verify_checksum``。

檔案去重
--------

:func:`~automation_file.find_duplicates` 透過 ``os.scandir`` 一次性
走訪目錄樹，並以「大小 → 部分雜湊 → 全量雜湊」三段式進行篩選。
大小唯一的檔案根本不會被雜湊，因此即使百萬檔案也能廉價掃描：

.. code-block:: python

   from automation_file import find_duplicates

   groups = find_duplicates("/data", min_size=1024)
   # groups: list[list[str]]，每個內層清單都是互相重複的檔案，依大小遞減排列。

JSON 形式：``FA_find_duplicates``。

增量目錄同步
------------

:func:`~automation_file.sync_dir` 把 ``src`` 增量鏡像到 ``dst``，
僅複製新增或變更的檔案。預設依 ``(size, mtime)`` 偵測變化；
當 mtime 不可靠時改用 ``compare="checksum"``。``dst`` 中的多餘檔案
預設保留——傳入 ``delete=True`` 才會清掉（``dry_run=True`` 可預覽）：

.. code-block:: python

   from automation_file import sync_dir

   summary = sync_dir("/data/src", "/data/dst", delete=True)
   # summary: {"copied": [...], "skipped": [...], "deleted": [...],
   #           "errors": [...], "dry_run": False}

符號連結會以連結重新建立而非被跟隨。JSON 形式：``FA_sync_dir``。

目錄清單
--------

把整棵目錄樹的每個檔案寫入 JSON 清單，稍後再驗證目錄是否變化。
適合用於發行產物驗證、備份完整性檢查與移動前的預檢：

.. code-block:: python

   from automation_file import write_manifest, verify_manifest

   write_manifest("/release/payload", "/release/MANIFEST.json")

   # 之後……
   result = verify_manifest("/release/payload", "/release/MANIFEST.json")
   if not result["ok"]:
       raise SystemExit(f"manifest mismatch: {result}")

``result`` 會分別回報 ``matched`` / ``missing`` / ``modified`` / ``extra``。
多餘檔案不會讓驗證失敗（與 ``sync_dir`` 預設不刪除一致）；
``missing`` 與 ``modified`` 才會失敗。JSON 形式：
``FA_write_manifest`` / ``FA_verify_manifest``。
