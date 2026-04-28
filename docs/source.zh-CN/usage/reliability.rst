可靠性
======

为自家的可调用对象套上重试：

.. code-block:: python

   from automation_file import retry_on_transient

   @retry_on_transient(max_attempts=5, backoff_base=0.5)
   def flaky_network_call(): ...

该装饰器只重试 ``retriable=(…)`` 中明确列出的异常类型
（默认是 ``ConnectionError`` / ``TimeoutError`` / ``OSError``）。
切勿放宽到裸 ``Exception``——那会把逻辑 bug 当成瞬时失败掩盖掉。
重试耗尽后会抛出 :class:`~automation_file.RetryExhaustedException`，
并通过 ``raise ... from err`` 链回最后一次原因。

为单个动作设置上限：

.. code-block:: python

   from automation_file import Quota

   quota = Quota(max_bytes=50 * 1024 * 1024, max_seconds=30.0)
   with quota.time_budget("bulk-upload"):
       bulk_upload_work()

   # 也可以直接装饰可调用对象：
   @quota.wraps
   def expensive(payload: bytes) -> None: ...

每个上限设置为 ``0`` 即表示禁用该项检查。
