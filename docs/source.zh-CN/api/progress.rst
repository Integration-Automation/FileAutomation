进度与取消
==========

传输的可选仪表化。对 :func:`~automation_file.download_file`、
:func:`s3_upload_file` 或 :func:`s3_download_file` 传入
``progress_name="<label>"``，传输即会注册到共享的
:data:`~automation_file.core.progress.progress_registry`。之后 GUI 或
JSON 动作即可轮询 reporter 快照，或在传输中途取消。

.. automodule:: automation_file.core.progress
   :members:
