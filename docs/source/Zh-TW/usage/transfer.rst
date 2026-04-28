HTTP 傳輸
=========

可續傳 HTTP 下載
----------------

:func:`~automation_file.download_file` 接受 ``resume=True``。位元組會寫入
``<target>.part``；若該臨時檔案已存在，下次呼叫會送出
``Range: bytes=<n>-``，讓傳輸從現有位元組數繼續。搭配
``expected_sha256=`` 可在最後一塊寫入後立刻驗證：

.. code-block:: python

   from automation_file import download_file

   download_file(
       "https://example.com/big.bin",
       "big.bin",
       resume=True,
       expected_sha256="3b0c44298fc1...",
   )

每個 URL 都會通過
:func:`~automation_file.remote.url_validator.validate_http_url`，
攔截 ``file://`` / ``ftp://`` / ``data:`` 等 scheme，以及
私有 / loopback / link-local / 保留 / 多播 / 未指定地址的 IP。
預設 20 MB 回應上限、15 秒連線逾時。TLS 驗證從不關閉。

傳輸進度與取消
--------------

把 ``progress_name="<label>"`` 傳給 :func:`download_file`、
:func:`s3_upload_file` 或 :func:`s3_download_file`，將該次傳輸登錄到
共用進度註冊表。GUI 的 **Progress** 分頁每 0.5 秒輪詢一次該註冊表；
``FA_progress_list``、``FA_progress_cancel``、``FA_progress_clear``
讓 JSON 動作清單也能取得相同視圖。

.. code-block:: python

   from automation_file import download_file, progress_cancel

   # 一個執行緒裡：
   download_file("https://example.com/big.bin", "big.bin",
                 progress_name="big-download")

   # 另一個執行緒 / GUI：
   progress_cancel("big-download")

取消會在傳輸迴圈中擲出 :class:`~automation_file.CancelledException`。
傳輸函式會自行捕獲並把狀態標為 ``status="cancelled"``，回傳 ``False``——
呼叫方無需自行處理該例外。
