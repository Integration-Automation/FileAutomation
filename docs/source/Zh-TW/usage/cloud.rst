雲端與 SFTP 後端
================

每個後端的動作都由
:func:`~automation_file.core.action_registry.build_default_registry` 註冊，無論其
SDK 是否已安裝。SDK 本身則由 extra 提供：``pip install "automation_file[s3]"``
（另有 ``azure``、``gdrive``、``dropbox``、``sftp``、``onedrive``、``box``、
``smb``、``fsspec``），或以 ``[all]`` 安裝所有後端。使用缺少 extra 的後端時會拋出
``OptionalDependencyException``，訊息中附有要執行的指令。SDK 就緒後，在單例上呼叫
``later_init`` 即可使用：

.. code-block:: python

   from automation_file import execute_action, s3_instance

   s3_instance.later_init(region_name="us-east-1")

   execute_action([
       ["FA_s3_upload_file", {"local_path": "report.csv",
                              "bucket": "reports", "key": "report.csv"}],
   ])

所有後端都暴露相同的五種操作：``upload_file``、``upload_dir``、
``download_file``、``delete_*``、``list_*``。如需建立自訂註冊表，
``register_<backend>_ops(registry)`` 仍是公開 API。

Google Drive
------------

.. code-block:: python

   from automation_file import driver_instance, drive_upload_to_drive

   driver_instance.later_init("token.json", "credentials.json")
   drive_upload_to_drive("example.txt")

OAuth 憑證以 UTF-8 寫入呼叫方提供的 ``token_path``。
切勿輸出或記錄該檔案內容。

SFTP
----

:class:`~automation_file.SFTPClient` 採用 :class:`paramiko.RejectPolicy`——
未知主機會被拒絕，而非自動加入。請顯式提供 ``known_hosts=`` 或依賴
``~/.ssh/known_hosts``。不要為了方便而換成 ``AutoAddPolicy``。

跨後端複製
----------

``FA_copy_between``（``copy_between(source, target)``）把一個檔案從某個位置複製到
另一個位置，傳輸完成時回傳 ``True``。它是 ``File(source).copy_to(target)`` 的舊寫法，
建立在儲存層之上（:doc:`storage`）：兩個後端能直接互傳時會採用原生複製，目標位置已有
的檔案會被取代，而且這次操作會送達儲存觀察者與稽核軌跡。

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_copy_between",
        {"source": "s3://reports/2026-04.csv",
         "target": "azure://backups/april.csv"}],
   ])

它接受：

* 任何儲存 URI：``s3://bucket/key``、``azure://container/blob``（或 ``az://``）、
  ``gdrive:///path``、``onedrive:///path``、``dropbox:///path``、
  ``sftp://host/absolute/path``、``memory://name/path``，或掛載的前綴；
* 一般的檔案系統路徑、``local:<path>`` 或 ``local:/path``；
* 它一直以來接受的寫法：``s3:bucket/key``、``azure:container/blob`` 與
  ``dropbox:/path``；
* 只有一個斜線或沒有斜線的 ``sftp:/path`` 與 ``ftp:/path``，路徑相對於工作階段登入時
  所在的目錄，與以往相同。寫成兩個斜線（``sftp://host/path``）時，URI 指定的是主機
  與絕對路徑，而且主機必須是工作階段實際連線的那一台；
* ``http://`` / ``https://`` 只能作為來源，透過經過驗證的下載器取得（:doc:`transfer`）。

每個後端都必須先初始化（``s3_instance.later_init(...)`` 等）。傳輸本身失敗時（來源不
存在、寫入被拒、把檔案複製到它自己）函式回傳 ``False`` 並記錄原因；無法理解的位置會
拋出 ``CrossBackendException``，尚未初始化的後端會拋出
``StorageUnavailableException``。

新的程式建議使用 ``FA_storage_copy``（:doc:`storage`）：它接受儲存 URI，會回報複製的
結果，失敗時拋出明確的例外，而不是回傳 ``False``。
