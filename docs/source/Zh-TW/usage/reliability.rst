可靠性
======

為自家的可呼叫物件套上重試：

.. code-block:: python

   from automation_file import retry_on_transient

   @retry_on_transient(max_attempts=5, backoff_base=0.5)
   def flaky_network_call(): ...

該裝飾器只重試 ``retriable=(…)`` 中明確列出的例外型別
（預設為 ``ConnectionError`` / ``TimeoutError`` / ``OSError``）。
切勿放寬到裸 ``Exception``——那會把邏輯 bug 當成瞬時失敗掩蓋。
重試耗盡後會擲出 :class:`~automation_file.RetryExhaustedException`，
並透過 ``raise ... from err`` 鏈回最後一次原因。

為單一動作設定上限：

.. code-block:: python

   from automation_file import Quota

   quota = Quota(max_bytes=50 * 1024 * 1024, max_seconds=30.0)
   with quota.time_budget("bulk-upload"):
       bulk_upload_work()

   # 也可以直接裝飾可呼叫物件：
   @quota.wraps
   def expensive(payload: bytes) -> None: ...

每個上限設成 ``0`` 即表示停用該項檢查。
