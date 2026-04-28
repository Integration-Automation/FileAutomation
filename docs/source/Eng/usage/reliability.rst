Reliability
===========

Apply retries to your own callables:

.. code-block:: python

   from automation_file import retry_on_transient

   @retry_on_transient(max_attempts=5, backoff_base=0.5)
   def flaky_network_call(): ...

The decorator only retries the exception types passed via ``retriable=(…)``
(default: ``ConnectionError`` / ``TimeoutError`` / ``OSError``). Never
widen to bare ``Exception`` — that masks logic bugs as transient failures.
Always exhausts to :class:`~automation_file.RetryExhaustedException`
chained with ``raise ... from err``.

Enforce per-action limits:

.. code-block:: python

   from automation_file import Quota

   quota = Quota(max_bytes=50 * 1024 * 1024, max_seconds=30.0)
   with quota.time_budget("bulk-upload"):
       bulk_upload_work()

   # Or wrap a callable directly:
   @quota.wraps
   def expensive(payload: bytes) -> None: ...

``0`` disables each cap individually.
