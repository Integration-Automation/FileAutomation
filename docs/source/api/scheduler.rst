Scheduler
=========

Cron-style scheduler for recurring action lists. The parser understands the
standard 5-field syntax (minute hour day-of-month month day-of-week) with
``*``, ranges, lists, and ``*/n`` steps plus month / day-of-week aliases. A
background thread wakes on minute boundaries and dispatches every matching
job through the shared :class:`ActionExecutor`.

.. automodule:: automation_file.scheduler
   :members:

.. automodule:: automation_file.scheduler.cron
   :members:

.. automodule:: automation_file.scheduler.manager
   :members:
