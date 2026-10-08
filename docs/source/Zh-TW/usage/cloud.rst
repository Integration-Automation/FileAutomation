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

``FA_copy_between``（``copy_between(source, target)``）透過本機暫存檔，把一個檔案
從某個後端複製到另一個後端，兩個階段都成功時回傳 ``True``：

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_copy_between",
        {"source": "s3://reports/2026-04.csv",
         "target": "azure://backups/april.csv"}],
   ])

它接受 ``s3://bucket/key``、``azure://container/blob``（或 ``az://``）、
``dropbox:/path``、``sftp:/path``、``ftp:/path``、``local:/path`` 或一般的檔案系統
路徑；``http://`` / ``https://`` 只能作為來源。每個後端都必須先初始化
（``s3_instance.later_init(...)`` 等）。沒有 Google Drive 的 scheme：Drive 以 ID
定位檔案，請改用 ``FA_drive_*`` 動作。

新的程式建議使用儲存層（:doc:`storage`）：``FA_storage_copy`` 接受同類型的 URI，
會回報複製的結果，失敗時拋出明確的例外，而不是回傳 ``False``。
