通用儲存層
==========

``automation_file.storage`` 讓每一種儲存都使用同一套位址語法、同一組操作與同一組
例外。:class:`~automation_file.File` 與 :class:`~automation_file.Storage` 是應用層
API；:class:`~automation_file.StorageBackend` 則是後端要實作的契約。

``FA_*`` 動作與各後端原有的函式（``s3_upload_file``、``sftp_download_file`` ……）
完全不變，可與本層並用。

.. note::

   本層是新功能，API 在 1.0 之前仍可能調整。目前內建本機檔案系統、記憶體儲存、
   S3 與 Azure Blob 四種後端。Google Drive、Dropbox、SFTP、FTP、WebDAV、SMB 與
   fsspec 在各自的轉接器完成之前，仍透過既有的用戶端與動作使用（見 :doc:`cloud`）；
   你也可以現在就自行撰寫後端，把它們接到本層之後（見 `撰寫後端`_）。

快速開始
--------

.. code-block:: python

   from automation_file import File, Storage

   report = File("local:///data/reports/q1.csv")     # 也可以直接寫 "reports/q1.csv"
   report.write("region,total\nEMEA,42\n")
   report.exists()                                    # True
   report.size                                        # 21
   report.read_text()
   report.checksum()                                  # Checksum("sha256", "…")
   report.verify("sha256:9f86d081…")                  # 常數時間比對

   archive = report.copy_to("memory://scratch/archive/q1.csv")
   report.move_to("local:///data/done/q1.csv")

   reports = Storage("local:///data/reports")
   for info in reports.list_dir(recursive=True):
       print(info.path, info.size, info.modified_at)
   reports.upload("q2.csv", "2026/q2.csv")
   reports.file("2026/q2.csv").download_to("copy-of-q2.csv")
   reports.delete("2026", recursive=True)

建立 ``File`` 或 ``Storage`` 物件不會碰觸任何儲存。每次呼叫才查找後端，因此可以在
後端初始化或掛載之前先建立物件。

儲存 URI
--------

.. code-block:: text

   <scheme>://<authority>/<path>

   local:///data/report.csv          s3://bucket/report.csv
   local:///C:/data/report.csv       azure://container/report.csv
   sftp://server/data/report.csv     dropbox:///reports/report.csv
   memory://scratch/report.csv       smb://server/share/report.csv

``scheme``
    決定使用哪個後端，一律轉為小寫。``file`` 是 ``local`` 的別名，``az`` 是
    ``azure`` 的別名。

``authority``
    後端找到自身根目錄所需的資訊：bucket、container 或主機名稱，保留原樣。憑證
    不屬於 URI，因此 ``user@host`` 與 ``user:password@host`` 會被拒絕，而且錯誤
    訊息不會重複顯示這些內容。

``path``
    按字面解讀。不做百分比解碼，``?`` 與 ``#`` 都是一般字元，所以
    ``s3://bucket/Q1 #3?.csv`` 指的就是那個 key。空區段與 ``.`` 區段會被捨棄；
    ``..`` 區段視為錯誤，因此路徑永遠無法跳出它所接上的根目錄。

本機路徑
    不含 ``://`` 的文字是檔案系統路徑，會先轉成絕對路徑：``reports/a.csv``、
    ``/data/a.csv`` 與 ``C:\data\a.csv`` 都能直接使用，:class:`pathlib.Path` 也
    一樣。在 Windows 上，UNC 路徑 ``\\server\share\a.csv`` 等同
    ``local://server/share/a.csv``。

有歧義的文字
    ``sftp:/data/a.csv`` 可能是少打一個斜線的 URI，也可能是名為 ``sftp:`` 的本機
    檔案。這種寫法會被拒絕，訊息中會列出兩種明確的寫法：URI 寫成 ``sftp://…``，
    本機檔案寫成 ``./sftp:/data/a.csv``。

:func:`~automation_file.parse_storage_uri` 回傳不可變的
:class:`~automation_file.StorageURI`，具有 ``scheme``、``authority``、``path``、
``name``、``parent`` 與 ``joinpath()``。格式錯誤的輸入會拋出
:class:`~automation_file.StorageURIException`。

操作
----

每個後端的方法都相同，``File`` 與 ``Storage`` 會轉呼叫它們。

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - 方法
     - 行為
   * - ``exists(path)``
     - 檔案或目錄存在時回傳 ``True``。
   * - ``stat(path)``
     - 回傳 :class:`~automation_file.FileInfo`。路徑不存在時拋出
       ``StorageNotFoundException``。
   * - ``list_dir(path="", recursive=False)``
     - 依路徑排序的項目。``recursive=True`` 回傳所有子孫項目，包含目錄。對象是
       檔案時拋出 ``StoragePathTypeException``。
   * - ``mkdir(path, parents=True, exist_ok=True)``
     - 建立目錄。若後端的目錄只是由檔案路徑隱含而來，則不會建立任何東西，也不
       需要建立。
   * - ``upload(local_path, path, overwrite=True)``
     - 存入本機檔案，並建立缺少的上層目錄。``overwrite=False`` 時若檔案已存在，
       拋出 ``StorageAlreadyExistsException``。
   * - ``download(path, local_path, overwrite=True)``
     - 先寫入同目錄下的 ``.part`` 檔，完成後才取代目標，所以下載失敗不會留下
       被截斷的檔案。
   * - ``delete(path, recursive=False, missing_ok=False)``
     - 目錄內有項目時需要 ``recursive=True``（否則拋出
       ``StorageNotEmptyException``）。儲存的根目錄永遠不會被刪除。
   * - ``checksum(path, algorithm="sha256")``
     - 回傳 :class:`~automation_file.Checksum`。支援 ``hashlib`` 中所有固定長度
       的演算法：``sha256``、``sha512``、``blake2b``、``md5``（僅供相容，不作
       安全用途）。
   * - ``read_bytes(path)`` / ``write_bytes(path, data)``
     - 讀寫整個檔案的內容。
   * - ``open_read(path)`` / ``open_write(path, overwrite=True)``
     - 二進位檔案物件，用於大到無法整個放進記憶體的內容。寫入的內容在物件關閉時
       才會存入；若因例外離開 ``with`` 區塊，則不會存入任何東西。
   * - ``copy_from(source, source_path, path)`` / ``move_from(…)``
     - 從任何後端（包含自己）傳輸。兩個後端之間能直接完成時走原生方式（例如
       本機重新命名），否則經由本機暫存檔。

``FileInfo`` 包含 ``path``、``name``、``is_dir``、``size``、``modified_at``（帶
時區的 UTC 時間）、``etag``、``version``、``content_type`` 與 ``metadata``。後端
無法提供的欄位為 ``None``。``FileInfo.to_dict()`` 與 ``Checksum.to_dict()`` 的結果
可直接序列化為 JSON。

``backend.capabilities`` 是 :class:`~automation_file.StorageCapabilities`，說明後端
會填入哪些選用的 ``FileInfo`` 欄位，以及它的目錄是真實存在（``directories=True``，
檔案系統）還是由檔案路徑隱含（``directories=False``，物件儲存）。

動作
----

本層也能從 JSON 動作清單使用，因此 CLI、TCP 與 HTTP 動作伺服器以及 MCP 主機都能呼叫。
每個 ``FA_storage_*`` 動作都以字串形式接收 URI，並回傳可序列化為 JSON 的值。

.. list-table::
   :header-rows: 1
   :widths: 28 40 32

   * - 動作
     - 參數
     - 回傳值
   * - ``FA_storage_exists``
     - ``uri``
     - ``true`` / ``false``
   * - ``FA_storage_stat``
     - ``uri``
     - 檔案資訊
   * - ``FA_storage_list``
     - ``uri, recursive=False``
     - 檔案資訊的清單
   * - ``FA_storage_mkdir``
     - ``uri, parents=True, exist_ok=True``
     - ``True``
   * - ``FA_storage_upload``
     - ``local_path, uri, overwrite=True``
     - 檔案資訊
   * - ``FA_storage_download``
     - ``uri, local_path, overwrite=True``
     - 本機路徑
   * - ``FA_storage_delete``
     - ``uri, recursive=False, missing_ok=False``
     - ``True``
   * - ``FA_storage_checksum``
     - ``uri, algorithm="sha256"``
     - ``{"algorithm": …, "value": …}``
   * - ``FA_storage_verify``
     - ``uri, expected, algorithm="sha256"``
     - ``true`` / ``false``
   * - ``FA_storage_copy``
     - ``source, target, overwrite=True``
     - 目標的檔案資訊
   * - ``FA_storage_move``
     - ``source, target, overwrite=True``
     - 目標的檔案資訊
   * - ``FA_storage_read_text``
     - ``uri, encoding="utf-8"``
     - 文字內容
   * - ``FA_storage_write_text``
     - ``uri, text, overwrite=True, encoding="utf-8"``
     - 檔案資訊
   * - ``FA_storage_copy_tree``
     - ``source, target, overwrite=True``
     - 摘要：``copied``、``skipped``、``deleted``、``errors``、``dry_run``
   * - ``FA_storage_sync``
     - ``source, target, delete=False, checksum=False, dry_run=False``
     - 摘要：``copied``、``skipped``、``deleted``、``errors``、``dry_run``
   * - ``FA_storage_schemes``
     - —
     - 已註冊的 scheme

檔案資訊是 ``FileInfo.to_dict()`` 再加上 ``uri`` 鍵：``uri``、``path``、``name``、
``is_dir``、``size``、``modified_at``（ISO 8601）、``etag``、``version``、
``content_type`` 與 ``metadata``。在 ``FA_storage_list`` 中，每個 ``path`` 都相對於
被列出的 URI。失敗時會拋出 `例外`_ 一節中的例外，執行器會把它記錄在該動作上，
不會中斷整份清單。

.. code-block:: json

   [
     ["FA_storage_copy", {"source": "s3://reports/2026/q1.csv",
                          "target": "local:///backup/2026/q1.csv"}],
     ["FA_storage_verify", {"uri": "local:///backup/2026/q1.csv",
                            "expected": "sha256:9f86d081884c7d65…"}],
     ["FA_storage_list", {"uri": "s3://reports/2026", "recursive": true}]
   ]

與其他檔案動作一樣，這些動作能存取行程所能存取的一切。在 TCP 或 HTTP 動作伺服器上
請傳入 :class:`~automation_file.ActionACL`，在 MCP 伺服器上請使用
``--allowed-actions``，只開放用戶端需要的動作。
:func:`~automation_file.register_storage_ops` 可把它們加入你自己的註冊表。

例外
----

全部衍生自 :class:`~automation_file.StorageException`，而它本身是
``FileAutomationException`` 的子類別。

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 例外
     - 拋出時機
   * - ``StorageURIException``
     - URI 或路徑格式錯誤、有歧義，或沒有後端能處理。
   * - ``StorageNotFoundException``
     - 路徑或上傳的本機來源檔不存在。它同時是 ``FileNotExistsException``，所以
       既有的例外處理仍然有效。
   * - ``StorageAlreadyExistsException``
     - 寫入會取代既有內容，而 ``overwrite`` / ``exist_ok`` 為關閉。
   * - ``StoragePathTypeException``
     - 對目錄執行檔案操作，或對檔案執行目錄操作。
   * - ``StorageNotEmptyException``
     - 刪除內有項目的目錄卻沒有指定 ``recursive=True``。
   * - ``StoragePermissionException``
     - 後端拒絕存取。
   * - ``StorageTransientException``
     - 值得重試的失敗：逾時、連線中斷、被限流。可作為 ``retry_on_transient`` 的
       ``retriable=`` 型別。
   * - ``StorageUnavailableException``
     - 後端尚未初始化，或其 SDK 未安裝。
   * - ``StorageUnsupportedException``
     - 後端無法執行所要求的操作（未知的校驗演算法、刪除根目錄）。

內建後端
--------

``LocalStorage``（``local://``，別名 ``file://``）
    ``LocalStorage()`` 涵蓋整個檔案系統，也就是 ``local:///…`` 解析的結果。
    ``LocalStorage(root)`` 則被限制在單一目錄樹內：每個路徑都經過
    :func:`~automation_file.safe_join`，因此透過符號連結離開根目錄的路徑會拋出
    ``PathTraversalException``。只要路徑來自行程之外，就應使用有根目錄的實例。

    讀寫時會跟隨符號連結；刪除時絕不跟隨：只移除連結本身，不動它指向的目標。
    遞迴列出時不會進入被連結的目錄。寫入會先寫到同目錄的暫存檔，再以原子操作
    取代目標。

``MemoryStorage``（``memory://<name>/…``）
    存在記憶體中的執行緒安全目錄樹，用於測試、試跑與範例。每個 ``<name>`` 是
    獨立的儲存，首次使用時建立。

``S3Storage``（``s3://<bucket>/<key>``）
    透過共用的 ``s3_instance`` 存取一個 bucket，初始化方式與以往相同：
    ``s3_instance.later_init(...)`` 或 ``FA_s3_later_init``。
    ``S3Storage(bucket, client=...)`` 可改用另一個 boto3 用戶端（其他帳號、
    MinIO），``prefix=`` 則把後端限制在某個前綴之下的 key。上傳時會依 key 的
    副檔名設定 ``ContentType``。``stat`` 回報大小、修改時間、ETag、內容類型、
    版本 ID 與中繼資料。共用同一個用戶端的兩個 S3 位置之間的複製由 S3 本身完成。

``AzureStorage``（``azure://<container>/<blob>``，別名 ``az://``）
    透過共用的 ``azure_blob_instance`` 存取一個 container
    （``azure_blob_instance.later_init(...)`` 或 ``FA_azure_blob_later_init``），
    或以 ``AzureStorage(container, service=...)`` 改用另一個
    ``BlobServiceClient``，例如 Azurite 模擬器。``prefix=`` 的用法與 S3 相同，
    ``stat`` 回報的欄位也相同。

S3 與 Azure Blob 都是物件儲存。目錄只在其下還有 key 時才存在，因此 ``mkdir`` 不會
建立任何東西，空目錄也無法存在（``capabilities.directories`` 為 ``False``）。其他
工具寫入、以 ``/`` 結尾的資料夾佔位 key 會顯示為目錄，絕不會顯示為檔案。校驗碼是
由內容計算而來，不取自 ETag，因為分段上傳的 ETag 並不是摘要。用戶端尚未初始化時，
每個呼叫都會拋出 ``StorageUnavailableException``。

.. code-block:: python

   from automation_file import File, azure_blob_instance, s3_instance

   s3_instance.later_init(region_name="us-east-1")
   azure_blob_instance.later_init(connection_string=connection_string)
   File("s3://reports/2026/q1.csv").copy_to("azure://backups/2026/q1.csv")

串流與目錄樹
------------

``File.open_read()`` 與 ``File.open_write()`` 回傳二進位檔案物件，
``File.iter_chunks()`` 則逐塊產出內容。本機後端直接就地讀取；其他後端提供一份
暫存的本機副本，物件關閉時即移除，因此兩種情況下記憶體用量都有上限。

``Storage.copy_to(target)`` 會把目錄下的每個檔案複製到 ``target`` 之下相同的相對
路徑，後端不限。``Storage.sync_to(target)`` 只複製有變動的部分：目標缺少的檔案、
大小不同的檔案，或來源版本較新的檔案。``checksum=True`` 改為比對 SHA-256 摘要而非
時間，代價是兩邊都要讀取一次。``delete=True`` 還會移除來源沒有的項目，
``dry_run=True`` 只回報會發生什麼而不做任何變更。兩者都回傳 ``TreeResult``，內含
``copied``、``skipped``、``deleted`` 與 ``errors``；失敗的檔案會記在 ``errors``
中，其餘檔案照常處理。

.. code-block:: python

   from automation_file import File, Storage

   with File("s3://logs/2026/big.log").open_read() as stream:
       for line in stream:
           ...

   with File("local:///exports/report.csv").open_write() as stream:
       stream.write(b"region,total\n")

   reports = Storage("s3://reports/2026")
   reports.copy_to("local:///backup/2026")                     # every file, any backend
   result = reports.sync_to("azure://backups/2026", delete=True, dry_run=True)
   result.copied, result.skipped, result.deleted, result.errors

掛載與註冊後端
--------------

URI 的解析分兩步。**掛載** 優先：掛載把一個後端實例綁定到某個 URI，位於該 URI
或其下的所有 URI 都交給這個後端，並去掉掛載點本身的路徑；符合的掛載中最長者
優先。沒有任何掛載認領的 URI 則交給 **scheme 工廠**。

.. code-block:: python

   from automation_file import File, LocalStorage, Storage

   # 為某個目錄樹取一個自己的名稱。透過 sandbox://jobs/… 存取的任何東西都離不開
   # /srv/jobs，即使經由符號連結也一樣。
   Storage.mount("sandbox://jobs", LocalStorage("/srv/jobs"))
   File("sandbox://jobs/42/out.csv").write(b"done")   # /srv/jobs/42/out.csv

   # 整個 scheme：工廠收到解析後的 URI，回傳 (backend, path)。
   Storage.register_scheme("vault", lambda uri: (vault_backend(uri.authority), uri.path))

   Storage.resolve("sandbox://jobs/42/out.csv")       # (LocalStorage('/srv/jobs'), '42/out.csv')
   Storage.schemes()                                  # ['azure', 'local', 'memory', 's3', 'sandbox', 'vault']

``Storage.mount`` / ``unmount`` / ``register_scheme`` / ``schemes`` / ``resolve``
操作的是整個行程共用的表。需要私有的表時使用
:class:`~automation_file.StorageResolver`，並以 ``resolver=`` 傳給 ``File`` 與
``Storage``。

掛載是依 URI 的文字比對。因此把有根目錄的後端掛在某個 ``local://`` 路徑上，只會
導向該路徑的那一種寫法；同一個目錄的另一種寫法（例如指向它的符號連結）仍然會
連到整個檔案系統。要限制不受信任的路徑，請像上面那樣給有根目錄的後端一個專屬的
scheme 或 authority，並且只接受其下的 URI。

撰寫後端
--------

繼承 :class:`~automation_file.StorageBackend` 並實作基本操作即可。上述公開方法
都由基底類別提供：它們會正規化路徑、檢查既有內容、拋出共用的例外並建立上層目錄。

.. code-block:: python

   from automation_file import FileInfo, StorageBackend, StorageCapabilities

   class VaultStorage(StorageBackend):
       scheme = "vault"
       capabilities = StorageCapabilities(directories=False, etag=True)

       def _stat(self, path): ...          # FileInfo；不存在時回傳 None；"" 是根目錄
       def _list_dir(self, path): ...      # 目錄的直接子項目
       def _upload(self, source, path): ...
       def _download(self, path, target): ...
       def _delete_file(self, path): ...
       # 目錄真實存在時（capabilities.directories=True）還需要：
       #   _mkdir(path)、_rmdir(path)
       # 可選擇覆寫：_walk、_copy_from、_move_from、_checksum、_read_bytes

若是物件儲存，請改為繼承 :class:`~automation_file.ObjectStorage`，並實作
``_head``、``_scan``、``_put``、``_get`` 與 ``_remove``。它提供 `內建後端`_ 一節
所述的目錄行為，``S3Storage`` 與 ``AzureStorage`` 都建立在它之上。

請用契約測試套件檢查。``tests/storage_contract.py`` 包含 81 個案例——巢狀目錄、
空檔與大檔、Unicode 路徑、二進位資料、覆寫與路徑不存在時的行為、路徑正規化、
串流、複製與搬移——並在後端確實有差異之處讀取 ``capabilities``：

.. code-block:: python

   import pytest
   from tests.storage_contract import StorageContract

   class TestVaultStorageContract(StorageContract):
       @pytest.fixture
       def backend(self):
           return VaultStorage(...)        # 每個測試都要是空的儲存

       @pytest.fixture
       def break_storage(self, backend):
           def fail(kind, times=1):          # kind: "denied" or "transient"
               backend.client.fail_next(kind, times)
           return fail

四個失敗案例（存取被拒、暫時性失敗、重試後成功、被拒的呼叫不會重試）需要
``break_storage`` fixture，它會讓接下來對服務的呼叫失敗。沒有它時，這四個案例會略過，
其餘案例照常執行。
