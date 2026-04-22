進度與取消
==========

傳輸的可選儀表化。對 :func:`~automation_file.download_file`、
:func:`s3_upload_file` 或 :func:`s3_download_file` 傳入
``progress_name="<label>"``，傳輸即會登錄到共享的
:data:`~automation_file.core.progress.progress_registry`。接著 GUI 或
JSON 動作即可輪詢 reporter 快照，或在傳輸中途取消。

.. automodule:: automation_file.core.progress
   :members:
