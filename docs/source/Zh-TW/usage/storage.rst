通用儲存層
==========

``automation_file.storage`` 讓每一種儲存都使用同一套位址語法、同一組操作與同一組
例外。:class:`~automation_file.File` 與 :class:`~automation_file.Storage` 是應用層
API；:class:`~automation_file.StorageBackend` 則是後端要實作的契約。

``FA_*`` 動作與各後端原有的函式（``s3_upload_file``、``sftp_download_file`` ……）
完全不變，可與本層並用。

.. note::

   本層是新功能，API 在 1.0 之前仍可能調整。目前內建十二種後端：本機檔案系統、
   記憶體儲存、S3、Azure Blob、Google Drive、Dropbox、OneDrive、SFTP、FTP / FTPS、
   WebDAV、SMB，以及 fsspec 能存取的任何儲存。Box 沒有轉接器，只能透過它的
   ``FA_box_*`` 動作使用（見 :doc:`cloud`）。每個遠端後端都需要安裝對應的 extra
   （``pip install "automation_file[s3]"``）並初始化其用戶端，詳見 `內建後端`_
   中各自的條目。

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
     - ``uri, expected, algorithm="sha256", strict=False``
     - ``true`` / ``false``；``strict=True`` 時，不相符會擲出
       ``StorageChecksumException``
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
   * - ``StorageChecksumException``
     - 嚴格驗證（``FA_storage_verify`` 搭配 ``strict=True``）發現摘要與預期不同。

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

``SFTPStorage``（``sftp://<host>[:<port>]/<絕對路徑>``）
    透過共用的 ``sftp_instance`` 存取一個 SFTP 工作階段所能到達的檔案。開啟工作階段
    的方式與以往相同：``sftp_instance.later_init(host=..., username=..., ...)`` 或
    ``FA_sftp_later_init``；主機金鑰會與 ``known_hosts`` 比對，未知的主機一律拒絕。
    URI 的路徑就是伺服器上的絕對路徑，因此 ``sftp://nas/data/q1.csv`` 指的是
    ``/data/q1.csv``，而不是登入目錄之下的路徑。

    主機可以省略（``sftp:///data/q1.csv``），代表「已開啟的工作階段」。若寫出主機，
    它必須是工作階段所連線的那一台；比對時不分大小寫，若同時寫了連接埠，連接埠也
    必須相符。其他主機會拋出 ``StorageURIException``。要存取第二台主機，請另外
    連線一個 ``SFTPClient`` 並為它掛載後端：
    ``Storage.mount("sftp://backup", SFTPStorage(client))``。
    ``SFTPStorage(client, root="/srv/data")`` 會把每個路徑都接在某個遠端目錄之下。
    ``root`` 只是路徑前綴，並不是隔離環境：伺服器上的符號連結仍可能通往它之外。

    ``stat`` 回報伺服器傳回的大小與修改時間（UTC，精確到秒）。同一個工作階段內的
    移動是一次重新命名；複製則經由本機暫存檔，因為 SFTP 本身沒有複製功能。

    讀寫時會跟隨符號連結；刪除時絕不跟隨：只移除連結本身，不動它指向的目標。
    遞迴列出時不會進入被連結的目錄。目標已不存在的連結仍會被列出，但 ``exists``
    與 ``stat`` 會回報它不存在。

``FTPStorage``（``ftp://<host>[:<port>]/<絕對路徑>``、``ftps://…``）
    透過共用的 ``ftp_instance`` 存取一個 FTP 或 FTPS 工作階段所能到達的檔案。開啟
    工作階段的方式與以往相同：
    ``ftp_instance.later_init(host=..., username=..., password=..., tls=True)`` 或
    ``FA_ftp_later_init``。主機規則、``root=`` 與絕對路徑都和 ``SFTPStorage``
    相同；要存取第二台主機，請以另一個已連線的 ``FTPClient`` 掛載
    ``FTPStorage(client)``。除非已開啟的工作階段是以 ``tls=True`` 建立的，否則
    ``ftps://`` 會以 ``StorageURIException`` 拒絕；``ftp://`` 則兩種工作階段都接受。
    未加密的 FTP 會以明文傳送密碼與檔案內容。

    伺服器若提供 ``MLST`` / ``MLSD``（RFC 3659），``stat`` 會依伺服器的 fact 回報
    類型、大小與修改時間（UTC）。其他伺服器則以探測的方式判斷：``CWD`` 進得去的是
    目錄，``SIZE`` 與 ``MDTM`` 有回應的是檔案，列出目錄則是 ``NLST`` 再加上每個名稱
    最多三個指令。這種方式比較慢，目錄沒有修改時間，而且伺服器不在 ``NLST`` 中顯示
    的檔案（通常是名稱以點開頭的檔案）不會被列出。每次探測後都會把工作階段的工作
    目錄切回原處。

    FTP 對「沒有這個檔案」與「不允許」使用同一個回覆碼 550。``exists``、``stat``
    與列出目錄會把它視為「不存在」；上傳、下載與刪除則把它視為
    ``StoragePermissionException``。含有換行字元的路徑會以 ``StorageURIException``
    拒絕。

    不論哪一種伺服器，刪除時都絕不跟隨符號連結。列出時則視伺服器而定：``MLSD``
    會標示連結的伺服器，連結會列為檔案且不會被進入；以探測方式處理的伺服器則把
    指向目錄的連結顯示為目錄，遞迴列出時會進入其中。

SFTP 與 FTP 都有真正的目錄（``capabilities.directories`` 為 ``True``）：``mkdir``
會建立目錄，空目錄也可以存在。兩者都不回報 ETag、版本、內容類型與中繼資料，校驗碼
則由下載回來的內容計算。上傳時會先寫入目標旁邊的隱藏 ``.part`` 檔，再重新命名蓋過
目標，因此失敗的上傳絕不會留下被截斷的檔案。若伺服器不允許重新命名到已存在的檔案
之上（沒有 ``posix-rename@openssh.com`` 擴充的 SFTP、Windows 上的 FTP），會先把該
檔案移到一旁，完成後再刪除，若重新命名仍然失敗則放回原處；這種取代方式不是原子
操作。

一個工作階段一次只能執行一個操作，因此同一個工作階段上的呼叫會互相等待。
``FA_sftp_*`` / ``FA_ftp_*`` 動作不受這個機制保護：其他執行緒正透過儲存層使用某個
工作階段時，不要同時對它執行這些動作。在呼叫 ``later_init`` 之前，每個呼叫都會拋出
``StorageUnavailableException``。連線中斷或逾時會拋出
``StorageTransientException``；儲存層不會自動重新連線，重試之前請再呼叫一次
``later_init``。

.. code-block:: python

   from automation_file import (
       File, SFTPClient, SFTPStorage, Storage, ftp_instance, sftp_instance,
   )

   sftp_instance.later_init(host="nas.example", username="ops",
                            key_filename="/home/ops/.ssh/id_ed25519")
   ftp_instance.later_init(host="files.example", username="ops",
                           password=password, tls=True)

   File("sftp://nas.example/exports/q1.csv").copy_to("ftps://files.example/incoming/q1.csv")
   File("sftp:///exports/q1.csv").move_to("sftp:///archive/2026/q1.csv")   # 一次重新命名

   # 第二台主機：使用自己的用戶端，掛載在自己的 authority 之下。
   backup = SFTPClient()
   backup.later_init(host="backup.example", username="ops")
   Storage.mount("sftp://backup.example", SFTPStorage(backup, root="/srv/backups"))
   File("sftp:///archive/2026/q1.csv").copy_to("sftp://backup.example/2026/q1.csv")

``DropboxStorage``（``dropbox:///<path>``）
    透過共用的 ``dropbox_instance`` 存取 Dropbox，初始化方式與以往相同：
    ``dropbox_instance.later_init(token)`` 或 ``FA_dropbox_later_init``。authority
    必須留空：``dropbox:///reports/q1.csv`` 就是檔案 ``/reports/q1.csv``，而
    ``dropbox://reports/q1.csv`` 會被拒絕，並在錯誤訊息中給出正確寫法。
    ``DropboxStorage(client)`` 可改用另一個 ``dropbox.Dropbox`` 用戶端，``root=``
    則把後端限制在某個資料夾內；這樣的實例要掛載後才有 URI。資料夾是真正的目錄。

    ``stat`` 回報大小、伺服器端的修改時間，並以修訂版本（rev）作為 ``version``、
    以 Dropbox 的內容雜湊作為 ``etag``。超過 8 MiB 的檔案會透過上傳工作階段、每次
    8 MiB 分段上傳，因此不會整個讀進記憶體。同一個用戶端內兩個路徑之間的複製與
    搬移由 Dropbox 本身完成，刪除資料夾只需要一次請求。

    Dropbox 比對名稱時不分大小寫。複製或搬移時它不會取代既有檔案，因此會先刪除
    已存在的目標，這一步並非原子操作。用戶端尚未初始化時，每個呼叫都會拋出
    ``StorageUnavailableException``。

``WebDAVStorage``（以掛載方式使用，例如掛在 ``webdav://<host>``）
    透過 :class:`~automation_file.WebDAVClient` 存取 WebDAV 伺服器。基底 URL 與
    憑證都在用戶端上，因此沒有任何 URI 能自行解析：請把後端掛載到檔案應該出現的
    位置。``root=`` 把後端限制在基底 URL 之下的某個集合（collection）內。集合是
    真正的目錄。

    ``stat`` 是一次 ``Depth: 0`` 的 ``PROPFIND``，回報伺服器提供的大小、修改時間
    （``getlastmodified``）、``getetag`` 與 ``getcontenttype``。同一個用戶端內兩個
    路徑之間的複製與搬移由伺服器以 ``COPY`` 與 ``MOVE`` 完成；不支援這兩個方法的
    伺服器則改經本機暫存檔傳輸。刪除目錄只需要一次 ``DELETE``。HTTP 404 會拋出
    ``StorageNotFoundException``，401 與 403 拋出 ``StoragePermissionException``，
    408、429、5xx 與連線中斷則拋出 ``StorageTransientException``。

    基底 URL 會經過 ``WebDAVClient`` 的 SSRF 檢查（伺服器位於私有網路時請傳入
    ``allow_private_hosts=True``），而且預設會驗證 TLS。路徑不能以空白字元結尾。
    用戶端由呼叫端負責關閉。

``SMBStorage``（以掛載方式使用，例如掛在 ``smb://<server>/<share>``）
    透過 :class:`~automation_file.SMBClient` 存取一個 SMB / CIFS 共用資料夾；
    伺服器、共用名稱與憑證都在用戶端上。需要安裝 ``smbprotocol``
    （``pip install smbprotocol``），未安裝時每個呼叫都會拋出
    ``StorageUnavailableException``。請把後端掛載到檔案應該出現的位置。``root=``
    把後端限制在共用資料夾內的某個目錄。目錄是真正的目錄。

    ``stat`` 回報大小與修改時間。同一個用戶端內兩個路徑之間的搬移是伺服器上的
    重新命名；複製則經由本機暫存檔。``/`` 與 ``\`` 都是路徑分隔符號，不論用哪一種
    寫法，``..`` 區段都會被拒絕。用戶端由呼叫端負責關閉。

``FsspecStorage``（可掛載在任何 scheme 之下）
    把任何 `fsspec <https://filesystem-spec.readthedocs.io>`_ 檔案系統（Google
    Cloud Storage、HDFS、FTP、壓縮檔……）放到儲存契約之後。需要安裝 ``fsspec`` 與
    該服務的驅動程式（``gcsfs``、``adlfs`` ……），缺少時會拋出
    ``StorageUnavailableException``。
    ``FsspecStorage(filesystem, root=..., scheme=..., directories=...)`` 包裝一個
    檔案系統物件；
    ``FsspecStorage.from_url(url, directories=..., **storage_options)`` 則由 fsspec
    URL 建立，URL 的路徑會成為根目錄。請用你選擇的 scheme 掛載這個後端。

    ``directories`` 表示檔案系統是否保留沒有任何檔案的目錄。真正的檔案系統維持
    ``True``；物件儲存的目錄只是 key 的前綴，請傳入 ``False``。``stat`` 回報大小，
    並在檔案系統有提供時回報修改時間：``capabilities.modified_at`` 說明是否可以
    期待這個欄位，而列出目錄時只有在檔案系統的清單本身帶有時間時才會回報。同一個
    檔案系統物件內的複製與搬移由檔案系統本身完成。

    路徑一律照字面解讀：名稱中含有 ``*``、``?`` 或 ``[`` 時絕不會被當成萬用字元
    展開。fsspec 不在 SSRF 檢查的範圍內，因此後端應由設定建立，絕不要由請求輸入
    建立。本機目錄請使用 ``LocalStorage(root)``，它還能阻止符號連結離開根目錄。

.. code-block:: python

   from automation_file import (
       DropboxStorage, File, FsspecStorage, SMBClient, SMBStorage, Storage,
       WebDAVClient, WebDAVStorage, dropbox_instance,
   )

   dropbox_instance.later_init(token)
   File("dropbox:///reports/q1.csv").copy_to("local:///backup/q1.csv")
   Storage.mount("dropbox://team", DropboxStorage(root="team/shared"))

   dav = WebDAVClient("https://files.example.com/remote.php/dav", "user", password)
   Storage.mount("webdav://files.example.com", WebDAVStorage(dav))

   nas = SMBClient("nas.example.com", "projects", "user", password)
   Storage.mount("smb://nas.example.com/projects", SMBStorage(nas, root="2026"))

   Storage.mount("gcs://reports", FsspecStorage.from_url("gcs://reports", directories=False))

   File("webdav://files.example.com/reports/q1.csv").copy_to("gcs://reports/2026/q1.csv")

``GoogleDriveStorage``（``gdrive://<root>/<path>``）
    透過共用的 ``driver_instance`` 存取「我的雲端硬碟」，初始化方式與以往相同：
    ``driver_instance.later_init(token_path, credentials_path)`` 或
    ``FA_drive_later_init``。URI 的 authority 是作為根目錄的資料夾 ID，留空或
    寫成 ``root`` 則代表「我的雲端硬碟」：``gdrive:///reports/q1.csv``、
    ``gdrive://<folder-id>/q1.csv``。在程式中即
    ``GoogleDriveStorage(root_id="<folder-id>")``；共用雲端硬碟的 ID 也可以，
    ``GoogleDriveStorage(client)`` 則可改用另一個 ``GoogleDriveClient``。

    Drive 以 ID 而非路徑來定址，因此每次呼叫都會逐層資料夾查找路徑，呼叫之間
    不保留任何結果。名稱採完全比對：``Report.txt`` 與 ``report.txt`` 是兩個
    項目。Drive 也允許同一個資料夾內有多個同名項目；這樣的路徑無法指向單一
    項目，因此對它的每個呼叫都會拋出 ``StorageException``，並說明有幾個項目
    共用該名稱，絕不會從中挑選一個。列出目錄時仍會顯示每一個同名項目。名稱
    含有 ``/`` 的項目同樣無法寫成路徑，列出時會略過它，並在記錄檔留下警告。
    垃圾桶中的項目對這個後端而言並不存在。

    資料夾是真實的目錄。寫入已有檔案的路徑時，會上傳該檔案的新修訂版本，因此
    檔案的 ID、連結與共用設定都會保留；複製或搬移到既有檔案上也是如此。在同一
    個用戶端之內複製或搬移到新路徑時由 Drive 本身完成，搬移會保留 ID。
    ``delete`` 是永久刪除，不經過垃圾桶，資料夾會連同其中所有內容一併刪除。

    Google 文件、試算表、簡報以及其他 ``application/vnd.google-apps.*`` 類型
    沒有二進位內容。它們在列出時 ``size=None``，可以複製、搬移與刪除，但
    ``download``、``read_bytes`` 與 ``checksum`` 會拋出
    ``StorageUnsupportedException``，也不能用檔案覆寫它們。不會匯出成其他
    格式，也不會跟隨捷徑。

    ``stat`` 回報大小、修改時間、作為 ETag 的 Drive MD5、版本號與 MIME 類型。
    ``checksum`` 對 MD5、SHA-1 與 SHA-256 直接回傳 Drive 為該檔案保存的值，
    不需下載；其他演算法則由內容計算。

    限制：路徑的每一層都要一次請求；而且 Drive 不保證名稱唯一，兩個寫入者若
    同時建立同一個新路徑，會留下兩個同名項目。

``OneDriveStorage``（``onedrive:///<path>``）
    透過共用的 ``onedrive_instance`` 存取已登入使用者的 OneDrive，初始化方式
    與以往相同：``onedrive_instance.later_init(access_token)``、
    ``onedrive_instance.device_code_login(client_id)`` 或對應的
    ``FA_onedrive_*`` 動作。URI 的 authority 一律留空：
    ``onedrive:///reports/q1.csv``。在該位置寫了東西
    （``onedrive://reports/q1.csv``）會被拒絕，並提示正確寫法。
    ``OneDriveStorage(root="backups/2026")`` 把後端限制在某個資料夾內，該
    資料夾必須已經存在；``OneDriveStorage(client)`` 則可改用另一個
    ``OneDriveClient``。

    資料夾是真實的目錄。OneDrive 比對名稱時不分大小寫，但會保留寫入時的
    大小寫，因此 ``Report.txt`` 與 ``report.txt`` 是同一個項目，名稱在所屬
    資料夾內是唯一的。名稱含有 OneDrive 禁用的字元（``" * : < > ? \ |``）時會
    被服務拒絕，並拋出 ``StorageException``。

    4 MiB 以內的檔案以單一請求上傳。更大的檔案透過上傳工作階段，以 10 MiB 的
    分段邊讀邊送；下載則以串流寫入磁碟，因此兩者都不會把整個檔案放進記憶體。
    寫入已有檔案的路徑時會取代其內容並保留該項目；複製或搬移到既有檔案上也是
    如此。在同一個用戶端之內搬移到新路徑時由 OneDrive 本身完成，複製則經過
    本機暫存檔。``delete`` 會把項目送進資源回收筒，資料夾會連同其中所有內容
    一併送入。

    ``stat`` 回報大小、修改時間、ETag 與 MIME 類型，沒有版本。校驗碼由內容
    計算。

    限制：只能存取已登入使用者自己的雲端硬碟；而且用戶端不會更新存取權杖，
    權杖過期後每個呼叫都會拋出 ``StoragePermissionException``，直到安裝新的
    權杖為止。

Google Drive 與 OneDrive 都有真實的目錄，因此 ``mkdir`` 會建立資料夾，空目錄
也可以存在（``capabilities.directories`` 為 ``True``）。兩個服務都會限流：收到
限流回應、伺服器錯誤或連線中斷時會拋出 ``StorageTransientException``，可交給
``retry_on_transient`` 重試。用戶端尚未初始化時，每個呼叫都會拋出
``StorageUnavailableException``。

.. code-block:: python

   from automation_file import File, driver_instance, onedrive_instance

   driver_instance.later_init("token.json", "credentials.json")
   onedrive_instance.later_init(access_token)
   File("gdrive:///reports/2026/q1.csv").copy_to("onedrive:///backups/2026/q1.csv")

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
   Storage.schemes()                                  # ['azure', 'dropbox', 'ftp', 'ftps', 'gdrive', 'local', 'memory',
                                                      #  'onedrive', 's3', 'sandbox', 'sftp', 'vault']

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

請用契約測試套件檢查。``tests/storage_contract.py`` 包含 88 個案例——巢狀目錄、
空檔與大檔、Unicode 路徑、二進位資料、覆寫與路徑不存在時的行為、路徑正規化、
串流、複製與搬移，以及後端宣告會填入的 ``FileInfo`` 欄位——並在後端確實有差異之處讀取
``capabilities``。後端沒有宣告的欄位必須不存在，因此這些旗標所承諾的不會比 ``stat``
實際給出的多，也不會少：

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
