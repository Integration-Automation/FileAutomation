HTTP 传输
=========

可续传 HTTP 下载
----------------

:func:`~automation_file.download_file` 接受 ``resume=True``。字节会写入
``<target>.part``；若该临时文件已存在，下一次调用会发送
``Range: bytes=<n>-``，让传输从已有字节数继续。配合 ``expected_sha256=``
可在最后一块写入后立即完成校验：

.. code-block:: python

   from automation_file import download_file

   download_file(
       "https://example.com/big.bin",
       "big.bin",
       resume=True,
       expected_sha256="3b0c44298fc1...",
   )

每个 URL 都会经过
:func:`~automation_file.remote.url_validator.validate_http_url`，
拦截 ``file://`` / ``ftp://`` / ``data:`` 等 scheme 以及
私有 / loopback / link-local / 保留 / 多播 / 未指定地址的 IP。
默认 20 MB 响应上限、15 秒连接超时。TLS 验证从不关闭。

传输进度与取消
--------------

把 ``progress_name="<label>"`` 传给 :func:`download_file`、
:func:`s3_upload_file` 或 :func:`s3_download_file`，将该次传输登记到
共享的进度注册表。GUI 的 **Progress** 标签页每 0.5 秒轮询一次该注册表；
``FA_progress_list``、``FA_progress_cancel``、``FA_progress_clear``
让 JSON 动作列表也能查看同样的视图。

.. code-block:: python

   from automation_file import download_file, progress_cancel

   # 一个线程里：
   download_file("https://example.com/big.bin", "big.bin",
                 progress_name="big-download")

   # 另一个线程 / GUI：
   progress_cancel("big-download")

取消会在传输循环里抛出 :class:`~automation_file.CancelledException`。
传输函数自身捕获后将状态标为 ``status="cancelled"``，并返回 ``False``——
调用方无需自行处理该异常。
